"""Neutral, definition-driven Cosmos prompts (YOLO facts injected as sensor data) and reply normalizers."""
from __future__ import annotations

import json

PROMPT_VERSION = "2026-10-09.1"

SYSTEM = ("You are a careful video analyst for warehouse operations. Report only what is visible in the video, "
          "in neutral factual language. Treat the provided sensor facts as reliable measurements.")

MACHINE_TYPES = ("forklift", "agv", "amr", "humanoid")
W017_CHECKS = ("avoids_machine", "machine_close", "no_interaction", "unclear")
W3_EVENTS = ("collision", "near_miss", "person_in_path", "none")
CONGESTION = ("none", "low", "medium", "high")
SEPARATIONS = ("contact", "<1m", "1-2m", "2-4m", ">4m")
POSITIONS = ("left", "center", "right")

VIEW_TEXT = {
    "floor": "high wide view of the main warehouse floor",
    "lane": "view of a robot lane along a wall",
    "ceiling": "high ceiling-mounted wide view",
    "eye": "low eye-level close-up view; the person or the vehicle may be partly cut off",
}

_SYNONYMS = {
    "near-miss": "near_miss", "nearmiss": "near_miss", "near miss": "near_miss",
    "person_in_vehicle_path": "person_in_path", "in_path": "person_in_path", "person in path": "person_in_path",
    "safe": "none", "no_event": "none", "": "none",
    "avoid": "avoids_machine", "avoids": "avoids_machine", "close": "machine_close", "no": "no_interaction",
}


_W017_SCENE = ("in a robot-assisted warehouse with workers and machines: AGVs (low-profile yellow transporters that "
               "carry cartons or pallets), AMRs (small white mobile robots), humanoid robots (bipedal, black or teal "
               "and white) and possibly forklifts")


def w017_facts(kin: dict) -> str:
    """People counts only: per-moment motion hints are left out so the model cannot echo them back."""
    p, hints = kin["people"], kin["machine_hints"]
    return "\n".join([
        f"- person-shaped figures per frame (people AND humanoid robots): median {p['per_frame_median']:g}, "
        f"max {p['per_frame_max']}",
        f"- of those, about {p['idle']:.1f} stay in place and {p['moving']:.1f} walk; "
        f"mean walking-track speed {p['mean_speed_mps']:.2f} m/s",
        f"- non-person objects tracked by the detector (weak hint, class labels unreliable): "
        f"{hints['tracks']}, of which {hints['moving']} move",
    ])


def w017_prompt(camera: str, view: str, kin: dict) -> str:
    return f"""This is a 5-second clip from fixed camera "{camera}" ({VIEW_TEXT[view]}) {_W017_SCENE}.
Watch the whole clip and describe only what is visible.

Sensor facts for this clip from a calibrated person detector and tracker:
{w017_facts(kin)}

Count each physical machine once; people are not machines. A machine is moving if it changes position during the clip; an AGV is loaded if it carries cartons or a pallet.
Congestion: none = open floor; low = people or machines present but routes clear; medium = clusters that slow movement; high = routes blocked or crowded.

Return ONLY a JSON object with this shape:
{{"machines": {{"agv": {{"total": int, "moving": int, "loaded": int}}, "amr": {{"total": int, "moving": int}}, "humanoid": {{"total": int, "moving": int}}, "forklift": {{"total": int, "moving": int}}}},
 "congestion": "none|low|medium|high",
 "summary": str (one neutral, operations-focused sentence about what people and machines are doing)}}"""


