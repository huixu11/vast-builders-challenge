"""Event fusion: Cosmos labels + YOLO kinematics -> deduplicated, explainable safety events.

warehouse3: one event per run from the majority of ceiling views (eye views only break ties);
confidence = view agreement x kinematic support.
w017: YOLO proposes candidate moments (a person starts moving suddenly while a moving machine-like object is
close, at the same place and time) and Cosmos answers a targeted question about each one. The same question
on random control moments measures how often Cosmos says "yes" anyway; that false-positive rate sets the
confidence of confirmed events.
"""
from __future__ import annotations

import random
import statistics
from collections import Counter, defaultdict

from inventory import Segment
from prompts import POSITIONS

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
CLOSE_SEPARATIONS = ("contact", "<1m")
TIE_ORDER = ("near_miss", "person_in_path", "collision", "none")
COMPATIBLE = {"near_miss": ("near_miss", "collision"), "collision": ("collision",),
              "person_in_path": ("person_in_path",)}
MAX_CONFIDENCE = 0.95
DEDUPE_SEC = 3.0
MACHINE_NAMES = {"agv": "AGV", "amr": "AMR", "humanoid": "humanoid robot", "forklift": "forklift"}

JOINT_DIST_M = 1.5          # candidate: moving machine-like object this close to the person who starts suddenly
JOINT_DT_SEC = 1.0
JOINT_DX = 0.15             # same person: foot-point x within 15% of the image width
CHECK_HALF_WINDOW_SEC = 1.5
MIN_CONTROLS = 12
CHECK_YES = ("avoids_machine", "machine_close")
CANDIDATE_PRIOR = 0.5       # assumed share of candidates that are real close approaches
ASSUMED_HIT_RATE = 0.8      # assumed share of real close approaches that Cosmos confirms
MOTION_ONLY_CONF = 0.3
REGION_COLS = {"left": (0, 1), "center": (1, 2), "right": (2, 3)}


class SegIndex:
    def __init__(self, segs: list[Segment]) -> None:
        self._by_cam: dict[tuple, list[Segment]] = defaultdict(list)
        for s in segs:
            self._by_cam[(s.site_id, s.camera)].append(s)
        self.by_source = {s.source: s for s in segs}

    def locate(self, site_id: str, camera: str, scene_t: float) -> tuple[Segment, float]:
        segs = self._by_cam[(site_id, camera)]
        for s in segs:
            if s.scene_t0 <= scene_t < s.scene_t1:
                return s, round(scene_t - s.scene_t0, 2)
        s = segs[-1] if scene_t >= segs[-1].scene_t1 else segs[0]
        return s, round(min(max(scene_t - s.scene_t0, 0.0), s.duration), 2)


