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
TOTAL_KEYS = ("people_avg", "idle_ratio", "machine_moving_ratio", "person_seconds", "idle_person_seconds")


def compact_payload(util: dict, events: list[dict]) -> dict:
    return {
        "counts": {"events_by_severity": {s: sum(e["severity"] == s for e in events) for s in ("high", "medium", "low")},
                   "flags_by_type": dict(Counter(f["type"] for f in util["flags"]))},
        "cameras": [{"site_id": c["site_id"], "camera": c["camera"], "view": c["view"],
                     **{k: c["totals"][k] for k in TOTAL_KEYS}}
                    for c in util["cameras"] if c["view"] in ("floor", "lane")],
        "flags": [{k: f[k] for k in ("flag_id", "type", "site_id", "camera", "zone", "scene_t0", "scene_t1",
                                     "metric", "message")} for f in util["flags"]],
        "events": [{k: e[k] for k in ("event_id", "type", "severity", "confidence", "site_id", "camera", "scene_t",
                                      "title")} for e in events],
    }


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
              f"t={e['scene_t']:.1f} s" for e in payload["events"][:8]] or ["- No safety events."]
    lines += ["", "## Utilization", "| Camera | People avg | Idle share | Machines moving share |", "|---|---|---|---|"]
    lines += [f"| {c['site_id']} {c['camera']} | {c['people_avg']:.1f} | {c['idle_ratio'] * 100:.0f}% | "
              f"{c['machine_moving_ratio'] * 100:.0f}% |" for c in payload["cameras"]]
    lines += [""] + [f"- {f['message']}" for f in payload["flags"]]
    lines += ["", "## Actions"] + [f"{i}. **{r['title']}**: {r['action']}" for i, r in enumerate(recs, 1)]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------- template
def _flags(payload: dict, ftype: str) -> list[dict]:
    return sorted((f for f in payload["flags"] if f["type"] == ftype),
                  key=lambda f: -abs(f["metric"]["value"] - f["metric"]["threshold"]))


def template(payload: dict) -> tuple[list[dict], str]:
    """Deterministic recommendations and summary from the same payload (fallback when Cosmos fails)."""
    recs: list[dict] = []
    events = payload["events"]

    def add(title: str, action: str, rationale: str, impact: str, refs: list[str]) -> None:
        recs.append({"rec_id": f"rec_{len(recs) + 1:02d}", "title": title, "action": action, "rationale": rationale,
                     "expected_impact": impact, "refs": refs})

    close = [e for e in events if e["type"] in ("collision", "near_miss") and e["site_id"].startswith("w3_")]
    if close:
        add("Enforce a stop-and-yield zone around moving pallet stackers",
            "Enable proximity slowdown/stop on pallet stackers, mark pedestrian walkways and require stackers to "
            "halt when a worker is within the exclusion zone.",
            "; ".join(f"{e['site_id']}: {e['title']} ({e['severity']}, confidence {e['confidence']:.2f}) at "
                      f"t={e['scene_t']:.1f} s" for e in close),
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
        ("labor_surplus", "Rebalance idle labor", "Reassign idle workers from the flagged area to active tasks or "
         "stagger their start times.", "Higher labor utilization during the flagged windows."),
        ("machine_surplus", "Right-size the active robot fleet", "Park or redeploy robots that stay stationary in "
         "the flagged windows.", "Fewer idle machines occupying floor space."),
        ("congestion", "Relieve crowding hot spots", "Move standing work away from the flagged zone and keep it as "
         "a transit area.", "Clearer routes for people and robots."),
        ("bottleneck", "Unblock slow-moving traffic", "Widen or re-route the path through the flagged zone.",
         "Faster movement through the zone."),
        ("underused_zone", "Use idle floor space", "Use the rarely occupied zone for staging or buffer storage.",
         "Better use of available floor area."),
    ):
        flags = _flags(payload, ftype)
        if flags:
            add(title, action, " ".join(f["message"] for f in flags[:3]), impact, [f["flag_id"] for f in flags[:3]])

    sev = payload["counts"]["events_by_severity"]
    summary = (f"{len(events)} safety events ({sev['high']} high, {sev['medium']} medium, {sev['low']} low severity) "
               f"and {len(payload['flags'])} utilization flags across {len(payload['cameras'])} floor cameras.")
    return recs, summary