def w017_check_prompt(camera: str, view: str, t0: float, t1: float, region: str) -> str:
    """Targeted question about one moment; used identically for candidate and random control moments."""
    return f"""This is a 5-second clip from fixed camera "{camera}" ({VIEW_TEXT[view]}) {_W017_SCENE}.
Focus only on the {region} part of the image between t={t0:.1f} s and t={t1:.1f} s.

Classify what happens there between people and machines with exactly one label:
- avoids_machine: a person steps aside, backs off, stops abruptly or hurries out of the way because a moving machine comes within about 1 m of them
- machine_close: a moving machine passes within about 1 m of a person, but the person does not need to react
- no_interaction: no moving machine comes within about 1 m of any person there
- unclear: that part of the clip is not visible enough to tell
Choose no_interaction unless you can clearly see a moving machine within about 1 m of a person in that part of the image at that time.

Return ONLY a JSON object:
{{"label": "avoids_machine|machine_close|no_interaction|unclear", "machine": "agv|amr|humanoid|forklift|none", "min_distance_m": float, "description": str (one sentence: who does what, where)}}"""


def w3_facts(kin: dict) -> str:
    ev, main = kin["events"], kin.get("main_track") or {}
    tl = ", ".join("n/a" if v is None else f"{v:.1f}" for v in kin["speed_timeline"])
    lines = [f"- person visible in {kin['visible_frac'] * 100:.0f}% of frames",
             f"- person speed per 1-second interval, m/s (0-1 s ... 9-10 s): [{tl}]"]
    for e in ev["evasive"][:2]:
        lines.append(f"- person stood still for {e['standstill_sec']:.1f} s, then moved suddenly at t={e['t']:.1f}s "
                     f"(peak {e['peak_mps']:.1f} m/s)")
    for g in ev["occlusions"][:2]:
        lines.append(f"- person not detected between t={g['t_lost']:.1f}s and t={g['t_found']:.1f}s, then re-detected "
                     f"{g['dist_m']:.1f} m from where they disappeared (hidden behind something)")
    if ev["posture"]:
        p = ev["posture"][0]
        lines.append(f"- person's box was wider than tall between t={p['t0']:.1f}s and t={p['t1']:.1f}s")
    elif main.get("ruler_px"):
        lines.append("- person's box stayed upright the whole clip (no lying-down posture)")
    return "\n".join(lines)


def w3_prompt(camera: str, view: str, kin: dict) -> str:
    return f"""This is a 10-second clip from fixed camera "{camera}" ({VIEW_TEXT[view]}) in an empty warehouse with one worker and one pallet stacker (a forklift-type vehicle with a mast).
Watch the whole clip and pay attention to motion over time. Describe only what is visible, in neutral factual language.

Sensor facts from a person tracker on this camera (reliable for the person; it cannot see the vehicle):
{w3_facts(kin)}

Definitions:
- collision: clearly visible physical contact between the vehicle and the person
- near_miss: the vehicle is moving and comes within about 1 m of the person without visible contact
- person_in_path: the person walks or stands in front of the moving vehicle while it stays farther than about 1 m away
- none: the vehicle does not move toward the person, or they stay well apart
Prefer near_miss over collision unless contact is unambiguous. Set person_fell to true only if the person is clearly lying on the floor.

Return ONLY a JSON object with this shape:
{{"vehicle_visible": bool, "vehicle_moves": bool, "vehicle_moving_0_5s": bool, "vehicle_moving_5_10s": bool,
 "vehicle_motion": str (direction and path relative to the person, with approximate seconds),
 "person_motion": str (what the person does, with approximate seconds),
 "min_separation": "contact|<1m|1-2m|2-4m|>4m",
 "closest_approach_sec": float,
 "event": "collision|near_miss|person_in_path|none",
 "person_fell": bool,
 "evidence": str (what you saw that supports the event label),
 "summary": str (one sentence)}}"""


HUMAN_ACTIVITIES = ("walking", "working_stationary", "waiting")
MACHINE_STATES = ("moving", "attended", "parked")


def _where(region: str | None) -> str:
    return f"Look only at the {region} part of the image." if region else "Look at the whole image."


def labor_check_prompt(camera: str, view: str, region: str | None) -> str:
    return f"""This is a 5-second clip from fixed camera "{camera}" ({VIEW_TEXT[view]}) {_W017_SCENE}.
{_where(region)}

List every human worker you can see. Do NOT include humanoid robots (bipedal machines). For each human give their main activity during the clip with exactly one label:
- walking: moves from one place to another
- working_stationary: stays in place but handles items, operates equipment, or works at a station, shelf or pallet
- waiting: stands or sits without handling anything (waiting, talking, watching)
Then count the humanoid robots separately.

Return ONLY a JSON object:
{{"humans": [{{"position": "left|center|right", "activity": "walking|working_stationary|waiting"}}], "humanoid_robots": int, "description": str (one sentence)}}"""


