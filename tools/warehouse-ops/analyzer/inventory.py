"""Inventory: explore both VSS locations and normalize chunk names into sites/cameras/chunks/segments."""
from __future__ import annotations

import re
from dataclasses import dataclass

from common import cache_path, log, read_json, vss, write_json

LOCATIONS = ("indoor", "warehouse3")
CAPTION_CHARS = 300

_W017 = re.compile(r"_Warehouse_(\d+)_(Camera(?:_\d+)?)_chunk_(\d+)\.mp4$")
_W3 = re.compile(r"_run_(\d+)_seed_\d+\.(ceiling|eye)_(\d+)\.rgb_chunk_(\d+)\.mp4$")
_UPLOAD = re.compile(r"^\d{8}_(\d{6})_[0-9a-f]+_chunk_(\d+)\.mp4$")
_CAMERA_ID = re.compile(r"^(ceiling|eye)_\d+$")
LANE_CAMERAS = {("w017", "Camera_01")}


@dataclass(frozen=True)
class Segment:
    site_id: str
    location: str
    camera: str
    view: str
    chunk_index: int
    n: int
    source: str
    original_video: str
    filename: str
    scene_t0: float
    scene_t1: float
    caption: str

    @property
    def seg_id(self) -> str:
        return f"{self.site_id}|{self.camera}|{self.chunk_index}|{self.n}"

    @property
    def duration(self) -> float:
        return self.scene_t1 - self.scene_t0

    @property
    def is_scenario(self) -> bool:
        return self.location == "warehouse3"


def parse_name(location: str, filename: str, camera_id: str = "") -> dict | None:
    if location == "indoor":
        m = _W017.search(filename)
        if m:
            site, cam = f"w{m.group(1)}", m.group(2)
            return {"site_id": site, "camera": cam, "chunk_index": int(m.group(3)),
                    "view": "lane" if (site, cam) in LANE_CAMERAS else "floor"}
    elif location == "warehouse3":
        m = _W3.search(filename)
        if m:
            return {"site_id": f"w3_run{m.group(1)}", "camera": f"{m.group(2)}_{m.group(3)}",
                    "chunk_index": int(m.group(4)), "view": m.group(2)}
        m, cam = _UPLOAD.match(filename), _CAMERA_ID.match(camera_id or "")
        if m and cam:  # /videos/upload renames the file, so the camera comes from the upload metadata
            return {"site_id": f"w3_live{m.group(1)}", "camera": cam.group(0), "chunk_index": int(m.group(2)),
                    "view": cam.group(1)}
    return None


def site_sort_key(site_id: str) -> tuple:
    m = re.match(r"w3_(run|live)(\d+)$", site_id)
    return (1 if m.group(1) == "run" else 2, int(m.group(2)), "") if m else (0, 0, site_id)


def site_meta(site_id: str) -> dict:
    m = re.match(r"w3_run(\d+)$", site_id)
    if m:
        return {"title": f"Forklift safety scenario, run {m.group(1)}", "kind": "scenario"}
    m = re.match(r"w3_live(\d\d)(\d\d)(\d\d)$", site_id)
    if m:
        return {"title": f"Live camera upload, {m.group(1)}:{m.group(2)}:{m.group(3)} UTC", "kind": "scenario"}
    return {"title": f"Warehouse {site_id[1:]} robot-assisted floor", "kind": "continuous"}


def explore(location: str) -> list[dict]:
    """Always refresh (cheap); fall back to the cached copy if the API is unreachable."""
    path = cache_path("explore", f"{location}.json")
    try:
        items = vss().explore_all(location)
        write_json(path, items)
    except Exception as e:  # noqa: BLE001
        items = read_json(path)
        if items is None:
            raise
        log(f"explore({location}) failed ({type(e).__name__}); using cached inventory")
    return items


def load_segments(sites: set[str] | None = None) -> list[Segment]:
    segs: dict[str, Segment] = {}
    for location in LOCATIONS:
        for ch in explore(location):
            meta = parse_name(location, ch.get("filename", ""), ch.get("camera_id") or "")
            if meta is None:
                log(f"skipping unrecognized chunk name: {ch.get('filename')}")
                continue
            if sites and meta["site_id"] not in sites:
                continue
            base = meta["chunk_index"] * float(ch.get("chunk_duration_sec") or 0.0)
            for tl in ch.get("timeline") or []:
                seg = Segment(
                    site_id=meta["site_id"], location=location, camera=meta["camera"], view=meta["view"],
                    chunk_index=meta["chunk_index"], n=int(tl["segment_number"]), source=tl["source"],
                    original_video=ch["original_video"], filename=ch["filename"],
                    scene_t0=round(base + float(tl["segment_start_sec"]), 3),
                    scene_t1=round(base + float(tl["segment_end_sec"]), 3),
                    caption=(tl.get("reasoning_content") or "")[:CAPTION_CHARS],
                )
                if seg.seg_id in segs:
                    log(f"duplicate segment {seg.seg_id}; keeping the first one")
                    continue
                segs[seg.seg_id] = seg
    return sorted(segs.values(), key=lambda s: (site_sort_key(s.site_id), s.camera, s.chunk_index, s.n))


def videos_doc(segments: list[Segment], generated_at: str) -> dict:
    sites: dict[str, dict] = {}
    for s in segments:
        site = sites.setdefault(s.site_id, {"site_id": s.site_id, "location": s.location, **site_meta(s.site_id),
                                            "duration_sec": 0.0, "cameras": {}})
        cam = site["cameras"].setdefault(s.camera, {"camera": s.camera, "view": s.view, "chunks": {}})
        chunk = cam["chunks"].setdefault(s.chunk_index, {
            "chunk_index": s.chunk_index, "original_video": s.original_video, "filename": s.filename,
            "scene_t0": s.scene_t0, "scene_t1": s.scene_t1, "segments": []})
        chunk["scene_t0"] = min(chunk["scene_t0"], s.scene_t0)
        chunk["scene_t1"] = max(chunk["scene_t1"], s.scene_t1)
        chunk["segments"].append({"n": s.n, "source": s.source, "scene_t0": s.scene_t0, "scene_t1": s.scene_t1})
        site["duration_sec"] = max(site["duration_sec"], s.scene_t1)
    out = []
    for site in sites.values():
        cameras = []
        for cam in site["cameras"].values():
            cam["chunks"] = sorted(cam["chunks"].values(), key=lambda c: c["chunk_index"])
            cameras.append(cam)
        site["cameras"] = cameras
        out.append(site)
    return {"generated_at": generated_at, "sites": out}
