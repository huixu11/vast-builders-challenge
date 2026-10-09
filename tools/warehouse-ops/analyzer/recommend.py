"""Recommendations + shift report from one Cosmos text call over issue cards.

The code groups the analysis into issue cards (one per safety-event group or flag type), each with its
facts, the kind of action that addresses it and its refs, ordered by priority (safety first). Cosmos
writes one recommendation per card plus an executive summary. A card's text is kept only if every number
in it appears in that card's facts (allowing rounding and ratio->percent), severity counts match and it
promises no size of improvement; otherwise that card uses its template text. The Safety, Utilization and
Actions sections of the shift report are rendered from the data itself. If the summary or most cards fail
after one corrective retry, the whole output is the deterministic template.
"""
from __future__ import annotations

import re
from collections import Counter

import prompts
from common import log
from fusion import SEVERITY_RANK

NUM_RE = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?")
SEVERITY_COUNT_RE = re.compile(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?!of\b)(?:[a-z-]+\s+)?"
                               r"(high|medium|low)[- ]severity", re.I)
PROJECTION_RE = re.compile(r"\b(?:by|to)\s+(?:at least\s+|about\s+|over\s+)?\d+(?:\.\d+)?\s*(?:%|percent)", re.I)
WORD_NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
SMALL_INTS = set(range(13))
MIN_SUMMARY_CHARS = 80
MIN_ACTION_CHARS = 25
MAX_FACTS = 4
TOTAL_KEYS = ("people_avg", "idle_ratio", "machine_moving_ratio", "person_seconds", "idle_person_seconds")
TEXT_KEYS = ("title", "action", "rationale", "expected_impact")

SAFETY_CARDS = (  # card_id, sites, issue, guidance, fallback (title, action, expected_impact)
    ("safety_drills", "w3_", "A pallet stacker came within about 1 m of a worker in the forklift safety drills",
     "Engineering and procedural controls for pallet stackers around pedestrians: proximity sensing with automatic "
     "slow-down and stop, marked pedestrian exclusion zones along stacker routes, right-of-way rules for workers.",
     ("Enforce a stop-and-yield zone around moving pallet stackers",
      "Enable proximity slowdown/stop on pallet stackers, mark pedestrian walkways and require stackers to halt "
      "when a worker is within the exclusion zone.", "Removes the close-approach situations seen in these runs.")),
    ("safety_floor", "w017", "Robots or vehicles came close to people on the main floor",
     "Separate robot lanes from walkways, slow robots near people, keep standing work out of robot routes.",
     ("Separate robot routes from walking areas on the main floor",
      "Paint dedicated AGV/robot lanes and keep standing workers out of them.",
      "Lower exposure to moving robots on the shared floor.")),
)
FLAG_CARDS = (  # flag type, issue, guidance, fallback (title, action, expected_impact)
    ("labor_surplus", "Many people stand idle",
     "Reassign idle workers to active tasks, stagger breaks or start times, or reduce headcount in the flagged window.",
     ("Rebalance idle labor", "Reassign idle workers from the flagged area to active tasks or stagger their start "
      "times.", "Higher labor utilization during the flagged windows.")),
    ("machine_surplus", "Several machines are in view but mostly stationary",
     "Park, redeploy or re-dispatch the stationary robots; adjust task allocation so fewer machines wait.",
     ("Right-size the active robot fleet", "Park or redeploy robots that stay stationary in the flagged windows.",
      "Fewer idle machines occupying floor space.")),
    ("congestion", "Too many people in one zone at once",
     "Move standing work out of the zone, keep it as a transit area, stagger arrivals. Do not add people there.",
     ("Relieve crowding hot spots", "Move standing work away from the flagged zone and keep it as a transit area.",
      "Clearer routes for people and robots.")),
    ("bottleneck", "People move unusually slowly through a zone", "Re-route or widen the path, remove obstacles.",
     ("Unblock slow-moving traffic", "Widen or re-route the path through the flagged zone.",
      "Faster movement through the zone.")),
    ("underused_zone", "Floor area that is rarely occupied",
     "Use the area for staging or buffer storage, or re-layout; do NOT move staff into it.",
     ("Use idle floor space", "Use the rarely occupied zone for staging or buffer storage.",
      "Better use of available floor area.")),
)


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


def issue_cards(payload: dict) -> list[dict]:
    """Safety cards first (most severe first), then one card per flag type in FLAG_CARDS order."""
    safety = []
    for card_id, prefix, issue, guidance, (title, action, impact) in SAFETY_CARDS:
        evs = [e for e in payload["events"] if e["site_id"].startswith(prefix)]
        if evs:
            facts = [f"{e['site_id']} {e['camera']}: {e['title']} (severity {e['severity']}, confidence "
                     f"{e['confidence']:.2f}) at t={e['scene_t']:.1f} s" for e in evs][:MAX_FACTS]
            safety.append((min(SEVERITY_RANK[e["severity"]] for e in evs), {
                "card_id": card_id, "issue": issue, "guidance": guidance, "facts": facts,
                "refs": [e["event_id"] for e in evs],
                "fallback": {"title": title, "action": action, "rationale": "; ".join(facts), "expected_impact": impact},
            }))
    cards = [card for _, card in sorted(safety, key=lambda p: p[0])]
    for ftype, issue, guidance, (title, action, impact) in FLAG_CARDS:
        flags = sorted((f for f in payload["flags"] if f["type"] == ftype),
                       key=lambda f: -abs(f["metric"]["value"] - f["metric"]["threshold"]))
        if flags:
            facts = [f["message"] for f in flags[:MAX_FACTS]]
            cards.append({"card_id": ftype, "issue": issue, "guidance": guidance, "facts": facts,
                          "refs": [f["flag_id"] for f in flags],
                          "fallback": {"title": title, "action": action, "rationale": " ".join(facts),
                                       "expected_impact": impact}})
    return cards