def machine_check_prompt(camera: str, view: str) -> str:
    return f"""This is a 5-second clip from fixed camera "{camera}" ({VIEW_TEXT[view]}) {_W017_SCENE}.
Look at the whole image.

List every machine you can see: forklifts or pallet stackers, AGVs, AMRs and humanoid robots. Count each physical machine once. For each give its state during the clip with exactly one label:
- moving: drives or walks during the clip
- attended: stopped while being loaded or unloaded, or while a person works with it
- parked: stopped with nobody using it

Return ONLY a JSON object:
{{"machines": [{{"type": "forklift|agv|amr|humanoid", "state": "moving|attended|parked"}}], "description": str (one sentence)}}"""


def crowd_check_prompt(camera: str, view: str, region: str) -> str:
    return f"""This is a 5-second clip from fixed camera "{camera}" ({VIEW_TEXT[view]}) {_W017_SCENE}.
{_where(region)}

Count the humans in that part of the image (do NOT count humanoid robots). Then answer: is anyone's movement there blocked or slowed by people, machines or objects, and are people queuing or waiting for others to pass?

Return ONLY a JSON object:
{{"humans_in_region": int, "movement_obstructed": bool, "queueing": bool, "description": str (one sentence)}}"""


def normalize_labor_check(js) -> dict:
    if not isinstance(js, dict) or not isinstance(js.get("humans"), list):
        raise ValueError("unexpected reply shape")
    acts = [_label((h or {}).get("activity") if isinstance(h, dict) else h, HUMAN_ACTIVITIES) for h in js["humans"]]
    counts = {a: sum(x == a for x in acts) for a in HUMAN_ACTIVITIES}
    return {"humans": sum(counts.values()), **counts, "humanoid_robots": _int(js.get("humanoid_robots")),
            "description": str(js.get("description") or "")[:240]}


def normalize_machine_check(js) -> dict:
    if not isinstance(js, dict) or not isinstance(js.get("machines"), list):
        raise ValueError("unexpected reply shape")
    items = [(_label(m.get("type"), MACHINE_TYPES), _label(m.get("state"), MACHINE_STATES))
             for m in js["machines"] if isinstance(m, dict)]
    items = [(t, s) for t, s in items if t and s]
    return {"machines": len(items), **{s: sum(x == s for _, x in items) for s in MACHINE_STATES},
            "by_type": {t: sum(x == t for x, _ in items) for t in MACHINE_TYPES},
            "description": str(js.get("description") or "")[:240]}


def normalize_crowd_check(js) -> dict:
    if not isinstance(js, dict) or "humans_in_region" not in js:
        raise ValueError("unexpected reply shape")
    return {"humans_in_region": _int(js.get("humans_in_region")), "obstructed": _bool(js.get("movement_obstructed")),
            "queueing": _bool(js.get("queueing")), "description": str(js.get("description") or "")[:240]}


def recommendations_prompt(cards: list[dict], counts: dict, cameras: list[dict]) -> str:
    shown = [{k: c[k] for k in ("card_id", "issue", "guidance", "facts")} for c in cards]
    return f"""You are the operations analyst for a robot-assisted warehouse. The video analytics system found the issues below during the last shift. Each issue card lists measured facts and the kind of action that addresses it.

ISSUE CARDS (JSON):
{json.dumps(shown, separators=(",", ":"))}

COUNTS: {json.dumps(counts, separators=(",", ":"))}
CAMERA TOTALS: {json.dumps(cameras, separators=(",", ":"))}

For EACH card write one recommendation for the shift supervisor:
- title: short imperative title
- action: 1-2 concrete operational steps that follow the card's guidance (equipment settings, floor markings, task assignments, robot dispatch); never just "review" or "monitor"
- rationale: why, quoting the card's facts and numbers
- expected_impact: qualitative; never promise a size of improvement (no "by 30%", "to 80%")
Use ONLY numbers from that card's facts, with the meaning they have there. Do not mix facts between cards.

Then write a 2-4 sentence executive summary of the shift. Call an event high-severity only if its severity is high and take counts from COUNTS. Convert ratios to percentages only by multiplying by 100 (0.59 -> 59%).

Return ONLY a JSON object:
{{"recommendations": [{{"card_id": str, "title": str, "action": str, "rationale": str, "expected_impact": str}}],
 "summary": str (2-4 sentences, plain text)}}"""


