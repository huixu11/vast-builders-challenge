"""Recommendations + shift report from one Cosmos text call over compact metrics.

Cosmos writes the recommendations and an executive summary. Every number it uses must appear in the
input payload (allowing rounding and ratio->percent), severity counts must match, impacts must not
promise sizes of improvement, refs must name real flags/events, and at least one recommendation must
address the high-severity events (any it left out are attached to that recommendation). The Safety,
Utilization and Actions sections of the shift report are rendered from the data itself. After one
corrective retry, a deterministic template built from the same payload is used instead.
"""
from __future__ import annotations

import re
from collections import Counter

import prompts
from common import log

NUM_RE = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?")
SEVERITY_COUNT_RE = re.compile(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?!of\b)(?:[a-z-]+\s+)?"
                               r"(high|medium|low)[- ]severity", re.I)
PROJECTION_RE = re.compile(r"\b(?:by|to)\s+(?:at least\s+|about\s+|over\s+)?\d+(?:\.\d+)?\s*(?:%|percent)", re.I)
WORD_NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
SMALL_INTS = set(range(13))
MAX_UNGROUNDED_SHARE = 0.1
MIN_SUMMARY_CHARS = 80
TOTAL_KEYS = ("people_avg", "machine_moving_ratio")
REACTION_KEYS = ("onset_t", "evade_t", "peak_mps", "closest_t", "closest_spread_sec", "margin_sec", "margin_reliable",
                 "min_separation", "danger", "verdict")
VERDICT_TEXT = {"contact": "contact with the worker", "forced_evasion": "worker was forced to run clear",
                "short_margin": "too little reaction margin", "close_pass": "forklift passed within 2 m"}


def _fleet(c: dict) -> dict:
    f = c.get("fleet") or {}
    return {"types": f.get("types") or {}, "active_window_share": f.get("active_window_share", 0.0),
            "stalled_window_share": f.get("stalled_window_share", 0.0)}


def compact_payload(util: dict, events: list[dict]) -> dict:
    flags = [f for f in util["flags"] if f["type"] != "labor_surplus"]
    return {
        "counts": {"events_by_severity": {s: sum(e["severity"] == s for e in events) for s in ("high", "medium", "low")},
                   "flags_by_type": dict(Counter(f["type"] for f in flags))},
        "cameras": [{"site_id": c["site_id"], "camera": c["camera"], "view": c["view"],
                     **{k: c["totals"][k] for k in TOTAL_KEYS}, "fleet": _fleet(c)}
                    for c in util["cameras"] if c["view"] in ("floor", "lane")],
        "flags": [{k: f[k] for k in ("flag_id", "type", "site_id", "camera", "zone", "scene_t0", "scene_t1",
                                     "metric", "message")} for f in flags],
        "events": [{**{k: e[k] for k in ("event_id", "type", "severity", "confidence", "site_id", "camera", "scene_t",
                                         "title")},
                    **({"reaction": {k: e["reaction"][k] for k in REACTION_KEYS}} if e.get("reaction") else {})}
                   for e in events],
    }


def reaction_text(r: dict | None) -> str:
    if not r:
        return ""
    parts = [VERDICT_TEXT.get(r.get("verdict"), "dangerous pass")]
    if r.get("peak_mps") is not None:
        parts.append(f"peak escape speed {r['peak_mps']:.1f} m/s")
    if r.get("onset_t") is not None:
        parts.append(f"worker started moving at t={r['onset_t']:.1f} s")
    if r.get("margin_sec") is not None:
        parts.append(f"{r['margin_sec']:.1f} s before the closest approach" if r.get("margin_reliable") else
                     f"closest-approach time uncertain (VLM views disagree by {r.get('closest_spread_sec') or 0:.1f} s)")
    return "; ".join(parts)


def _numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in NUM_RE.findall(text)]