def _median(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def _first_cue_time(kin: dict) -> float | None:
    """Reaction onset: end of the standstill before an evasive move, or the moment the worker got hidden."""
    ev = kin["events"]
    times = [e["onset_t"] for e in ev["evasive"][:1]] + [g["t_lost"] for g in ev["occlusions"][:1]]
    return min(times) if times else None


def _last_cue_time(kin: dict) -> float | None:
    ev = kin["events"]
    times = [e["t"] + 1.0 for e in ev["evasive"][:1]] + [g["t_found"] for g in ev["occlusions"][:1]]
    return max(times) if times else None


def _kin_story(kin: dict) -> str:
    ev, parts = kin["events"], []
    if ev["evasive"]:
        e = ev["evasive"][0]
        parts.append(f"worker stood still {e['standstill_sec']:.1f} s, then moved suddenly at t={e['t']:.1f} s "
                     f"(peak {e['peak_mps']:.1f} m/s)")
    if ev["occlusions"]:
        g = ev["occlusions"][0]
        parts.append(f"worker hidden from view t={g['t_lost']:.1f}-{g['t_found']:.1f} s")
    if ev["posture"]:
        p = ev["posture"][0]
        parts.append(f"wide person box (possible fall) t={p['t0']:.1f}-{p['t1']:.1f} s")
    elif (kin.get("main_track") or {}).get("ruler_px"):
        parts.append("person box upright throughout")
    return "; ".join(parts) or "no notable person motion"


def _view_cues(kin: dict) -> list[str]:
    ev = kin["events"]
    return [name for name, items in (("evasive", ev["evasive"]), ("occlusion", ev["occlusions"])) if items]


# ----------------------------------------------------------------------------------------------- warehouse3
def _majority(ceil_votes: Counter, eye_votes: Counter) -> str:
    top = max(ceil_votes.values())
    tied = [lab for lab, n in ceil_votes.items() if n == top]
    if len(tied) > 1:
        best_eye = max(eye_votes.get(lab, 0) for lab in tied)
        tied = [lab for lab in tied if eye_votes.get(lab, 0) == best_eye]
    return min(tied, key=TIE_ORDER.index)


def _w3_title(label: str, severity: str) -> str:
    if label == "near_miss":
        return ("Near miss: pallet stacker within 1 m of worker" if severity == "high"
                else "Near miss: pallet stacker passes close to worker")
    return {"collision": "Collision: pallet stacker contacts worker",
            "person_in_path": "Worker in the path of a moving pallet stacker",
            "fall": "Possible worker fall"}[label]


def _w3_views(site_id: str, cams: list[str], ceiling: list[str], cam_kin: dict, vlm: dict, scene_t: float,
              index: SegIndex) -> list[dict]:
    """Cameras are synchronized, so every view points at the same scene time; vlm_t keeps each view's estimate."""
    views = []
    for c in cams:
        rec = vlm.get(c)
        seg, t_in = index.locate(site_id, c, scene_t)
        if rec is None:
            views.append({"camera": c, "source": seg.source, "t_in_segment": t_in, "label": "unavailable",
                          "confidence": 0.0, "vlm_t": None})
            continue
        own = min(2, len(_view_cues(cam_kin[c])))
        conf = 0.5 + 0.25 * own if rec["event"] != "none" else max(0.1, 0.5 - 0.2 * own)
        views.append({"camera": c, "source": seg.source, "t_in_segment": t_in, "label": rec["event"],
                      "confidence": round(conf * (1.0 if c in ceiling else 0.5), 2),
                      "vlm_t": rec["closest_approach_sec"]})
    return views


def _scene_timing(ceiling: list[str], cam_kin: dict, t_vlm: float | None) -> tuple[float, list[float]]:
    """Event time = median reaction onset over ceiling views (precise, needs >= 2 views), else the VLM estimate."""
    onsets = [t for t in (_first_cue_time(cam_kin[c]) for c in ceiling) if t is not None]
    ends = [t for t in (_last_cue_time(cam_kin[c]) for c in ceiling) if t is not None]
    scene_t = _median(onsets) if len(onsets) >= 2 else (t_vlm if t_vlm is not None else 5.0)
    end = max(_median(ends) or 0.0, (t_vlm or 0.0), scene_t + 2.0)
    return scene_t, [round(max(0.0, scene_t - 1.0), 2), round(min(10.0, end), 2)]


def w3_events(site_id: str, cams: dict[str, list[Segment]], cam_kin: dict, vlm: dict, index: SegIndex) -> list[dict]:
    ceiling = sorted(c for c in cams if c.startswith("ceiling"))
    eye = sorted(c for c in cams if c.startswith("eye"))
    labels = {c: vlm[c]["event"] for c in cams if c in vlm}
    ceil_votes = Counter(labels[c] for c in ceiling if c in labels)
    eye_votes = Counter(labels[c] for c in eye if c in labels)
    if not ceil_votes:
        return _w3_kinematic_only(site_id, ceiling, eye, cam_kin, index, reason="no VLM result for ceiling views")
    label = _majority(ceil_votes, eye_votes)
    n_ceiling = sum(ceil_votes.values())
    evasive_views = [c for c in ceiling if cam_kin[c]["events"]["evasive"]]
    occl_views = [c for c in ceiling if cam_kin[c]["events"]["occlusions"]]
    posture_views = [c for c in ceiling if cam_kin[c]["events"]["posture"]]
    fall_claims = sorted(c for c in labels if vlm[c]["person_fell"])
    fall_supported = bool(fall_claims and posture_views)

    downgraded = None
    if label == "collision":
        contact = [c for c in ceiling if labels.get(c) == "collision" and vlm[c]["min_separation"] == "contact"]
        if not (ceil_votes["collision"] / n_ceiling >= 0.6 and contact and (occl_views or posture_views)):
            label, downgraded = "near_miss", "collision"
    if label == "none":
        return _w3_kinematic_only(site_id, ceiling, eye, cam_kin, index,
                                  reason=f"VLM ceiling majority saw no interaction ({dict(ceil_votes)})")

    agreeing = [c for c in ceiling if labels.get(c) in COMPATIBLE[label]]
    agreement = len(agreeing) / n_ceiling
    close_views = [c for c in agreeing if vlm[c]["min_separation"] in CLOSE_SEPARATIONS]
    walking_views = [c for c in ceiling if max((v or 0.0) for v in cam_kin[c]["speed_timeline"]) >= 0.5]
    n = len(ceiling)
    cue_options = {
        "near_miss": [(evasive_views, f"sudden evasive movement in {len(evasive_views)}/{n} ceiling views"),
                      (occl_views, f"worker hidden behind an object in {len(occl_views)}/{n} ceiling views"),
                      (close_views, f"{len(close_views)}/{len(agreeing)} agreeing views estimate < 1 m separation")],
        "person_in_path": [(walking_views, f"worker walking (>= 0.5 m/s) in {len(walking_views)}/{n} ceiling views"),
                           (evasive_views, f"sudden movement from standstill in {len(evasive_views)}/{n} ceiling views")],
        "collision": [(occl_views, f"worker hidden behind the vehicle in {len(occl_views)}/{n} ceiling views"),
                      (posture_views, f"wide person box in {len(posture_views)}/{n} ceiling views"),
                      (close_views, f"{len(close_views)}/{len(agreeing)} agreeing views report contact")],
    }[label]
    cues = [text for views, text in cue_options if views]
    support = round(0.6 + 0.2 * min(2, len(cues)), 2)
    if label == "collision":
        severity = "high"
    elif label == "near_miss":
        severity = "high" if (2 * len(close_views) >= len(agreeing) or occl_views) else "medium"
    else:
        severity = "medium"

    t_vlm = _median([vlm[c]["closest_approach_sec"] for c in agreeing])
    scene_t, window = _scene_timing(ceiling, cam_kin, t_vlm)

    def rank(c: str) -> tuple:
        t_c = _first_cue_time(cam_kin[c])
        return len(_view_cues(cam_kin[c])), -abs((scene_t if t_c is None else t_c) - scene_t)

    primary = max(agreeing, key=rank)
    seg, t_in = index.locate(site_id, primary, scene_t)
    p_vlm = vlm[primary]
    story = _kin_story(cam_kin[primary])
    consensus = {"method": "ceiling_majority", "ceiling_votes": dict(ceil_votes), "eye_votes": dict(eye_votes),
                 "agreement": round(agreement, 2), "kinematic_support": support, "cues": cues,
                 "downgraded_from": downgraded, "fall_claims": fall_claims, "fall_supported": fall_supported,
                 "t_vlm": t_vlm, "t_onset": scene_t}
    kinematics = {"primary_story": story, "speed_timeline": cam_kin[primary]["speed_timeline"],
                  "per_view": [{"camera": c, **cs} for c in ceiling + eye if (cs := _cue_summary(cam_kin[c]))]}
    events = [{
        "type": label, "severity": severity, "confidence": round(min(MAX_CONFIDENCE, agreement * support), 2),
        "site_id": site_id, "camera": primary, "source": seg.source, "original_video": seg.original_video,
        "t_in_segment": t_in, "scene_t": scene_t, "title": _w3_title(label, severity),
        "description": f"{p_vlm['summary']} {len(agreeing)}/{n_ceiling} ceiling views agree. Motion data: {story}.",
        "scene_window": window,
        "evidence": {
            "vlm": {"primary_view": primary, "summary": p_vlm["summary"], "evidence": p_vlm["evidence"],
                    "vehicle_motion": p_vlm["vehicle_motion"], "person_motion": p_vlm["person_motion"],
                    "min_separation": p_vlm["min_separation"], "closest_approach_sec": p_vlm["closest_approach_sec"],
                    "label_counts": dict(Counter(labels.values()))},
            "kinematics": kinematics, "consensus": consensus, "pipeline_caption_said": seg.caption,
        },
        "views": _w3_views(site_id, ceiling + eye, ceiling, cam_kin, vlm, scene_t, index),
    }]
    if fall_supported:
        p = cam_kin[posture_views[0]]["events"]["posture"][0]
        fseg, ft_in = index.locate(site_id, posture_views[0], p["t0"])
        fall_views = [v for v in _w3_views(site_id, ceiling + eye, ceiling, cam_kin, vlm, p["t0"], index)
                      if v["camera"] in fall_claims]
        events.append({
            "type": "fall", "severity": "high",
            "confidence": round(min(MAX_CONFIDENCE, len([c for c in fall_claims if c in ceiling]) / n_ceiling), 2),
            "site_id": site_id, "camera": posture_views[0], "source": fseg.source,
            "original_video": fseg.original_video, "t_in_segment": ft_in, "scene_t": p["t0"],
            "title": _w3_title("fall", "high"),
            "description": f"VLM reports the worker on the floor in {len(fall_claims)} views; person box wider than "
                           f"tall t={p['t0']:.1f}-{p['t1']:.1f} s.",
            "scene_window": [p["t0"], p["t1"]],
            "evidence": {"vlm": {"fall_claims": fall_claims}, "kinematics": {"posture": p},
                         "consensus": {"method": "vlm_claim+yolo_posture"}, "pipeline_caption_said": fseg.caption},
            "views": [{**v, "label": "fall"} for v in fall_views],
        })
    return events


def _cue_summary(kin: dict) -> dict:
    ev, out = kin["events"], {}
    if ev["evasive"]:
        out["evasive_t"], out["peak_mps"] = ev["evasive"][0]["t"], ev["evasive"][0]["peak_mps"]
    if ev["occlusions"]:
        out["hidden"] = [ev["occlusions"][0]["t_lost"], ev["occlusions"][0]["t_found"]]
    if ev["posture"]:
        out["wide_box"] = [ev["posture"][0]["t0"], ev["posture"][0]["t1"]]
    return out


def _w3_kinematic_only(site_id: str, ceiling: list[str], eye: list[str], cam_kin: dict, index: SegIndex,
                       reason: str) -> list[dict]:
    """Fallback when the VLM is unavailable or saw nothing: motion cues in >= 2 ceiling views."""
    cue_views = [c for c in ceiling if _view_cues(cam_kin[c])]
    if len(cue_views) < 2:
        return []
    occl = [c for c in cue_views if cam_kin[c]["events"]["occlusions"]]
    primary = (occl or cue_views)[0]
    scene_t, window = _scene_timing(ceiling, cam_kin, None)
    seg, t_in = index.locate(site_id, primary, scene_t)
    story = _kin_story(cam_kin[primary])
    views = []
    for c in ceiling + eye:
        cued = bool(_view_cues(cam_kin[c]))
        vseg, vt = index.locate(site_id, c, scene_t)
        views.append({"camera": c, "source": vseg.source, "t_in_segment": vt, "label": "near_miss" if cued else "none",
                      "confidence": round((0.4 if cued else 0.2) * (1.0 if c in ceiling else 0.5), 2)})
    return [{
        "type": "near_miss", "severity": "medium", "confidence": round(min(0.5, 0.1 * len(cue_views)), 2),
        "site_id": site_id, "camera": primary, "source": seg.source, "original_video": seg.original_video,
        "t_in_segment": t_in, "scene_t": scene_t, "title": "Possible near miss (motion cues only)",
        "description": f"Worker motion suggests an evasive reaction in {len(cue_views)}/{len(ceiling)} ceiling views: "
                       f"{story}.",
        "scene_window": window,
        "evidence": {"vlm": None,
                     "kinematics": {"primary_story": story,
                                    "per_view": [{"camera": c, **_cue_summary(cam_kin[c])} for c in cue_views]},
                     "consensus": {"method": "kinematics_only", "reason": reason,
                                   "cue_views": len(cue_views), "ceiling_views": len(ceiling)},
                     "pipeline_caption_said": seg.caption},
        "views": views,
    }]


# ----------------------------------------------------------------------------------------------------- w017
def _region(x: float) -> str:
    return POSITIONS[min(2, int(x * 3))]


def _moment(seg: Segment, t: float, region: str, role: str, **extra) -> dict:
    window = [round(max(0.0, t - CHECK_HALF_WINDOW_SEC), 1), round(min(seg.duration, t + CHECK_HALF_WINDOW_SEC), 1)]
    return {"key": f"{seg.seg_id}@{t:.1f}@{region}", "seg": seg, "t": round(t, 2), "window": window,
            "region": region, "role": role, **extra}


def w017_moments(segs: list[Segment], kin: dict, seed: int = 17) -> tuple[list[dict], list[dict]]:
    """(candidates, controls) to put to Cosmos; deterministic for the same inputs."""
    cands = []
    for seg in segs:
        k, best = kin[seg.seg_id], None
        for e in k["events"]["evasive"]:
            near = [p for p in k["machine_hints"]["proximity"] if abs(p["t"] - e["t"]) <= JOINT_DT_SEC
                    and abs(p["x"] - e["x"]) <= JOINT_DX and p["d_m"] < JOINT_DIST_M]
            if near:
                p = min(near, key=lambda p: p["d_m"])
                if best is None or p["d_m"] < best[1]["d_m"]:
                    best = (e, p)
        if best:
            e, p = best
            cands.append(_moment(seg, e["t"], _region(e["x"]), "candidate", d_m=p["d_m"], peak_mps=e["peak_mps"],
                                 standstill_sec=e["standstill_sec"], object_label=p["label"]))

    rng = random.Random(seed)
    taken = {m["seg"].seg_id for m in cands}
    pool = [s for s in segs if s.seg_id not in taken and kin[s.seg_id]["people"]["per_frame_mean"] >= 1.0]
    controls = []
    for seg in rng.sample(pool, min(len(pool), max(MIN_CONTROLS, len(cands)))):
        occ = kin[seg.seg_id]["zones"]["occupancy"]
        regions = [r for r, cols in REGION_COLS.items() if sum(row[c] for row in occ for c in cols) >= 0.5]
        controls.append(_moment(seg, round(rng.uniform(1.0, 4.0), 1), rng.choice(regions or list(POSITIONS)),
                                "control"))
    return cands, controls


def _posterior(control_yes: int, n_control: int) -> float:
    """P(real | Cosmos confirms a candidate), with the smoothed control yes-rate as Cosmos' false-positive rate."""
    false_positive_rate = (control_yes + 1) / (n_control + 2)
    odds = CANDIDATE_PRIOR / (1 - CANDIDATE_PRIOR) * ASSUMED_HIT_RATE / false_positive_rate
    return min(MAX_CONFIDENCE, odds / (1 + odds))


def _article(name: str) -> str:
    return "an" if name[0].lower() in "aeiou" else "a"


def _w017_event(m: dict, chk: dict | None, confidence: float, calibration: dict) -> dict:
    seg = m["seg"]
    motion = (f"a person who had stood still {m['standstill_sec']:.1f} s moved off at {m['peak_mps']:.1f} m/s "
              f"at t={m['t']:.1f} s while a moving machine-like object was {m['d_m']:.1f} m away")
    if chk is None:
        typ, severity, title = "near_miss", "low", "Possible near miss (motion cues only)"
        description = f"Motion data: {motion}. Not checked by Cosmos."
    else:
        name = MACHINE_NAMES.get(chk["machine"] or "", "machine")
        typ = "robot_proximity" if chk["machine"] in ("humanoid", "amr") else "near_miss"
        if chk["label"] == "avoids_machine":
            severity, what = "medium", f"person steps out of the way of {_article(name)} {name}"
        else:
            severity, what = "low", f"{name} passes within 1 m of a person"
        title = f"Near miss: {what}" if typ == "near_miss" else what[0].upper() + what[1:]
        description = f"{chk['description']} Motion data: {motion}."
    return {
        "type": typ, "severity": severity, "confidence": round(confidence, 2),
        "site_id": seg.site_id, "camera": seg.camera, "source": seg.source, "original_video": seg.original_video,
        "t_in_segment": m["t"], "scene_t": round(seg.scene_t0 + m["t"], 2), "title": title,
        "description": description,
        "scene_window": [round(seg.scene_t0 + m["window"][0], 2), round(seg.scene_t0 + m["window"][1], 2)],
        "evidence": {
            "vlm": None if chk is None else {**chk, "region": m["region"], "window_in_segment": m["window"]},
            "kinematics": {"cues": [motion], "separation_m": m["d_m"], "peak_mps": m["peak_mps"],
                           "standstill_sec": m["standstill_sec"], "object_yolo_label": m["object_label"]},
            "consensus": {"method": "kinematics_only" if chk is None else "kinematics_proposed+vlm_checked",
                          **calibration},
            "pipeline_caption_said": seg.caption,
        },
        "views": [{"camera": seg.camera, "source": seg.source, "t_in_segment": m["t"], "label": typ,
                   "confidence": round(confidence, 2)}],
    }


def w017_events(cands: list[dict], controls: list[dict], checks: dict[str, dict]
                ) -> tuple[list[dict], dict[str, list[dict]], dict]:
    """Returns (events, seg_id -> Cosmos check annotations, calibration summary)."""
    def answered(moments: list[dict]) -> tuple[int, int]:
        replies = [checks[m["key"]] for m in moments if m["key"] in checks]
        return len(replies), sum(r["label"] in CHECK_YES for r in replies)

    n_ctrl, ctrl_yes = answered(controls)
    n_cand, cand_yes = answered(cands)
    posterior = _posterior(ctrl_yes, n_ctrl)
    calibration = {"candidates": len(cands), "candidates_checked": n_cand, "candidates_confirmed": cand_yes,
                   "controls_checked": n_ctrl, "controls_confirmed": ctrl_yes,
                   "confidence_if_confirmed": round(posterior, 2)}

    annotations: dict[str, list[dict]] = defaultdict(list)
    for m in cands + controls:
        chk = checks.get(m["key"])
        annotations[m["seg"].seg_id].append({"role": m["role"], "t": m["t"], "region": m["region"],
                                             "answer": chk and chk["label"], "machine": chk and chk["machine"],
                                             "description": chk and chk["description"]})
    events = []
    for m in cands:
        chk = checks.get(m["key"])
        if chk is None:
            events.append(_w017_event(m, None, MOTION_ONLY_CONF, calibration))
        elif chk["label"] in CHECK_YES:
            events.append(_w017_event(m, chk, posterior, calibration))

    deduped: list[dict] = []
    for e in sorted(events, key=lambda e: (e["camera"], e["scene_t"])):
        prev = deduped[-1] if deduped else None
        if prev and prev["camera"] == e["camera"] and e["scene_t"] - prev["scene_t"] <= DEDUPE_SEC:
            if (SEVERITY_RANK[e["severity"]], -e["confidence"]) < (SEVERITY_RANK[prev["severity"]], -prev["confidence"]):
                deduped[-1] = e
            continue
        deduped.append(e)
    return deduped, dict(annotations), calibration


# --------------------------------------------------------------------------------------------------- driver
def build_events(segs: list[Segment], cam_kin: dict, vlm_w3: dict, moments: tuple[list[dict], list[dict]],
                 checks: dict[str, dict]) -> tuple[list[dict], dict[str, list[str]], dict[str, list[dict]], dict]:
    """Returns (events sorted by severity/confidence, seg_id -> event_ids, seg_id -> Cosmos check annotations,
    w017 check calibration)."""
    index = SegIndex(segs)
    events: list[dict] = []
    scenario: dict[str, dict[str, list[Segment]]] = defaultdict(lambda: defaultdict(list))
    for s in segs:
        if s.is_scenario:
            scenario[s.site_id][s.camera].append(s)
    for site_id, cams in scenario.items():
        views_vlm = {c: vlm_w3[(site_id, c)]["json"] for c in cams if (site_id, c) in vlm_w3}
        events += w3_events(site_id, cams, {c: cam_kin[(site_id, c)] for c in cams}, views_vlm, index)

    cands, controls = moments
    w017, annotations, calibration = w017_events(cands, controls, {k: v["json"] for k, v in checks.items()})
    events += w017

    seen: Counter = Counter()
    for e in events:
        base = f"ev_{e['site_id']}_{e['type']}_{int(round(e['scene_t'] * 10)):05d}"
        seen[base] += 1
        e["event_id"] = base if seen[base] == 1 else f"{base}_{seen[base]}"
    events.sort(key=lambda e: (SEVERITY_RANK[e["severity"]], -e["confidence"], e["site_id"], e["scene_t"]))
    events = [{"event_id": e.pop("event_id"), **e} for e in events]

    seg_events: dict[str, list[str]] = defaultdict(list)
    for e in events:
        for v in e["views"]:
            seg = index.by_source.get(v["source"])
            if seg and e["event_id"] not in seg_events[seg.seg_id]:
                seg_events[seg.seg_id].append(e["event_id"])
    return events, seg_events, annotations, calibration