def _int(v, lo: int = 0, hi: int = 50) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _float(v, lo: float, hi: float) -> float | None:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


def _bool(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes"))


def _label(v, allowed: tuple[str, ...]) -> str | None:
    s = str(v or "").strip().lower()
    s = _SYNONYMS.get(s, s).replace(" ", "_").replace("-", "_")
    s = _SYNONYMS.get(s, s)
    return s if s in allowed else None


def normalize_w017(js) -> dict:
    if not isinstance(js, dict) or "machines" not in js:
        raise ValueError("unexpected reply shape")
    machines = {}
    for t in MACHINE_TYPES:
        d = (js.get("machines") or {}).get(t) or {}
        total = _int(d.get("total"))
        rec = {"total": total, "moving": min(total, _int(d.get("moving")))}
        if t == "agv":
            rec["loaded"] = min(total, _int(d.get("loaded")))
        machines[t] = rec
    return {"machines": machines, "congestion": _label(js.get("congestion"), CONGESTION) or "none",
            "summary": str(js.get("summary") or "")[:300]}


def normalize_w017_check(js) -> dict:
    if not isinstance(js, dict) or "label" not in js:
        raise ValueError("unexpected reply shape")
    label = _label(js.get("label"), W017_CHECKS) or ("no_interaction" if _label(js.get("label"), ("none",)) else None)
    if label is None:
        raise ValueError(f"unknown label {js.get('label')!r}")
    return {"label": label, "machine": _label(js.get("machine"), MACHINE_TYPES),
            "min_distance_m": _float(js.get("min_distance_m"), 0.0, 50.0),
            "description": str(js.get("description") or "")[:240]}


def normalize_recs(js) -> dict:
    if not isinstance(js, dict) or not isinstance(js.get("recommendations"), list):
        raise ValueError("unexpected reply shape")
    recs = []
    for r in js["recommendations"]:
        if not isinstance(r, dict) or not r.get("title"):
            continue
        recs.append({"card_id": str(r.get("card_id") or ""), "title": str(r["title"])[:160],
                     "action": str(r.get("action") or "")[:600], "rationale": str(r.get("rationale") or "")[:800],
                     "expected_impact": str(r.get("expected_impact") or "")[:400]})
    return {"recommendations": recs, "summary": str(js.get("summary") or "")[:1500]}


def normalize_w3(js) -> dict:
    if not isinstance(js, dict) or "event" not in js:
        raise ValueError("unexpected reply shape")
    return {
        "vehicle_visible": _bool(js.get("vehicle_visible")),
        "vehicle_moves": _bool(js.get("vehicle_moves")),
        "vehicle_moving_0_5s": _bool(js.get("vehicle_moving_0_5s")),
        "vehicle_moving_5_10s": _bool(js.get("vehicle_moving_5_10s")),
        "vehicle_motion": str(js.get("vehicle_motion") or "")[:300],
        "person_motion": str(js.get("person_motion") or "")[:300],
        "min_separation": js.get("min_separation") if js.get("min_separation") in SEPARATIONS else None,
        "closest_approach_sec": _float(js.get("closest_approach_sec"), 0.0, 10.0),
        "event": _label(js.get("event"), W3_EVENTS) or "none",
        "person_fell": _bool(js.get("person_fell")),
        "evidence": str(js.get("evidence") or "")[:300],
        "summary": str(js.get("summary") or "")[:300],
    }
