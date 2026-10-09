"""Recompute derived fields in existing app data files without YOLO or Cosmos calls.

Adds per-camera fleet metrics and AGV series fields (from data_segments.json), worker reaction metrics on
safety events (from stored evidence), drops labor_surplus flags and the recommendation refs to them, and
re-renders the shift report around the existing summary.

Usage: python tools/warehouse-ops/analyzer/refresh_data.py [app_dir]
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

import fusion
import recommend
import utilization
import validate_outputs
from common import APP_DIR, log, read_json, write_json


def main() -> int:
    app_dir = sys.argv[1] if len(sys.argv) > 1 else APP_DIR
    path = {k: os.path.join(app_dir, f"data_{k}.json") for k in ("segments", "events", "utilization", "recommendations")}
    segs, events = read_json(path["segments"]), read_json(path["events"])
    util, recs = read_json(path["utilization"]), read_json(path["recommendations"])

    rows = defaultdict(list)
    for s in segs:
        rows[(s["site_id"], s["camera"])].append(s)
    for cam in util["cameras"]:
        cam_rows = sorted(rows.get((cam["site_id"], cam["camera"]), []), key=lambda s: s["scene_t0"])
        cam["fleet"] = utilization.fleet_summary(cam_rows)
        by_t0 = {s["scene_t0"]: s["machines"]["agv"] for s in cam_rows}
        for p in cam["series"]:
            agv = by_t0.get(p["scene_t0"], {"total": 0, "moving": 0, "loaded": 0})
            p.update(agv_total=agv["total"], agv_moving=agv["moving"], agv_loaded=agv["loaded"])

    dropped = {f["flag_id"] for f in util["flags"] if f["type"] == "labor_surplus"}
    util["flags"] = [f for f in util["flags"] if f["flag_id"] not in dropped]

    for e in events:
        r = fusion.reaction(e)
        if r:
            e["reaction"] = r
        else:
            e.pop("reaction", None)

    kept = []
    for r in recs["recommendations"]:
        r["refs"] = [x for x in r["refs"] if x not in dropped]
        if r["refs"]:
            kept.append(r)
    for i, r in enumerate(kept, 1):
        r["rec_id"] = f"rec_{i:02d}"
    recs["recommendations"] = kept
    m = re.search(r"## Summary\n(.*?)\n\n## ", recs.get("shift_report_md") or "", re.S)
    summary = m.group(1).strip() if m else recommend.template(recommend.compact_payload(util, events))[1]
    recs["shift_report_md"] = recommend.shift_report(recommend.compact_payload(util, events), kept, summary)

    for k, obj in (("utilization", util), ("events", events), ("recommendations", recs)):
        write_json(path[k], obj)
    log(f"refreshed {app_dir}: fleet on {len(util['cameras'])} cameras, "
        f"reaction on {sum(1 for e in events if e.get('reaction'))} events, dropped {len(dropped)} labor flags, "
        f"{len(kept)} recommendations kept")
    errors = validate_outputs.validate(app_dir)
    if errors:
        log(f"CONTRACT VALIDATION FAILED ({len(errors)}): " + "; ".join(errors[:10]))
        return 2
    log("contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
