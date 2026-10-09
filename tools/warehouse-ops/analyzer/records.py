"""Per-segment records (data_segments.json) and the per-camera rows that feed utilization."""
from __future__ import annotations

from collections import defaultdict

from inventory import Segment

PEOPLE_KEYS = ("per_frame_median", "per_frame_max", "tracks", "idle", "moving", "idle_ratio", "mean_speed_mps",
               "per_frame_mean", "classified_share")


def empty_machines() -> dict:
    return {"forklift": {"total": 0, "moving": 0}, "agv": {"total": 0, "moving": 0, "loaded": 0},
            "amr": {"total": 0, "moving": 0}, "humanoid": {"total": 0, "moving": 0}}


def machines_for(seg: Segment, kin: dict, vlm_w017: dict, vlm_w3: dict) -> tuple[dict, str]:
    """VLM machine counts when available, else class-agnostic YOLO hints (weak)."""
    machines, hints = empty_machines(), kin["machine_hints"]
    if seg.is_scenario:
        rec = vlm_w3.get((seg.site_id, seg.camera))
        if rec is None:
            machines["forklift"] = {"total": min(1, hints["tracks"]), "moving": min(1, hints["moving"])}
            return machines, "yolo_hint"
        js = rec["json"]
        halves = (js["vehicle_moving_0_5s"], js["vehicle_moving_5_10s"])
        moving = halves[min(seg.n, 2) - 1] if any(halves) else js["vehicle_moves"]
        visible = js["vehicle_visible"] or js["vehicle_moves"]
        machines["forklift"] = {"total": int(visible), "moving": int(visible and moving)}
        return machines, "vlm"
    rec = vlm_w017.get(seg.seg_id)
    if rec is not None:
        return rec["json"]["machines"], "vlm"
    machines["agv"] = {"total": hints["tracks"], "moving": hints["moving"], "loaded": 0}
    return machines, "yolo_hint"


def congestion_from_yolo(kin: dict) -> str:
    peak = max(max(row) for row in kin["zones"]["occupancy"])
    if peak >= 4:
        return "high"
    if peak >= 3:
        return "medium"
    if peak >= 1.5 or kin["people"]["per_frame_mean"] >= 6:
        return "low"
    return "none"


def build(segs: list[Segment], kin: dict, vlm_w017: dict, vlm_w3: dict, seg_events: dict, annotations: dict
          ) -> tuple[list[dict], dict[tuple, list[dict]], dict[tuple, str]]:
    records, cam_rows, views = [], defaultdict(list), {}
    for seg in segs:
        k = kin[seg.seg_id]
        machines, source = machines_for(seg, k, vlm_w017, vlm_w3)
        w017 = vlm_w017.get(seg.seg_id)
        w3 = vlm_w3.get((seg.site_id, seg.camera))
        congestion_yolo = congestion_from_yolo(k)
        ev = k["events"]
        rec = {
            "seg_id": seg.seg_id, "site_id": seg.site_id, "camera": seg.camera, "chunk_index": seg.chunk_index,
            "n": seg.n, "source": seg.source, "original_video": seg.original_video,
            "scene_t0": seg.scene_t0, "scene_t1": seg.scene_t1,
            "people": {key: k["people"][key] for key in PEOPLE_KEYS},
            "machines": machines,
            "zones": {"cols": k["zones"]["cols"], "rows": k["zones"]["rows"],
                      "occupancy": k["zones"]["occupancy"], "idle": k["zones"]["idle"]},
            "congestion": w017["json"]["congestion"] if w017 else congestion_yolo,
            "vlm_summary": (w017 or w3)["json"]["summary"] if (w017 or w3) else None,
            "pipeline_caption": seg.caption,
            "event_ids": seg_events.get(seg.seg_id, []),
            "view": seg.view,
            "machines_source": source,
            "congestion_yolo": congestion_yolo,
            "kinematics": {"evasive": len(ev["evasive"]), "occlusions": len(ev["occlusions"]),
                           "possible_falls": len(ev["posture"]), "machine_hint_tracks": k["machine_hints"]["tracks"]},
        }
        if w3 is not None:
            js = w3["json"]
            rec["vlm_event"] = {"event": js["event"], "min_separation": js["min_separation"],
                                "closest_approach_sec": js["closest_approach_sec"], "person_fell": js["person_fell"]}
        if seg.seg_id in annotations:
            rec["safety_checks"] = annotations[seg.seg_id]
        records.append(rec)

        cam_rows[(seg.site_id, seg.camera)].append({
            "scene_t0": seg.scene_t0, "scene_t1": seg.scene_t1, "people": k["people"]["per_frame_mean"],
            "idle": k["people"]["idle"], "moving": k["people"]["moving"],
            "machines_total": sum(m["total"] for m in machines.values()),
            "machines_moving": sum(m["moving"] for m in machines.values()),
            "machines": machines, "machines_source": source, "zones": k["zones"],
        })
        views[(seg.site_id, seg.camera)] = seg.view
    return records, cam_rows, views
