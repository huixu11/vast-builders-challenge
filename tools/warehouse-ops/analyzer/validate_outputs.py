"""Validate the five app data files against the shared data contract.

Usage: python tools/warehouse-ops/analyzer/validate_outputs.py [app_dir]
Exit code 0 when valid; prints every violation otherwise.
"""
from __future__ import annotations

import json
import os
import sys

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
FILES = ("data_videos.json", "data_segments.json", "data_events.json", "data_utilization.json",
         "data_recommendations.json")
MAX_TOTAL_BYTES = 700 * 1024
NUM = (int, float)
EVENT_TYPES = {"collision", "near_miss", "person_in_path", "robot_proximity", "fall", "blocked_aisle"}
SEVERITIES = ["high", "medium", "low"]
FLAG_TYPES = {"labor_surplus", "machine_surplus", "congestion", "underused_zone", "bottleneck"}
CONGESTION = {"none", "low", "medium", "high"}
VIEWS = {"floor", "lane", "ceiling", "eye"}
MACHINES = {"forklift": ("total", "moving"), "agv": ("total", "moving", "loaded"), "amr": ("total", "moving"),
            "humanoid": ("total", "moving")}


class Checker:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def fail(self, where: str, msg: str) -> None:
        if len(self.errors) < 200:
            self.errors.append(f"{where}: {msg}")

    def keys(self, obj, where: str, spec: dict) -> bool:
        if not isinstance(obj, dict):
            self.fail(where, f"expected object, got {type(obj).__name__}")
            return False
        for key, typ in spec.items():
            if key not in obj:
                self.fail(where, f"missing '{key}'")
            elif typ is not None and (isinstance(obj[key], bool) and typ in (NUM, int) or not isinstance(obj[key], typ)):
                self.fail(where, f"'{key}' has type {type(obj[key]).__name__}")
        return True

    def grid(self, g, where: str, rows: int = 3, cols: int = 4) -> None:
        if not (isinstance(g, list) and len(g) == rows and all(isinstance(r, list) and len(r) == cols for r in g)
                and all(isinstance(v, NUM) for r in g for v in r)):
            self.fail(where, f"expected {rows}x{cols} numeric grid")


