"""Cosmos3 calls with clip re-encoding, a GPU concurrency limit and an on-disk response cache."""
from __future__ import annotations

import base64
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

import imageio_ffmpeg

import prompts
from common import basename_noext, cache_path, cosmos, extract_json, log, read_json, stable_hash, vss_client, write_json
from fetch import Downloader
from inventory import Segment

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
ENC_WIDTH, ENC_FPS, ENC_CRF = 1280, 8, 26


def encode_clip(paths: list[str], name: str, force: bool = False) -> str:
    """Re-encode (and concatenate) clips to h264 at ENC_WIDTH px / ENC_FPS fps without audio."""
    out = cache_path("media", "enc", f"{name}_{ENC_WIDTH}p{ENC_FPS}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 0 and not force:
        return out
    if len(paths) == 1:
        inputs = ["-i", paths[0]]
    else:
        listing = out + ".txt"
        with open(listing, "w", encoding="utf-8") as f:
            f.writelines(f"file '{p.replace(os.sep, '/')}'\n" for p in paths)
        inputs = ["-f", "concat", "-safe", "0", "-i", listing]
    tmp = out[:-4] + ".part.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *inputs, "-vf", f"scale={ENC_WIDTH}:-2,fps={ENC_FPS}", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", str(ENC_CRF), "-pix_fmt", "yuv420p", tmp],
                   check=True, capture_output=True)
    os.replace(tmp, out)
    return out


class VLM:
    """Cache-first Cosmos client. Video clips are produced lazily, only on a cache miss."""

    def __init__(self, concurrency: int = 3, force: bool = False) -> None:
        self._sem = threading.Semaphore(concurrency)
        self._lock = threading.Lock()
        self.force = force
        self.stats = {"calls": 0, "cached": 0, "failed": 0, "gpu_seconds": 0.0}

    @property
    def model(self) -> str:
        return cosmos().model

    def _bump(self, key: str, by: float = 1) -> None:
        with self._lock:
            self.stats[key] += by

    def ask(self, kind: str, prompt: str, *, validate: Callable, cache_key: list, video: Callable[[], str] | None = None,
            max_tokens: int = 1200, temperature: float = 0.2, meta: dict | None = None) -> dict | None:
        key = stable_hash(prompts.PROMPT_VERSION, kind, self.model, prompts.SYSTEM, prompt, cache_key, max_tokens,
                          temperature)
        path = cache_path("vlm", f"{kind}_{key}.json")
        if not self.force:
            hit = read_json(path)
            if hit is not None:
                self._bump("cached")
                return hit
        content: list | str = prompt
        if video is not None:
            with open(video(), "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content = [vss_client.Cosmos.video_part(b64), {"type": "text", "text": prompt}]
        for attempt in range(2):
            with self._sem:
                t0 = time.time()
                try:
                    raw = cosmos().chat(content, max_tokens=max_tokens, temperature=temperature, system=prompts.SYSTEM)
                except Exception as e:  # noqa: BLE001
                    log(f"cosmos {kind} call failed: {type(e).__name__}: {str(e)[:120]}")
                    self._bump("failed")
                    return None
                latency = time.time() - t0
            self._bump("calls")
            self._bump("gpu_seconds", latency)
            try:
                parsed = validate(extract_json(raw))
            except (ValueError, TypeError, AttributeError) as e:
                log(f"cosmos {kind} reply not usable (attempt {attempt + 1}): {e}")
                continue
            rec = {"kind": kind, "meta": meta or {}, "model": self.model, "latency_sec": round(latency, 2),
                   "json": parsed, "raw": raw, "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            write_json(path, rec)
            return rec
        self._bump("failed")
        return None


def run_w017(vlm: VLM, downloader: Downloader, segs: list[Segment], kin: dict, workers: int = 6) -> dict[str, dict]:
    """One call per 5 s segment."""
    by_id = {s.seg_id: s for s in segs}

    def job(seg_id: str) -> dict | None:
        seg = by_id[seg_id]

        def clip() -> str:
            return encode_clip([downloader.get(seg.source).result()], basename_noext(seg.source))
        return vlm.ask("w017", prompts.w017_prompt(seg.camera, seg.view, kin[seg_id]),
                       validate=prompts.normalize_w017, cache_key=[seg.source], video=clip, meta={"seg_id": seg_id})

    return _run_jobs("w017", job, list(by_id), workers)


def run_w017_checks(vlm: VLM, downloader: Downloader, moments: list[dict], workers: int = 6) -> dict[str, dict]:
    """One targeted question per candidate or control moment (see fusion.w017_moments), on the 5 s segment clip."""
    by_key = {m["key"]: m for m in moments}

    def job(key: str) -> dict | None:
        m = by_key[key]
        seg = m["seg"]

        def clip() -> str:
            return encode_clip([downloader.get(seg.source).result()], basename_noext(seg.source))
        return vlm.ask("w017_check", prompts.w017_check_prompt(seg.camera, seg.view, *m["window"], m["region"]),
                       validate=prompts.normalize_w017_check, cache_key=[seg.source], video=clip, max_tokens=400,
                       meta={"seg_id": seg.seg_id, "role": m["role"], "t": m["t"], "region": m["region"]})

    return _run_jobs("w017_check", job, list(by_key), workers)


def run_w3(vlm: VLM, downloader: Downloader, cams: dict[tuple, list[Segment]], cam_kin: dict,
           workers: int = 6) -> dict[tuple, dict]:
    """One call per (run, camera) on the full 10 s clip (segments concatenated)."""
    def job(key: tuple) -> dict | None:
        segs = cams[key]

        def clip() -> str:
            return encode_clip([downloader.get(s.source).result() for s in segs], f"{key[0]}_{key[1]}_full")
        return vlm.ask("w3", prompts.w3_prompt(key[1], segs[0].view, cam_kin[key]), validate=prompts.normalize_w3,
                       cache_key=[s.source for s in segs], video=clip, meta={"site_id": key[0], "camera": key[1]})

    return _run_jobs("w3", job, list(cams), workers)


def _run_jobs(kind: str, job: Callable, keys: list, workers: int) -> dict:
    def safe(key):
        try:
            return key, job(key)
        except Exception as e:  # noqa: BLE001  (one bad clip must not abort the pass)
            log(f"vlm {kind} job {key} failed: {type(e).__name__}: {str(e)[:120]}")
            return key, None

    out, done = {}, 0
    with ThreadPoolExecutor(workers) as pool:
        for key, rec in pool.map(safe, keys):
            done += 1
            if rec is not None:
                out[key] = rec
            if done % 20 == 0 or done == len(keys):
                log(f"vlm {kind}: {done}/{len(keys)} done, {len(out)} usable")
    return out
