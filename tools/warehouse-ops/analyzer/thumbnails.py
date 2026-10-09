"""Build one JPEG contact sheet with a thumbnail per indexed video (chunk) for the app's video library.

Frames come from the segment clips the analyzer already downloaded into .cache/media; a chunk with a
safety event uses the frame at the event time. Writes app/data_thumbs.jpg plus app/data_thumbs.json,
which maps each chunk's filename to its tile.

Run: python tools/warehouse-ops/analyzer/thumbnails.py
"""
from __future__ import annotations

import io
import math
import os
import subprocess

import imageio_ffmpeg
from PIL import Image

from common import APP_DIR, log, read_json, write_json
from fetch import media_path

TILE_W, TILE_H, COLS, QUALITY = 256, 144, 8, 72
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def grab(path: str, t: float) -> Image.Image | None:
    cmd = [FFMPEG, "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", path, "-frames:v", "1",
           "-vf", f"scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=increase,crop={TILE_W}:{TILE_H}",
           "-f", "image2pipe", "-vcodec", "png", "-"]
    out = subprocess.run(cmd, capture_output=True, check=False)
    if out.returncode or not out.stdout:
        return None
    return Image.open(io.BytesIO(out.stdout)).convert("RGB")


def frame_for(chunk: dict, event_t: float | None) -> Image.Image | None:
    segments = sorted(chunk.get("segments") or [], key=lambda s: s.get("scene_t0", 0))
    if event_t is not None:
        hit = next((s for s in segments if s["scene_t0"] <= event_t < s["scene_t1"]), None)
        if hit:
            segments = [hit] + [s for s in segments if s is not hit]
    for seg in segments:
        path = media_path(seg.get("source") or "")
        if not os.path.exists(path):
            continue
        t = event_t - seg["scene_t0"] if event_t is not None and seg["scene_t0"] <= event_t < seg["scene_t1"] else 1.5
        img = grab(path, t)
        if img is not None:
            return img
    return None


def main() -> None:
    videos = read_json(os.path.join(APP_DIR, "data_videos.json"), {})
    events = read_json(os.path.join(APP_DIR, "data_events.json"), [])
    event_t: dict[str, float] = {}
    for e in events:
        if e.get("original_video") and e.get("original_video") not in event_t:
            event_t[e["original_video"]] = float(e.get("scene_t") or 0)

    chunks = [ch for site in videos.get("sites", []) for cam in site.get("cameras", []) for ch in cam.get("chunks", [])]
    rows = math.ceil(len(chunks) / COLS)
    sheet = Image.new("RGB", (COLS * TILE_W, rows * TILE_H), (6, 10, 18))
    tiles: dict[str, int] = {}
    for i, ch in enumerate(chunks):
        img = frame_for(ch, event_t.get(ch.get("original_video", "")))
        if img is None:
            log(f"no local clip for {ch.get('filename')}; tile left blank")
            continue
        sheet.paste(img, ((i % COLS) * TILE_W, (i // COLS) * TILE_H))
        tiles[ch["filename"]] = i

    jpg = os.path.join(APP_DIR, "data_thumbs.jpg")
    sheet.save(jpg, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    write_json(os.path.join(APP_DIR, "data_thumbs.json"),
               {"tile_w": TILE_W, "tile_h": TILE_H, "cols": COLS, "rows": rows, "tiles": tiles})
    log(f"thumbnails: {len(tiles)}/{len(chunks)} tiles, {os.path.getsize(jpg) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
