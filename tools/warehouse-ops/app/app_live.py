"""Live VSS access: lazy clients, explore-based source refresh, playback authorization and YOLO overlays.

Segment URIs can change after a re-ingest, so the app maps every stored URI to the *current* one
through the live explore inventory (keyed by the chunk file name without its upload timestamp,
then by time inside the chunk). Stored URIs are the fallback when VSS is unreachable.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from requests.adapters import HTTPAdapter

import vss_client
from app_data import Snapshot, basename, num, stable_chunk_name

log = logging.getLogger("wops.live")
LOCATIONS = ("indoor", "warehouse3")
_W017 = re.compile(r"_Warehouse_(\d+)_(Camera(?:_\d+)?)_chunk_(\d+)")
_W3 = re.compile(r"_run_(\d+)_seed_\d+\.(ceiling|eye)_(\d+)\.rgb_chunk_(\d+)")
# COCO classes that YOLO hallucinates on this footage; never useful as warehouse machines.
IGNORED_LABELS = {
    "sports ball", "traffic light", "airplane", "kite", "frisbee", "bird", "dog", "cat", "horse", "sheep", "cow",
    "oven", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush", "umbrella",
    "tie", "skis", "snowboard", "skateboard", "surfboard", "tennis racket", "baseball bat", "baseball glove",
    "fire hydrant", "stop sign", "parking meter", "potted plant", "bed", "dining table", "couch", "wine glass",
    "cup", "fork", "knife", "spoon", "bowl", "bottle", "banana", "apple", "sandwich", "orange", "broccoli",
    "carrot", "hot dog", "pizza", "donut", "cake", "handbag", "backpack",
}


def parse_site_camera(filename: str) -> tuple[str, str] | None:
    m = _W017.search(filename or "")
    if m:
        return f"w{m.group(1)}", m.group(2)
    m = _W3.search(filename or "")
    if m:
        return f"w3_run{m.group(1)}", f"{m.group(2)}_{m.group(3)}"
    return None


def safe_error(e: BaseException) -> str:
    """Error text that is safe to log or return: never includes URLs (stream URLs carry the token)."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