# ------------------------------------------------------------------------------------------- validation
def _numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in NUM_RE.findall(text)]


def allowed_numbers(data) -> list[float]:
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

    walk(data)
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
        n = WORD_NUMBERS.get(m.group(1).lower())
        if (int(m.group(1)) if n is None else n) != counts[m.group(2).lower()]:
            bad.append(m.group(0))
    return bad


def card_problems(rec: dict | None, card: dict, counts: dict) -> list[str]:
    if rec is None:
        return ["missing"]
    texts = [rec[k] for k in TEXT_KEYS]
    problems = []
    if bad := [b for t in texts for b in ungrounded(t, allowed_numbers([card["facts"], counts]))]:
        problems.append(f"numbers not in its facts ({', '.join(bad[:5])})")
    if bad := [b for t in texts for b in wrong_severity_counts(t, counts["events_by_severity"])]:
        problems.append(f"severity counts differ from COUNTS ({'; '.join(bad)})")
    if bad := PROJECTION_RE.findall(rec["expected_impact"]):
        problems.append(f"expected_impact promises a size of improvement ({'; '.join(bad)})")
    if len(rec["action"]) < MIN_ACTION_CHARS:
        problems.append("action too short")
    return problems


def summary_problems(summary: str, payload: dict) -> list[str]:
    problems = [] if len(summary) >= MIN_SUMMARY_CHARS else ["summary too short"]
    if bad := ungrounded(summary, allowed_numbers(payload)):
        problems.append(f"summary uses numbers not in the data ({', '.join(bad[:5])})")
    if bad := wrong_severity_counts(summary, payload["counts"]["events_by_severity"]):
        problems.append(f"summary severity counts differ from COUNTS ({'; '.join(bad)})")
    return problems


# ---------------------------------------------------------------------------------------------- build
def assemble(cards: list[dict], texts: dict[str, dict]) -> list[dict]:
    recs = []
    for i, card in enumerate(cards, 1):
        text = texts.get(card["card_id"])
        body = {k: text[k] for k in TEXT_KEYS} if text else card["fallback"]
        recs.append({"rec_id": f"rec_{i:02d}", **body, "refs": card["refs"], "source": "cosmos" if text else "template"})
    return recs


def build(util: dict, events: list[dict], vlm, generated_at: str) -> dict:
    payload = compact_payload(util, events)
    cards = issue_cards(payload)
    attempts = []
    if vlm is not None and cards:
        base_prompt = prompts.recommendations_prompt(cards, payload["counts"], payload["cameras"])
        prompt = base_prompt
        for attempt in range(2):
            rec = vlm.ask("recs", prompt, validate=prompts.normalize_recs, cache_key=[], max_tokens=3000)
            if rec is None:
                break
            by_card = {r["card_id"]: r for r in rec["json"]["recommendations"]}
            failed = {c["card_id"]: p for c in cards if (p := card_problems(by_card.get(c["card_id"]), c, payload["counts"]))}
            s_problems = summary_problems(rec["json"]["summary"], payload)
            attempts.append({"cards": len(cards), "cards_failed": failed, "summary_problems": s_problems})
            if not s_problems and 2 * len(failed) <= len(cards):
                recs = assemble(cards, {k: v for k, v in by_card.items() if k not in failed})
                return {"generated_at": generated_at, "model": rec["model"], "recommendations": recs,
                        "shift_report_md": shift_report(payload, recs, rec["json"]["summary"]),
                        "validation": {"source": "cosmos", "attempts": attempts}}
            log(f"recommendations failed validation (attempt {attempt + 1}): {attempts[-1]}")
            issues = [f"card {k}: {'; '.join(p)}" for k, p in failed.items()] + s_problems
            prompt = base_prompt + f"\n\nYour previous answer was rejected: {' | '.join(issues)}. Fix these problems."
    recs = assemble(cards, {})
    return {"generated_at": generated_at, "model": "template", "recommendations": recs,
            "shift_report_md": shift_report(payload, recs, template_summary(payload)),
            "validation": {"source": "template", "attempts": attempts}}


def template_summary(payload: dict) -> str:
    sev = payload["counts"]["events_by_severity"]
    return (f"{len(payload['events'])} safety events ({sev['high']} high, {sev['medium']} medium, {sev['low']} low "
            f"severity) and {len(payload['flags'])} utilization flags across {len(payload['cameras'])} floor cameras.")


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