def allowed_numbers(payload) -> list[float]:
    found: list[float] = []

    def walk(x) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            found.append(float(x))
        elif isinstance(x, str):
            found.extend(_numbers(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(payload)
    derived = set()
    for v in found:
        derived |= {v, round(v), round(v, 1), round(v * 100), round(v * 100, 1), round(v / 60, 1)}
    return sorted(derived)


def ungrounded(text: str, allowed: list[float]) -> list[str]:
    bad = []
    for raw in NUM_RE.findall(text):
        x = float(raw.replace(",", ""))
        if x in SMALL_INTS or any(abs(x - a) <= 0.05 + 0.005 * abs(a) for a in allowed):
            continue
        bad.append(raw)
    return bad


def wrong_severity_counts(text: str, counts: dict[str, int]) -> list[str]:
    bad = []
    for m in SEVERITY_COUNT_RE.finditer(text):
        n = WORD_NUMBERS.get(m.group(1).lower(), None)
        n = int(m.group(1)) if n is None else n
        if n != counts[m.group(2).lower()]:
            bad.append(m.group(0))
    return bad


def check(js: dict, payload: dict, known_refs: set[str], allowed: list[float], high_events: set[str]
          ) -> tuple[bool, list[dict], dict]:
    recs = []
    for r in js["recommendations"]:
        refs = [x for x in r["refs"] if x in known_refs]
        if refs:
            recs.append({"rec_id": f"rec_{len(recs) + 1:02d}", **r, "refs": refs})
    texts = [r[k] for r in recs for k in ("title", "action", "rationale", "expected_impact")] + [js["summary"]]
    bad = [b for t in texts for b in ungrounded(t, allowed)]
    checked = sum(len(NUM_RE.findall(t)) for t in texts)
    severity_errors = [b for t in texts for b in wrong_severity_counts(t, payload["counts"]["events_by_severity"])]
    projections = [m.group(0) for r in recs for m in PROJECTION_RE.finditer(r["expected_impact"])]

    missing_high = sorted(high_events - {ref for r in recs for ref in r["refs"]})
    safety = max(recs, key=lambda r: len(high_events & set(r["refs"])), default=None)
    addresses_high = not high_events or bool(safety and high_events & set(safety["refs"]))
    if addresses_high and missing_high:
        safety["refs"] = safety["refs"] + missing_high
    ok = (len(recs) >= 2 and len(js["summary"]) >= MIN_SUMMARY_CHARS and addresses_high and not severity_errors
          and not projections and len(bad) <= max(1, MAX_UNGROUNDED_SHARE * checked))
    return ok, recs, {"numbers_checked": checked, "ungrounded": bad[:20], "recs_kept": len(recs),
                      "recs_returned": len(js["recommendations"]),
                      "uncited_high_events": [] if addresses_high else missing_high,
                      "high_refs_attached": missing_high if addresses_high else [],
                      "wrong_severity_counts": severity_errors, "promised_improvements": projections}


def _feedback(report: dict) -> str:
    problems = []
    if report["ungrounded"]:
        problems.append(f"it used numbers that are not in DATA ({', '.join(report['ungrounded'][:10])})")
    if report["uncited_high_events"]:
        problems.append(f"no recommendation addressed the high-severity events {', '.join(report['uncited_high_events'])}")
    if report["wrong_severity_counts"]:
        problems.append(f"severity counts do not match DATA.counts ({'; '.join(report['wrong_severity_counts'])})")
    if report["promised_improvements"]:
        problems.append(f"expected_impact promised sizes of improvement ({'; '.join(report['promised_improvements'])})")
    if report["recs_kept"] < 2:
        problems.append("fewer than 2 recommendations had valid refs")
    if report.get("labor_wording"):
        problems.append("it made claims about labor or idle workers, which the data does not measure")
    return "; ".join(problems) or "the summary was too short"


def build(util: dict, events: list[dict], vlm, generated_at: str) -> dict:
    payload = compact_payload(util, events)
    known = {f["flag_id"] for f in payload["flags"]} | {e["event_id"] for e in payload["events"]}
    high = {e["event_id"] for e in payload["events"] if e["severity"] == "high"}
    allowed = allowed_numbers(payload)
    attempts = []
    if vlm is not None:
        prompt = prompts.recommendations_prompt(payload)
        for attempt in range(2):
            rec = vlm.ask("recs", prompt, validate=prompts.normalize_recs, cache_key=[], max_tokens=3000)
            if rec is None:
                break
            ok, recs, report = check(rec["json"], payload, known, allowed, high)
            report["labor_wording"] = has_labor_wording(recs, rec["json"]["summary"])
            ok = ok and not report["labor_wording"]
            attempts.append(report)
            if ok:
                return {"generated_at": generated_at, "model": rec["model"], "recommendations": recs,
                        "shift_report_md": shift_report(payload, recs, rec["json"]["summary"]),
                        "validation": {"source": "cosmos", "attempts": attempts}}
            log(f"recommendations failed validation (attempt {attempt + 1}): {report}")
            prompt = prompts.recommendations_prompt(payload) + (
                f"\n\nYour previous answer was rejected because {_feedback(report)}. "
                f"Fix this: use only DATA numbers and real flag_id/event_id values.")
    recs, summary = template(payload)
    return {"generated_at": generated_at, "model": "template", "recommendations": recs,
            "shift_report_md": shift_report(payload, recs, summary),
            "validation": {"source": "template", "attempts": attempts}}


def shift_report(payload: dict, recs: list[dict], summary: str) -> str:
    """Markdown report: the summary paragraph plus sections rendered directly from the data."""
    lines = ["## Summary", summary.strip(), "", "## Safety"]
    lines += [f"- **{e['title']}** ({e['severity']}, confidence {e['confidence']:.2f}): {e['site_id']} {e['camera']}, "
              f"t={e['scene_t']:.1f} s" + (f"; {reaction_text(e.get('reaction'))}" if e.get("reaction") else "")
              for e in payload["events"][:8]] or ["- No safety events."]

    def share(c: dict, mtype: str, key: str) -> str:
        v = c["fleet"]["types"].get(mtype, {}).get(key)
        return "-" if v is None else f"{v * 100:.0f}%"

    lines += ["", "## Fleet efficiency",
              "| Camera | Machines moving | AGV moving | AMR moving | Humanoid moving | Windows with motion |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {c['site_id']} {c['camera']} | {c['machine_moving_ratio'] * 100:.0f}% | {share(c, 'agv', 'moving_ratio')} | "
              f"{share(c, 'amr', 'moving_ratio')} | "
              f"{share(c, 'humanoid', 'moving_ratio')} | {c['fleet']['active_window_share'] * 100:.0f}% |"
              for c in payload["cameras"]]
    lines += [""] + [f"- {f['message']}" for f in payload["flags"]]
    lines += ["", "## Actions"] + [f"{i}. **{r['title']}**: {r['action']}" for i, r in enumerate(recs, 1)]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------- template
ZH = {
    "Enforce a stop-and-yield zone around moving pallet stackers": {
        "title_zh": "在行驶中的堆高车周围设置停车让行区",
        "action_zh": "为堆高车开启接近减速/停车，标出人行通道，工人进入禁行区时堆高车必须停下。",
        "impact_zh": "消除这几次场景中出现的近距离逼近。"},
    "Coach workers not to cross in front of moving vehicles": {
        "title_zh": "提醒工人不要在行驶车辆前横穿",
        "action_zh": "班前讲解路权规则，并在交叉点加地面标线。",
        "impact_zh": "减少工人走进车辆行驶路径。"},
    "Separate robot routes from walking areas on the main floor": {
        "title_zh": "在主作业区把机器人路线和人行区分开",
        "action_zh": "划出 AGV/机器人专用通道，站立作业不要占用通道。",
        "impact_zh": "降低共享区域里与移动机器人的接触。"},
    "Right-size the active robot fleet": {
        "title_zh": "调整在场机器人数量",
        "action_zh": "标记时段里一直静止的机器人，停回停车位或调去别处。",
        "impact_zh": "减少静止设备占用地面空间。"},
    "Relieve crowding hot spots": {
        "title_zh": "缓解拥堵热点",
        "action_zh": "把站立作业移出被标记的格子，让它保持为通行区域。",
        "impact_zh": "人和机器人的通行路线更通畅。"},
    "Unblock slow-moving traffic": {
        "title_zh": "疏通缓慢通行",
        "action_zh": "加宽或改道经过被标记格子的路线。",
        "impact_zh": "通过该区域更快。"},
    "Use the rarely occupied zone": {
        "title_zh": "利用很少有人的区域",
        "action_zh": "把很少有人的格子用作暂存或缓冲区。",
        "impact_zh": "更好地利用现有地面面积。"},
}
LABOR_RE = re.compile(r"\b(labou?r|idle (?:workers?|staff|people)|staffing|reassign(?:ing)? (?:workers?|staff))\b", re.I)


def has_labor_wording(recs: list[dict], summary: str) -> bool:
    """The analyzer measures machines and occupancy, not worker activity, so labor/idle-worker claims are ungrounded."""
    text = " ".join([summary] + [str(r.get(k, "")) for r in recs for k in ("title", "action", "rationale", "expected_impact")])
    return bool(LABOR_RE.search(text))


def _flags(payload: dict, ftype: str) -> list[dict]:
    return sorted((f for f in payload["flags"] if f["type"] == ftype),
                  key=lambda f: -abs(f["metric"]["value"] - f["metric"]["threshold"]))


def template(payload: dict) -> tuple[list[dict], str]:
    """Deterministic recommendations and summary from the same payload (fallback when Cosmos fails)."""
    recs: list[dict] = []
    events = payload["events"]

    def add(title: str, action: str, rationale: str, impact: str, refs: list[str]) -> None:
        recs.append({"rec_id": f"rec_{len(recs) + 1:02d}", "title": title, "action": action, "rationale": rationale,
                     "expected_impact": impact, "refs": refs, **ZH.get(title, {})})

    close = [e for e in events if e["type"] in ("collision", "near_miss") and e["site_id"].startswith("w3_")]
    if close:
        add("Enforce a stop-and-yield zone around moving pallet stackers",
            "Enable proximity slowdown/stop on pallet stackers, mark pedestrian walkways and require stackers to "
            "halt when a worker is within the exclusion zone.",
            "; ".join(f"{e['site_id']}: {e['title']} ({e['severity']}, confidence {e['confidence']:.2f}) at "
                      f"t={e['scene_t']:.1f} s" + (f" ({reaction_text(e.get('reaction'))})" if e.get("reaction") else "")
                      for e in close),
            "Removes the close-approach situations seen in these runs.", [e["event_id"] for e in close])
    in_path = [e for e in events if e["type"] == "person_in_path"]
    if in_path:
        add("Coach workers not to cross in front of moving vehicles",
            "Brief the shift on right-of-way rules and add floor markings at crossing points.",
            "; ".join(f"{e['site_id']} {e['camera']}: {e['title']} at t={e['scene_t']:.1f} s "
                      f"(confidence {e['confidence']:.2f})" for e in in_path),
            "Fewer workers walking into active vehicle paths.", [e["event_id"] for e in in_path])
    floor = [e for e in events if e["site_id"] == "w017" and e["type"] in ("near_miss", "collision", "robot_proximity")]
    if floor:
        add("Separate robot routes from walking areas on the main floor",
            "Paint dedicated AGV/robot lanes and keep standing workers out of them.",
            "; ".join(f"{e['camera']}: {e['title']} at t={e['scene_t']:.1f} s (confidence {e['confidence']:.2f})"
                      for e in floor[:4]),
            "Lower exposure to moving robots on the shared floor.", [e["event_id"] for e in floor])
    for ftype, title, action, impact in (
        ("machine_surplus", "Right-size the active robot fleet", "Park or redeploy robots that stay stationary in "
         "the flagged windows.", "Fewer stationary machines occupying floor space."),
        ("congestion", "Relieve crowding hot spots", "Move standing work away from the flagged zone and keep it as "
         "a transit area.", "Clearer routes for people and robots."),
        ("bottleneck", "Unblock slow-moving traffic", "Widen or re-route the path through the flagged zone.",
         "Faster movement through the zone."),
        ("underused_zone", "Use the rarely occupied zone", "Use the rarely occupied zone for staging or buffer storage.",
         "Better use of available floor area."),
    ):
        flags = _flags(payload, ftype)
        if flags:
            add(title, action, " ".join(f["message"] for f in flags[:3]), impact, [f["flag_id"] for f in flags[:3]])

    sev = payload["counts"]["events_by_severity"]
    summary = (f"{len(events)} safety events ({sev['high']} high, {sev['medium']} medium, {sev['low']} low severity) "
               f"and {len(payload['flags'])} efficiency flags across {len(payload['cameras'])} robot-floor cameras.")
    return recs, summary