class Clients:
    """Lazily-created shared clients. VSS() probes endpoints on construction, so build it off the request path."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._vss: vss_client.VSS | None = None
        self._failed_at = 0.0
        self.cosmos = vss_client.Cosmos()

    def vss(self) -> vss_client.VSS:
        if self._vss is not None:
            return self._vss
        with self._lock:
            if self._vss is None:
                if time.time() - self._failed_at < 20:
                    raise RuntimeError("VSS backend unavailable")
                client = vss_client.VSS()
                if not client.base:
                    self._failed_at = time.time()
                    raise RuntimeError("VSS backend not configured")
                adapter = HTTPAdapter(pool_connections=4, pool_maxsize=48)
                client.session.mount("https://", adapter)
                client.session.mount("http://", adapter)
                self._vss = client
        return self._vss

    def reset(self, error: BaseException) -> None:
        """Forget the client after connection-level failures so the backend URL is re-resolved."""
        if isinstance(error, (requests.ConnectionError, requests.Timeout)):
            with self._lock:
                self._vss, self._failed_at = None, time.time()

    @property
    def vss_ready(self) -> bool:
        return self._vss is not None


class LiveSources:
    def __init__(self, clients: Clients) -> None:
        self.clients = clients
        self._lock = threading.Lock()
        self.chunks: dict[str, dict] = {}
        self.by_video: dict[str, str] = {}
        self.sources: set[str] = set()
        self.vouched: set[str] = set()
        self.refreshed_at: float | None = None
        self.error: str | None = None

    def refresh(self) -> bool:
        try:
            vss = self.clients.vss()
            items: list[dict] = []
            for loc in LOCATIONS:
                items.extend(vss.explore_all(loc))
        except Exception as e:  # noqa: BLE001
            self.error = safe_error(e)
            self.clients.reset(e)
            log.warning("explore refresh failed: %s", self.error)
            return False
        chunks: dict[str, dict] = {}
        sources: set[str] = set()
        for it in items:
            video = it.get("original_video") or ""
            if not video:
                continue
            timeline = sorted(
                ((num(tl.get("segment_start_sec")), num(tl.get("segment_end_sec")), int(num(tl.get("segment_number"))),
                  tl.get("source")) for tl in it.get("timeline") or [] if tl.get("source")),
                key=lambda x: x[0])
            sources.add(video)
            sources.update(t[3] for t in timeline)
            if it.get("preview_source"):
                sources.add(it["preview_source"])
            key = stable_chunk_name(it.get("filename") or video)
            stamp = str(it.get("upload_timestamp") or "")
            prev = chunks.get(key)
            if prev and prev["upload_timestamp"] > stamp:
                continue
            chunks[key] = {"original_video": video, "upload_timestamp": stamp, "timeline": timeline,
                           "filename": it.get("filename") or basename(video), "location": it.get("location")}
        with self._lock:
            self.chunks = chunks
            self.by_video = {c["original_video"]: k for k, c in chunks.items()}
            self.sources = sources
        self.refreshed_at, self.error = time.time(), None
        log.info("live inventory: %d chunks, %d playable URIs", len(chunks), len(sources))
        return True

    def vouch(self, uris: list[str]) -> None:
        with self._lock:
            if len(self.vouched) > 5000:
                self.vouched.clear()
            self.vouched.update(u for u in uris if u)

    def _live_segment(self, ref: dict) -> str | None:
        live = self.chunks.get(stable_chunk_name(ref.get("filename") or ref.get("original_video")))
        if not live:
            return None
        mid = (num(ref.get("scene_t0")) + num(ref.get("scene_t1"))) / 2 - num(ref.get("chunk_scene_t0"))
        for t0, t1, _n, src in live["timeline"]:
            if t0 <= mid < t1:
                return src
        return next((src for _t0, _t1, n, src in live["timeline"] if n == ref.get("n")), None)

    def resolve(self, source: str, snap: Snapshot) -> str | None:
        """Current playable URI for a stored or live URI; None if the URI is not ours to serve."""
        if not source or not source.startswith("s3://"):
            return None
        ref = snap.seg_by_source.get(source)
        if ref:
            return self._live_segment(ref) or source
        chunk = snap.chunk_by_video.get(source)
        if chunk:
            live = self.chunks.get(stable_chunk_name(chunk.get("filename") or source))
            return live["original_video"] if live else source
        if source in snap.known_sources or source in self.sources or source in self.vouched:
            return source
        return None

    def chunk_parts(self, resolved: str, snap: Snapshot) -> list[tuple[str, float]]:
        """(segment URI, offset inside the chunk) for a chunk URI; [] when the URI is a segment."""
        key = self.by_video.get(resolved)
        if key:
            return [(src, t0) for t0, _t1, _n, src in self.chunks[key]["timeline"]]
        ref = snap.chunk_by_video.get(resolved)
        if ref:
            return [(self.resolve(s.get("source") or "", snap) or s.get("source") or "",
                     num(s.get("scene_t0")) - ref["scene_t0"]) for s in ref["segments"] if s.get("source")]
        return []

    def status(self) -> dict:
        return {"chunks": len(self.chunks), "refreshed_at": self.refreshed_at, "error": self.error}


def compact_detections(raw: dict | None, stride: int) -> dict:
    if not raw:
        return {"fps": 30.0, "width": 1920, "height": 1080, "frames": [], "available": False}
    fps = num(raw.get("fps"), 30.0) or 30.0
    shape = raw.get("video_shape") or [1080, 1920]
    frames = []
    for fr in (raw.get("frames") or [])[::max(1, stride)]:
        t = fr.get("time_sec")
        t = num(t) if t is not None else num(fr.get("frame_index")) / fps
        boxes = []
        for d in fr.get("detections") or []:
            label = str(d.get("label") or "")
            conf = num(d.get("confidence"))
            bbox = d.get("bbox") or []
            if len(bbox) < 4 or (label != "person" and (conf < 0.3 or label in IGNORED_LABELS)):
                continue
            boxes.append([round(num(bbox[0])), round(num(bbox[1])), round(num(bbox[2])), round(num(bbox[3])),
                          label, round(conf, 2)])
        frames.append({"t": round(t, 3), "boxes": boxes})
    return {"fps": fps, "width": int(num(shape[1], 1920)), "height": int(num(shape[0], 1080)), "frames": frames,
            "available": True}


class Detections:
    """Per-segment YOLO sidecars, compacted and LRU-cached; chunk URIs are stitched from their segments."""

    def __init__(self, clients: Clients, live: LiveSources, max_items: int = 160) -> None:
        self.clients = clients
        self.live = live
        self._cache: OrderedDict[tuple, dict] = OrderedDict()
        self._max = max_items
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="det")

    def _cached(self, key: tuple) -> dict | None:
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
            return hit

    def _store(self, key: tuple, value: dict) -> None:
        with self._lock:
            self._cache[key] = value
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def segment(self, source: str, stride: int) -> dict:
        key = ("seg", source, stride)
        hit = self._cached(key)
        if hit is None:
            hit = compact_detections(self.clients.vss().detections(source), stride)
            self._store(key, hit)
        return hit

    def get(self, resolved: str, stride: int, snap: Snapshot) -> dict[str, Any]:
        parts = self.live.chunk_parts(resolved, snap)
        if not parts:
            return self.segment(resolved, stride)
        key = ("chunk", resolved, stride)
        hit = self._cached(key)
        if hit is not None:
            return hit

        def load(part: tuple[str, float]) -> tuple[float, dict | None]:
            try:
                return part[1], self.segment(part[0], stride)
            except Exception as e:  # noqa: BLE001
                log.warning("detections for one segment failed: %s", safe_error(e))
                return part[1], None

        results = list(self._pool.map(load, parts))
        ok = [(off, d) for off, d in results if d]
        if not ok:
            raise RuntimeError("no detections available")
        first = ok[0][1]
        frames = sorted(({"t": round(f["t"] + off, 3), "boxes": f["boxes"]} for off, d in ok for f in d["frames"]),
                        key=lambda f: f["t"])
        merged = {"fps": first["fps"], "width": first["width"], "height": first["height"], "frames": frames,
                  "available": any(d.get("available") for _, d in ok)}
        if len(ok) == len(results):
            self._store(key, merged)
        return merged
