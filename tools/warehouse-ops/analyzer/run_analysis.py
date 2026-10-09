"""Offline analyzer: indexed VSS warehouse videos -> compact JSON data files for the Warehouse Ops app.

Usage (from the repo root):
  .venv\\Scripts\\python.exe tools/warehouse-ops/analyzer/run_analysis.py --no-vlm      # fast YOLO-only pass
  .venv\\Scripts\\python.exe tools/warehouse-ops/analyzer/run_analysis.py               # full pass with Cosmos
Options: --sites w017,w3_run10 (update only these sites in the existing files), --concurrency 3, --force.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import fusion
import inventory
import kinematics
import recommend
import records
import utilization
import validate_outputs
from common import APP_DIR, cosmos, log, read_json, write_json
from fetch import Downloader, fetch_sidecars

OUTPUTS = {"videos": "data_videos.json", "segments": "data_segments.json", "events": "data_events.json",
           "utilization": "data_utilization.json", "recommendations": "data_recommendations.json"}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-vlm", action="store_true", help="YOLO-only pass (no Cosmos calls, template recommendations)")
    ap.add_argument("--sites", default="", help="comma-separated site_ids to (re)analyze; others are kept as-is")
    ap.add_argument("--concurrency", type=int, default=3, help="max concurrent Cosmos calls (shared GPU: keep <= 3)")
    ap.add_argument("--force", action="store_true", help="ignore caches (sidecars, media, VLM replies)")
    ap.add_argument("--out", default=APP_DIR, help="output directory for the data files")
    return ap.parse_args()


def analyze_kinematics(segs: list[inventory.Segment], dets: dict) -> tuple[dict, dict]:
    """Per-segment kinematics, plus whole-clip (10 s) kinematics per scenario camera."""
    kin, by_cam = {}, defaultdict(list)
    for s in segs:
        det = dets.get(s.source) or {"frames": [], "video_shape": [1080, 1920]}
        h, w = det.get("video_shape") or [1080, 1920]
        kin[s.seg_id] = kinematics.analyze(det["frames"], w, h)
        if s.is_scenario:
            by_cam[(s.site_id, s.camera)].append(s)
    cam_kin = {}
    for key, cam_segs in by_cam.items():
        cam_dets = [dets.get(s.source) or {"frames": []} for s in sorted(cam_segs, key=lambda s: s.n)]
        h, w = (cam_dets[0].get("video_shape") or [1080, 1920])
        cam_kin[key] = kinematics.analyze(kinematics.concat_frames(cam_dets), w, h)
    return kin, cam_kin


def run_vlm(args, segs: list[inventory.Segment], kin: dict, cam_kin: dict, moments: tuple[list, list]):
    """Returns (runner, w017 descriptions, w3 per-camera labels, w017 moment checks)."""
    import vlm as vlm_mod

    client = cosmos()
    if not client.available:
        log("Cosmos credentials not available; skipping the VLM pass")
        return None, {}, {}, {}
    runner = vlm_mod.VLM(concurrency=args.concurrency, force=args.force)
    log(f"VLM pass with {runner.model}, GPU concurrency {args.concurrency}")
    downloader = Downloader(workers=6, force=args.force)
    try:
        w3_cams = defaultdict(list)
        for s in segs:
            if s.is_scenario:
                w3_cams[(s.site_id, s.camera)].append(s)
        vlm_w3 = vlm_mod.run_w3(runner, downloader, {k: sorted(v, key=lambda s: s.n) for k, v in w3_cams.items()},
                                cam_kin)
        checks = vlm_mod.run_w017_checks(runner, downloader, moments[0] + moments[1]) if moments[0] else {}
        vlm_w017 = vlm_mod.run_w017(runner, downloader, [s for s in segs if not s.is_scenario], kin)
    finally:
        downloader.close()
    log(f"media: {downloader.downloaded} clips downloaded ({downloader.bytes / 1e6:.0f} MB)")
    return runner, vlm_w017, vlm_w3, checks


def merge_by_site(new: list[dict], old_path: str, sites: set[str], key) -> list[dict]:
    old = read_json(old_path) or []
    if isinstance(old, dict):
        old = []
    return sorted([x for x in old if x.get("site_id") not in sites] + new, key=key)


def main() -> int:
    args = parse_args()
    started = time.time()
    selected = {s.strip() for s in args.sites.split(",") if s.strip()} or None
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    segs = inventory.load_segments(selected)
    if not segs:
        log("no segments found (check --sites values and whether ingestion finished)")
        return 1
    log(f"inventory: {len(segs)} segments, {len({(s.site_id, s.camera) for s in segs})} cameras, "
        f"{len({s.site_id for s in segs})} sites")
    dets = fetch_sidecars(segs, force=args.force)
    kin, cam_kin = analyze_kinematics(segs, dets)
    moments = fusion.w017_moments([s for s in segs if not s.is_scenario], kin)
    log(f"kinematics done; {len(moments[0])} w017 candidate moments, {len(moments[1])} control moments")

    runner, vlm_w017, vlm_w3, checks = ((None, {}, {}, {}) if args.no_vlm
                                        else run_vlm(args, segs, kin, cam_kin, moments))

    events, seg_events, annotations, calibration = fusion.build_events(segs, cam_kin, vlm_w3, moments, checks)
    seg_records, cam_rows, views = records.build(segs, kin, vlm_w017, vlm_w3, seg_events, annotations)
    util = utilization.build(cam_rows, views)
    videos = inventory.videos_doc(segs, generated_at)

    out = {name: os.path.join(args.out, fname) for name, fname in OUTPUTS.items()}
    if selected:
        def seg_key(r):
            return inventory.site_sort_key(r["site_id"]), r["camera"], r["chunk_index"], r["n"]
        old_videos = read_json(out["videos"]) or {"sites": []}
        videos["sites"] = sorted([s for s in old_videos["sites"] if s["site_id"] not in selected] + videos["sites"],
                                 key=lambda s: inventory.site_sort_key(s["site_id"]))
        seg_records = merge_by_site(seg_records, out["segments"], selected, seg_key)
        events = merge_by_site(events, out["events"], selected,
                               lambda e: (fusion.SEVERITY_RANK[e["severity"]], -e["confidence"], e["site_id"]))
        old_util = read_json(out["utilization"]) or {"cameras": [], "flags": []}
        util = {"cameras": sorted([c for c in old_util["cameras"] if c["site_id"] not in selected] + util["cameras"],
                                  key=lambda c: (inventory.site_sort_key(c["site_id"]), c["camera"])),
                "flags": [f for f in old_util["flags"] if f["site_id"] not in selected] + util["flags"]}

    recs = recommend.build(util, events, runner, generated_at)
    sizes = {
        "videos": write_json(out["videos"], videos),
        "segments": write_json(out["segments"], seg_records),
        "events": write_json(out["events"], events),
        "utilization": write_json(out["utilization"], util),
        "recommendations": write_json(out["recommendations"], recs),
    }
    print_summary(args, started, segs, events, util, recs, runner, sizes, calibration)
    errors = validate_outputs.validate(args.out)
    if errors:
        log(f"CONTRACT VALIDATION FAILED ({len(errors)}): " + "; ".join(errors[:10]))
        return 2
    log("contract validation passed")
    return 0


def print_summary(args, started, segs, events, util, recs, runner, sizes, calibration) -> None:
    print("\n================ SUMMARY ================")
    print(f"mode: {'YOLO-only' if args.no_vlm else 'YOLO + Cosmos'} | runtime {time.time() - started:.0f} s | "
          f"segments analyzed: {len(segs)}")
    if runner is not None:
        st = runner.stats
        print(f"cosmos: {st['calls']} calls ({st['cached']} cached, {st['failed']} failed), "
              f"{st['gpu_seconds']:.0f} s GPU wall time, model {runner.model}")
    if calibration["candidates_checked"] or calibration["controls_checked"]:
        print(f"w017 checks: Cosmos confirmed {calibration['candidates_confirmed']}/"
              f"{calibration['candidates_checked']} candidate moments vs {calibration['controls_confirmed']}/"
              f"{calibration['controls_checked']} random control moments -> confidence "
              f"{calibration['confidence_if_confirmed']:.2f} per confirmed event")
    print(f"files: {sizes} total {sum(sizes.values()) / 1024:.0f} KB")
    print(f"\nevents ({len(events)}): {dict(Counter(e['type'] for e in events))}")
    for e in events:
        print(f"  [{e['severity']:<6} {e['confidence']:.2f}] {e['type']:<15} {e['site_id']:<9} {e['camera']:<11} "
              f"t={e['scene_t']:6.1f}s  {e['title']}")
    print("\nfleet per floor/lane camera (machines moving / AGV moving / AGV loaded / windows with motion):")
    for c in util["cameras"]:
        if c["view"] in ("floor", "lane"):
            f, agv = c.get("fleet") or {}, (c.get("fleet") or {}).get("types", {}).get("agv", {})
            print(f"  {c['site_id']:<9} {c['camera']:<11} {c['totals']['machine_moving_ratio']:.2f} / "
                  f"{agv.get('moving_ratio', 0):.2f} / {agv.get('loaded_ratio', 0):.2f} / "
                  f"{f.get('active_window_share', 0):.2f}")
    for e in events:
        if e.get("reaction"):
            r = e["reaction"]
            print(f"  reaction {e['site_id']:<9} {r['verdict']}, peak {r['peak_mps']} m/s, onset t={r['onset_t']} s, "
                  f"margin {r['margin_sec']} s ({'reliable' if r['margin_reliable'] else 'VLM spread ' + str(r['closest_spread_sec']) + ' s'})")
    print(f"\nflags ({len(util['flags'])}): {dict(Counter(f['type'] for f in util['flags']))}")
    for f in util["flags"]:
        print(f"  {f['type']:<15} {f['message']}")
    print(f"\nrecommendations ({recs['model']}):")
    for r in recs["recommendations"]:
        print(f"  {r['rec_id']}: {r['title']}  refs={r['refs']}")


if __name__ == "__main__":
    sys.exit(main())