def validate(app_dir: str = APP_DIR) -> list[str]:
    c = Checker()
    data, total = {}, 0
    for name in FILES:
        path = os.path.join(app_dir, name)
        if not os.path.exists(path):
            c.fail(name, "missing file")
            continue
        total += os.path.getsize(path)
        with open(path, encoding="utf-8") as f:
            data[name] = json.load(f)
    if c.errors:
        return c.errors
    if total > MAX_TOTAL_BYTES:
        c.fail("all files", f"total size {total} bytes exceeds {MAX_TOTAL_BYTES}")

    videos = data["data_videos.json"]
    sources = set()
    c.keys(videos, "videos", {"generated_at": str, "sites": list})
    for si, site in enumerate(videos.get("sites", [])):
        w = f"videos.sites[{si}]"
        c.keys(site, w, {"site_id": str, "location": str, "title": str, "kind": str, "duration_sec": NUM,
                         "cameras": list})
        if site.get("kind") not in ("continuous", "scenario"):
            c.fail(w, f"bad kind {site.get('kind')}")
        for cam in site.get("cameras", []):
            cw = f"{w}.{cam.get('camera')}"
            c.keys(cam, cw, {"camera": str, "view": str, "chunks": list})
            if cam.get("view") not in VIEWS:
                c.fail(cw, f"bad view {cam.get('view')}")
            for ch in cam.get("chunks", []):
                c.keys(ch, cw, {"chunk_index": int, "original_video": str, "filename": str, "scene_t0": NUM,
                                "scene_t1": NUM, "segments": list})
                for seg in ch.get("segments", []):
                    c.keys(seg, cw, {"n": int, "source": str, "scene_t0": NUM, "scene_t1": NUM})
                    sources.add(seg.get("source"))

    events = data["data_events.json"]
    event_ids = set()
    if not isinstance(events, list):
        c.fail("events", "expected list")
        events = []
    for i, e in enumerate(events):
        w = f"events[{i}]"
        c.keys(e, w, {"event_id": str, "type": str, "severity": str, "confidence": NUM, "site_id": str, "camera": str,
                      "source": str, "original_video": str, "t_in_segment": NUM, "scene_t": NUM, "title": str,
                      "description": str, "evidence": dict, "views": list})
        event_ids.add(e.get("event_id"))
        if e.get("type") not in EVENT_TYPES:
            c.fail(w, f"bad type {e.get('type')}")
        if e.get("severity") not in SEVERITIES:
            c.fail(w, f"bad severity {e.get('severity')}")
        if not 0 <= e.get("confidence", -1) <= 1:
            c.fail(w, "confidence outside 0..1")
        if e.get("source") not in sources:
            c.fail(w, "source not in data_videos")
        c.keys(e.get("evidence", {}), f"{w}.evidence", {"vlm": None, "kinematics": None, "consensus": None,
                                                         "pipeline_caption_said": None})
        for v in e.get("views", []):
            c.keys(v, f"{w}.views", {"camera": str, "source": str, "t_in_segment": NUM, "label": str,
                                     "confidence": NUM})
            if v.get("source") not in sources:
                c.fail(f"{w}.views", "source not in data_videos")
    order = [(SEVERITIES.index(e.get("severity", "low")) if e.get("severity") in SEVERITIES else 9,
              -e.get("confidence", 0)) for e in events]
    if order != sorted(order):
        c.fail("events", "not sorted by severity then confidence")
    if len(event_ids) != len(events):
        c.fail("events", "duplicate event_id")

    segments = data["data_segments.json"]
    seg_sources = set()
    if not isinstance(segments, list):
        c.fail("segments", "expected list")
        segments = []
    for i, s in enumerate(segments):
        w = f"segments[{i}]"
        c.keys(s, w, {"seg_id": str, "site_id": str, "camera": str, "chunk_index": int, "n": int, "source": str,
                      "original_video": str, "scene_t0": NUM, "scene_t1": NUM, "people": dict, "machines": dict,
                      "zones": dict, "congestion": str, "vlm_summary": (str, type(None)), "pipeline_caption": str,
                      "event_ids": list})
        expected = f"{s.get('site_id')}|{s.get('camera')}|{s.get('chunk_index')}|{s.get('n')}"
        if s.get("seg_id") != expected:
            c.fail(w, f"seg_id {s.get('seg_id')} != {expected}")
        seg_sources.add(s.get("source"))
        c.keys(s.get("people", {}), f"{w}.people", {k: NUM for k in ("per_frame_median", "per_frame_max", "tracks",
                                                                     "idle", "moving", "idle_ratio",
                                                                     "mean_speed_mps")})
        for mtype, fields in MACHINES.items():
            c.keys(s.get("machines", {}).get(mtype), f"{w}.machines.{mtype}", {k: int for k in fields})
        z = s.get("zones", {})
        if z.get("cols") != 4 or z.get("rows") != 3:
            c.fail(f"{w}.zones", "cols/rows must be 4/3")
        c.grid(z.get("occupancy"), f"{w}.zones.occupancy")
        c.grid(z.get("idle"), f"{w}.zones.idle")
        if s.get("congestion") not in CONGESTION:
            c.fail(w, f"bad congestion {s.get('congestion')}")
        for eid in s.get("event_ids", []):
            if eid not in event_ids:
                c.fail(w, f"unknown event_id {eid}")
    if seg_sources != sources:
        c.fail("segments", f"segment sources differ from data_videos ({len(seg_sources)} vs {len(sources)})")

    util = data["data_utilization.json"]
    flag_ids = set()
    c.keys(util, "utilization", {"cameras": list, "flags": list})
    for cam in util.get("cameras", []):
        w = f"utilization.{cam.get('site_id')}|{cam.get('camera')}"
        c.keys(cam, w, {"site_id": str, "camera": str, "view": str, "series": list, "totals": dict, "heatmap": dict})
        for row in cam.get("series", []):
            c.keys(row, f"{w}.series", {k: NUM for k in ("scene_t0", "scene_t1", "people", "idle", "moving",
                                                         "machines_total", "machines_moving")})
        c.keys(cam.get("totals", {}), f"{w}.totals", {k: NUM for k in ("people_avg", "idle_ratio",
                                                                       "machine_moving_ratio", "person_seconds",
                                                                       "idle_person_seconds")})
        hm = cam.get("heatmap", {})
        c.keys(hm, f"{w}.heatmap", {"cols": int, "rows": int, "occupancy": list, "idle": list})
        c.grid(hm.get("occupancy"), f"{w}.heatmap.occupancy")
        c.grid(hm.get("idle"), f"{w}.heatmap.idle")
    for f in util.get("flags", []):
        w = f"flags.{f.get('flag_id')}"
        c.keys(f, w, {"flag_id": str, "type": str, "site_id": str, "camera": str, "zone": (list, type(None)),
                      "scene_t0": NUM, "scene_t1": NUM, "metric": dict, "message": str})
        flag_ids.add(f.get("flag_id"))
        if f.get("type") not in FLAG_TYPES:
            c.fail(w, f"bad type {f.get('type')}")
        zone = f.get("zone")
        if zone is not None and not (len(zone) == 2 and 0 <= zone[0] < 4 and 0 <= zone[1] < 3):
            c.fail(w, f"bad zone {zone}")
        c.keys(f.get("metric", {}), f"{w}.metric", {"name": str, "value": NUM, "threshold": NUM})
    if len(flag_ids) != len(util.get("flags", [])):
        c.fail("flags", "duplicate flag_id")

    recs = data["data_recommendations.json"]
    c.keys(recs, "recommendations", {"generated_at": str, "model": str, "recommendations": list,
                                     "shift_report_md": str})
    for r in recs.get("recommendations", []):
        w = f"recommendations.{r.get('rec_id')}"
        c.keys(r, w, {"rec_id": str, "title": str, "action": str, "rationale": str, "expected_impact": str,
                      "refs": list})
        for ref in r.get("refs", []):
            if ref not in flag_ids | event_ids:
                c.fail(w, f"unknown ref {ref}")
    if not recs.get("shift_report_md", "").strip():
        c.fail("recommendations", "empty shift_report_md")
    return c.errors


def main() -> int:
    app_dir = sys.argv[1] if len(sys.argv) > 1 else APP_DIR
    errors = validate(app_dir)
    sizes = {n: os.path.getsize(os.path.join(app_dir, n)) for n in FILES if os.path.exists(os.path.join(app_dir, n))}
    print("sizes (bytes):", sizes, "total:", sum(sizes.values()))
    if errors:
        print(f"INVALID: {len(errors)} problem(s)")
        for e in errors:
            print("  -", e)
        return 1
    print("VALID: all five files match the data contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
