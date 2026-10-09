"""Grounded Q&A and shift reports.

Ask: compact facts from the analyzer files + VSS semantic search over both locations, answered by
the text LLM (W&B Inference, falling back to Cosmos3-Reason) under "use ONLY these facts and clips".
Fallbacks keep the demo alive: the search's own LLM synthesis, then VSS /agent/ask, then a
deterministic answer from the data.

Report: deterministic metrics tables computed from the data, plus an LLM narrative whose numbers
are checked against those tables. Results are cached per data version and scope.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any

from app_data import Snapshot, dicts, num, ranked_flags, stable_chunk_name
from app_live import Clients, LiveSources, parse_site_camera, safe_error

log = logging.getLogger("wops.copilot")
LOCATIONS = ("indoor", "warehouse3")
SEARCH_TIMEOUT = 25
ASK_LLM_TIMEOUT = 90
REPORT_LLM_TIMEOUT = 120
AGENT_TIMEOUT = 25

ASK_SYSTEM = (
    "You are Warehouse Ops Copilot, a safety and operations analyst for a warehouse video-analytics system. "
    "Answer using ONLY the FACTS and CLIPS provided. Cite every claim with ids in square brackets exactly as "
    "written, e.g. [evt_123], [flg_7], [rec_2] or [clip1]. Quote numbers exactly as they appear in the facts "
    "(a ratio such as 0.61 may be written as 61%). If the facts and clips do not answer the question, say "
    "plainly what is unknown. Be concise: at most 6 short sentences or bullets. No preamble."
)
REPORT_SYSTEM = (
    "You write shift reports for Warehouse Ops Copilot. Audience: the warehouse operations manager. Be direct, "
    "specific and metrics-first. Use ONLY the facts in DATA. Every number you write must appear in DATA "
    "(a ratio such as 0.61 may be written as 61%). Never invent counts, times or causes. Whenever you mention "
    "an alert, flag or recommendation, include its id in backticks, e.g. `evt_123`."
)


def fmt_t(sec: Any) -> str:
    tenths = int(round(max(0.0, num(sec)) * 10))
    whole, frac = divmod(tenths, 10)
    return f"{whole // 60}:{whole % 60:02d}" + (f".{frac}" if frac else "")


def pct(x: Any) -> str:
    return f"{round(num(x) * 100)}%"


def short(value: Any, limit: int = 200) -> str:
    if isinstance(value, dict):
        text = ", ".join(f"{k}={short(v, 60)}" for k, v in value.items() if v is not None)
    elif isinstance(value, list):
        text = ", ".join(short(v, 60) for v in value)
    else:
        text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def cell(value: Any) -> str:
    return short(value, 140).replace("|", "/")


def clean_llm(text: str | None) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    if "</think>" in text:
        text = text.split("</think>")[-1]
    text = text.split("<think>")[0].strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)```", text, flags=re.S)
    return (fenced.group(1) if fenced else text).strip()


def cited(text: str, snap: Snapshot) -> list[dict]:
    found = []
    for kind, table, title_key in (("event", snap.event_by_id, "title"), ("flag", snap.flag_by_id, "message"),
                                   ("rec", snap.rec_by_id, "title")):
        for id_, obj in table.items():
            if re.search(rf"(?<![\w-]){re.escape(id_)}(?![\w-])", text):
                found.append({"kind": kind, "id": id_, "title": short(obj.get(title_key) or obj.get("type"), 120)})
    return found


# ---------------------------------------------------------------------- facts
def _cam_totals(cams: list[dict]) -> dict:
    tot = [c.get("totals") or {} for c in cams]
    m_tot = sum(num(p.get("machines_total")) for c in cams for p in dicts(c.get("series")))
    m_mov = sum(num(p.get("machines_moving")) for c in cams for p in dicts(c.get("series")))
    agv = [_fleet_type(c, "agv") for c in cams]
    agv_n = sum(num(a.get("avg")) for a in agv)
    return {"people_sum": round(sum(num(t.get("people_avg")) for t in tot), 2),
            "people_mean": round(sum(num(t.get("people_avg")) for t in tot) / len(tot), 2) if tot else 0.0,
            "machine_moving_ratio": round(m_mov / m_tot, 3) if m_tot else 0.0,
            "agv_moving_ratio": round(sum(num(a.get("avg")) * num(a.get("moving_ratio")) for a in agv) / agv_n, 3)
            if agv_n else 0.0,
            "agv_loaded_ratio": round(sum(num(a.get("avg")) * num(a.get("loaded_ratio")) for a in agv) / agv_n, 3)
            if agv_n else 0.0}


def _fleet_type(cam: dict, mtype: str) -> dict:
    return ((cam.get("fleet") or {}).get("types") or {}).get(mtype) or {}


def _fleet_text(cam: dict) -> str:
    f = cam.get("fleet") or {}
    parts = [f"{t}: avg {num(d.get('avg'))}, moving_ratio {num(d.get('moving_ratio'))}"
             + (f", loaded_ratio {num(d.get('loaded_ratio'))}" if "loaded_ratio" in d else "")
             + f", stationary_avg {num(d.get('stationary_avg'))}" for t, d in (f.get("types") or {}).items()]
    return "; ".join(parts) + (f"; windows_with_moving_machine={num(f.get('active_window_share'))}" if f else "")


def reaction_text(r: dict | None) -> str:
    if not r:
        return ""
    parts = []
    if r.get("margin_sec") is not None:
        parts.append(f"worker started moving {num(r['margin_sec'])} s before the closest approach")
    if r.get("peak_mps") is not None:
        parts.append(f"peak escape speed {num(r['peak_mps'])} m/s")
    return "; ".join(parts)


def _busiest_zone(cam: dict) -> str:
    grid = (cam.get("heatmap") or {}).get("occupancy") or []
    best = max(((num(v), c, r) for r, row in enumerate(grid) if isinstance(row, list) for c, v in enumerate(row)),
               default=None)
    return f", busiest_zone=({best[1]},{best[2]})" if best and best[0] > 0 else ""


def camera_lines(snap: Snapshot, util: list[dict], per_camera: bool = False) -> list[str]:
    by_site: dict[str, list[dict]] = {}
    for c in util:
        by_site.setdefault(str(c.get("site_id")), []).append(c)
    lines = []
    for sid, cams in by_site.items():
        if per_camera or snap.site_kind(sid) == "continuous":
            for c in cams:
                t = c.get("totals") or {}
                lines.append(
                    f"- {sid}/{c.get('camera')} [{c.get('view')}]: people_avg={num(t.get('people_avg'))}, "
                    f"machine_moving_ratio={num(t.get('machine_moving_ratio'))}, fleet: {_fleet_text(c)}"
                    f"{_busiest_zone(c)}")
        else:
            agg = _cam_totals(cams)
            lines.append(f"- {sid} ({len(cams)} synchronized views of one forklift scenario): "
                         f"people_avg={agg['people_mean']}")
    return lines


def event_line(e: dict) -> str:
    ev = e.get("evidence") or {}
    return (f"- [{e.get('event_id')}] {e.get('severity')} {e.get('type')} at {e.get('site_id')}/{e.get('camera')}, "
            f"scene time {fmt_t(e.get('scene_t'))}, confidence {num(e.get('confidence'))}: {short(e.get('title'), 120)}. "
            + (f"Reaction: {reaction_text(e.get('reaction'))}. " if e.get("reaction") else "")
            + f"{short(e.get('description'), 220)} Consensus: {short(ev.get('consensus'), 160)}")


def flag_line(f: dict) -> str:
    m = f.get("metric") or {}
    zone = f.get("zone")
    zone_txt = f" zone ({zone[0]},{zone[1]})" if isinstance(zone, list) and len(zone) >= 2 else ""
    return (f"- [{f.get('flag_id')}] {f.get('type')} at {f.get('site_id')}/{f.get('camera')}{zone_txt} during "
            f"{fmt_t(f.get('scene_t0'))}–{fmt_t(f.get('scene_t1'))}: {m.get('name')}={m.get('value')} "
            f"(threshold {m.get('threshold')}). {short(f.get('message'), 200)}")


def rec_line(r: dict) -> str:
    refs = ", ".join(str(x) for x in (r.get("refs") or []))
    return (f"- [{r.get('rec_id')}] {short(r.get('title'), 120)}: {short(r.get('action'), 200)} "
            f"Expected impact: {short(r.get('expected_impact'), 120)} (refs: {refs})")


def facts_block(snap: Snapshot) -> str:
    lines = ["SITES:"]
    for s in snap.sites:
        cams = ", ".join(f"{c.get('camera')}[{c.get('view')}]" for c in dicts(s.get("cameras"))[:12])
        lines.append(f"- {s.get('site_id')}: {short(s.get('title'), 90)} ({s.get('location')}, {snap.site_kind(s.get('site_id'))}, "
                     f"{num(s.get('duration_sec')):g} s of video; cameras: {cams})")
    lines.append("CAMERA METRICS (machine_moving_ratio = moving machine-time / machine-time; per machine type: "
                 "moving_ratio, AGV loaded_ratio = loaded AGV-time / AGV-time, stationary_avg = machines standing "
                 "still on average; person counts include humanoid robots):")
    lines += camera_lines(snap, snap.util_cameras)
    lines.append("SAFETY EVENTS:")
    lines += [event_line(e) for e in snap.events[:40]] or ["- none detected"]
    lines.append("OPERATIONAL FLAGS (bottlenecks, surplus, congestion):")
    lines += [flag_line(f) for f in ranked_flags(snap)[:40]] or ["- none"]
    lines.append("RECOMMENDATIONS:")
    lines += [rec_line(r) for r in snap.recommendations[:15]] or ["- none"]
    return "\n".join(lines)


def rules_answer(question: str, snap: Snapshot) -> str:
    q = question.lower()
    parts: list[str] = []
    floor = [c for c in snap.util_cameras if snap.site_kind(c.get("site_id")) == "continuous"]
    if any(k in q for k in ("agv", "amr", "robot", "fleet", "machine", "idle", "surplus", "utiliz", "efficien",
                            "lane", "机器人", "设备", "车队", "闲置", "效率", "利用", "通道")):
        parts.append("**Fleet by camera** (AGV moving · AGV loaded · machines standing still on average):")
        for c in floor:
            agv = _fleet_type(c, "agv")
            stationary = sum(num(d.get("stationary_avg")) for d in ((c.get("fleet") or {}).get("types") or {}).values())
            parts.append(f"- {c.get('site_id')}/{c.get('camera')} [{c.get('view')}]: {pct(agv.get('moving_ratio'))} · "
                         f"{pct(agv.get('loaded_ratio'))} · {round(stationary, 1)}")
        parts += [f"- [{f.get('flag_id')}] {short(f.get('message'), 200)}" for f in snap.flags
                  if f.get("type") == "machine_surplus"]
    if any(k in q for k in ("forklift", "stacker", "near", "collision", "miss", "path", "safety", "agv", "alert",
                            "叉车", "碰撞", "险", "安全", "告警")):
        parts.append("**Safety alerts:**")
        parts += [f"- [{e.get('event_id')}] {e.get('severity')} {e.get('type')} — {short(e.get('title'), 100)} "
                  f"({e.get('site_id')}/{e.get('camera')} @ {fmt_t(e.get('scene_t'))})"
                  + (f"; {reaction_text(e.get('reaction'))}" if e.get("reaction") else "")
                  for e in snap.events[:8]] or ["- none"]
    if any(k in q for k in ("move", "where", "recommend", "should", "reassign", "improve", "建议", "调", "怎么", "如何")):
        parts.append("**Recommended actions:**")
        parts += [f"- [{r.get('rec_id')}] {short(r.get('title'), 120)} — {short(r.get('action'), 180)}"
                  for r in snap.recommendations[:4]] or ["- none"]
    if not parts:
        sev = {s: sum(1 for e in snap.events if e.get("severity") == s) for s in ("high", "medium", "low")}
        parts.append(f"{len(snap.events)} safety alerts ({sev['high']} high, {sev['medium']} medium, {sev['low']} low) "
                     f"and {len(snap.flags)} operational flags in the analyzed footage.")
        parts += [f"- [{f.get('flag_id')}] {short(f.get('message'), 180)}" for f in ranked_flags(snap)[:3]]
    return "\n".join(parts) + "\n\n_Offline answer computed directly from the analyzer data (language model unavailable)._"


# ---------------------------------------------------------------------- number check
_NUM_IN_TEXT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.]*\d)")


def _variants(v: float) -> set[float]:
    out = {round(v, 3), round(v, 2), round(v, 1), float(round(v))}
    if v <= 1.5:
        out |= {round(v * 100, 1), float(round(v * 100))}
    return out


def verify_numbers(narrative: str, data: str) -> tuple[int, list[str]]:
    allowed: set[float] = set()
    for m in re.finditer(r"\d+(?:\.\d+)?", data.replace(",", "")):
        allowed |= _variants(float(m.group()))
    text = re.sub(r"`[^`]*`|\[[^\]]*\]|\b\d+:\d{2}(?:\.\d)?\b", " ", narrative.replace(",", ""))
    text = re.sub(r"\b[\w-]*_[\w-]*\b", " ", text)  # ids and camera names such as Camera_02
    checked, unverified = 0, []
    for m in _NUM_IN_TEXT.finditer(text):
        checked += 1
        if not (_variants(float(m.group(1))) & allowed):
            unverified.append(m.group(1))
    return checked, unverified[:10]


# ---------------------------------------------------------------------- report tables
LABELS = {
    "en": {"report": "Shift report", "all": "All sites", "scope": "Scope", "views": "camera views",
           "min": "min of video", "segments": "segments analysed", "data": "data", "metric": "Metric",
           "value": "Value", "key": "Key metrics", "cams": "Cameras", "alerts": "Safety alerts",
           "flags": "Bottlenecks & surplus", "recs": "Recommended actions", "none_alerts": "No safety alerts in scope.",
           "none_flags": "No operational flags in scope.", "none_recs": "No recommendations in scope.",
           "people": "People visible (avg)", "agv_moving": "AGV moving (share of AGV-time)",
           "agv_loaded": "AGV loaded (share of AGV-time)", "reaction": "Worker reaction before closest approach",
           "machines": "Machines moving (share of machine-time)", "n_alerts": "Safety alerts", "n_flags": "Operational flags",
           "camera": "Camera", "view": "View", "people_avg": "People avg", "stationary": "Machines standing still (avg)",
           "moving": "Machines moving", "time": "Scene time", "where": "Site / camera", "type": "Type",
           "severity": "Severity", "conf": "Confidence", "alert": "Alert", "ai_note":
           "Narrative by the text LLM; every table is computed directly from the analyzer data.",
           "tmpl_note": "Metrics-only report computed directly from the analyzer data.",
           "s_summary": "Executive summary", "s_safety": "Safety", "s_prod": "Productivity & bottlenecks",
           "s_actions": "Actions for next shift"},
    "zh": {"report": "班次报告", "all": "全部站点", "scope": "范围", "views": "个摄像头视角",
           "min": "分钟视频", "segments": "个片段已分析", "data": "数据", "metric": "指标",
           "value": "数值", "key": "关键指标", "cams": "摄像头", "alerts": "安全告警",
           "flags": "瓶颈与资源冗余", "recs": "建议措施", "none_alerts": "范围内无安全告警。",
           "none_flags": "范围内无运营标记。", "none_recs": "范围内无建议。",
           "people": "可见人数（平均）", "agv_moving": "AGV 运行占比（按 AGV 时间）",
           "agv_loaded": "AGV 载货占比（按 AGV 时间）", "reaction": "工人在最接近前开始躲避的时间",
           "machines": "设备运行占比（按设备时间）", "n_alerts": "安全告警", "n_flags": "运营标记",
           "camera": "摄像头", "view": "视角", "people_avg": "平均人数", "stationary": "静止设备（平均）",
           "moving": "设备运行", "time": "场景时间", "where": "站点 / 摄像头", "type": "类型",
           "severity": "严重度", "conf": "置信度", "alert": "告警", "ai_note":
           "叙述由文本大模型生成；所有表格直接由分析数据计算。",
           "tmpl_note": "纯指标报告，直接由分析数据计算。",
           "s_summary": "执行摘要", "s_safety": "安全", "s_prod": "效率与瓶颈", "s_actions": "下一班次行动"},
}


def report_parts(snap: Snapshot, site_id: str | None, camera: str | None, lang: str) -> dict[str, str]:
    L = LABELS["zh" if lang == "zh" else "en"]
    all_sites = not site_id or site_id == "all"
    site_ids = [str(s.get("site_id")) for s in snap.sites] if all_sites else [site_id]

    def cam_match(e: dict) -> bool:
        return not camera or e.get("camera") == camera or camera in [v.get("camera") for v in dicts(e.get("views"))]

    events = [e for e in snap.events if e.get("site_id") in site_ids and cam_match(e)]
    flags = [f for f in ranked_flags(snap) if f.get("site_id") in site_ids and (not camera or f.get("camera") == camera)]
    ids = {e.get("event_id") for e in events} | {f.get("flag_id") for f in flags}
    recs = [r for r in snap.recommendations if all_sites and not camera or set(r.get("refs") or []) & ids]
    util = [c for c in snap.util_cameras if c.get("site_id") in site_ids and (not camera or c.get("camera") == camera)]
    floor = [c for c in util if snap.site_kind(c.get("site_id")) == "continuous"]
    base = floor or util
    agg = _cam_totals(base)
    segs = [s for s in snap.segments if s.get("site_id") in site_ids and (not camera or s.get("camera") == camera)]
    video_min = sum(num(s.get("duration_sec")) * (1 if camera else len(dicts(s.get("cameras"))))
                    for s in snap.sites if s.get("site_id") in site_ids) / 60

    title = L["all"] if all_sites else snap.site_title(site_id)
    title = f"{L['report']} — {title}" + (f" · {camera}" if camera else "")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meta = (f"{L['scope']}: {len(util)} {L['views']} · {video_min:.1f} {L['min']} · {len(segs)} {L['segments']} · "
            f"{L['data']}: {snap.kind} · {generated}")

    sev = {s: sum(1 for e in events if e.get("severity") == s) for s in ("high", "medium", "low")}
    flag_types: dict[str, int] = {}
    for f in flags:
        flag_types[str(f.get("type"))] = flag_types.get(str(f.get("type")), 0) + 1
    people = agg["people_sum"] if floor else agg["people_mean"]
    reactions = [e for e in events if (e.get("reaction") or {}).get("margin_sec") is not None]
    kpi = [f"| {L['metric']} | {L['value']} |", "|---|---|",
           f"| {L['n_alerts']} | {sev['high']} high · {sev['medium']} medium · {sev['low']} low |"]
    if reactions:
        kpi.append(f"| {L['reaction']} | " + ", ".join(f"{e.get('site_id')} {num(e['reaction']['margin_sec'])} s"
                                                      for e in reactions) + " |")
    if floor:
        kpi += [f"| {L['machines']} | {pct(agg['machine_moving_ratio'])} |",
                f"| {L['agv_moving']} | {pct(agg['agv_moving_ratio'])} |",
                f"| {L['agv_loaded']} | {pct(agg['agv_loaded_ratio'])} |"]
    kpi += [f"| {L['people']} | {people} |",
            f"| {L['n_flags']} | {len(flags)}" + (" (" + ", ".join(f"{k} {v}" for k, v in flag_types.items()) + ")" if flags else "") + " |"]

    cam_rows = [f"| {L['camera']} | {L['view']} | {L['moving']} | {L['agv_moving']} | {L['agv_loaded']} | {L['stationary']} |",
                "|---|---|---|---|---|---|"]
    by_site: dict[str, list[dict]] = {}
    for c in util:
        by_site.setdefault(str(c.get("site_id")), []).append(c)
    for sid, cams in by_site.items():
        if camera or snap.site_kind(sid) == "continuous":
            for c in cams:
                t, agv = c.get("totals") or {}, _fleet_type(c, "agv")
                stationary = sum(num(d.get("stationary_avg")) for d in ((c.get("fleet") or {}).get("types") or {}).values())
                cam_rows.append(f"| {sid}/{c.get('camera')} | {c.get('view')} | {pct(t.get('machine_moving_ratio'))} | "
                                f"{pct(agv.get('moving_ratio'))} | {pct(agv.get('loaded_ratio'))} | {round(stationary, 2)} |")

    alert_rows = [f"| {L['time']} | {L['where']} | {L['type']} | {L['severity']} | {L['conf']} | {L['alert']} |",
                  "|---|---|---|---|---|---|"]
    alert_rows += [f"| {fmt_t(e.get('scene_t'))} | {e.get('site_id')}/{e.get('camera')} | {e.get('type')} | "
                   f"{e.get('severity')} | {num(e.get('confidence')):.2f} | {cell(e.get('title'))} `{e.get('event_id')}` |"
                   for e in events]
    flag_items = [f"- **{f.get('type')}** · {f.get('site_id')}/{f.get('camera')}"
                  + (f" zone ({f['zone'][0]},{f['zone'][1]})" if isinstance(f.get("zone"), list) and len(f["zone"]) >= 2 else "")
                  + f" · {fmt_t(f.get('scene_t0'))}–{fmt_t(f.get('scene_t1'))} — {(f.get('metric') or {}).get('name')} "
                  f"{(f.get('metric') or {}).get('value')} vs threshold {(f.get('metric') or {}).get('threshold')}: "
                  f"{short(f.get('message'), 220)} `{f.get('flag_id')}`" for f in flags]
    rec_items = [f"{i}. **{short(r.get('title'), 140)}** — {short(r.get('action'), 260)}"
                 + (f" _Impact: {short(r.get('expected_impact'), 140)}_" if r.get("expected_impact") else "")
                 + f" `{r.get('rec_id')}`" for i, r in enumerate(recs, 1)]
    return {
        "title": title, "meta": meta, "L": L,
        "kpi": "\n".join(kpi), "cameras": "\n".join(cam_rows),
        "alerts": "\n".join(alert_rows) if events else L["none_alerts"],
        "flags": "\n".join(flag_items) if flags else L["none_flags"],
        "recs": "\n".join(rec_items) if recs else L["none_recs"],
    }


def _tables(p: dict, with_recs: bool) -> str:
    L = p["L"]
    out = (f"## {L['key']}\n{p['kpi']}\n\n## {L['cams']}\n{p['cameras']}\n\n## {L['alerts']}\n{p['alerts']}\n\n"
           f"## {L['flags']}\n{p['flags']}\n")
    return out + (f"\n## {L['recs']}\n{p['recs']}\n" if with_recs else "")


def template_report(p: dict) -> str:
    return f"# {p['title']}\n_{p['meta']}_\n\n_{p['L']['tmpl_note']}_\n\n{_tables(p, True)}"


# ---------------------------------------------------------------------- service
class Copilot:
    def __init__(self, clients: Clients, live: LiveSources) -> None:
        self.clients = clients
        self.live = live
        self._io = ThreadPoolExecutor(max_workers=6, thread_name_prefix="search")
        self._ask_llm = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ask-llm")
        self._report_llm = ThreadPoolExecutor(max_workers=2, thread_name_prefix="report-llm")
        self._lock = threading.RLock()  # add_done_callback may run the callback while the lock is held
        self._reports: dict[tuple, dict] = {}
        self._inflight: dict[tuple, Future] = {}

    def _llm_ready(self) -> bool:
        return bool(getattr(self.clients.llm, "available", True))

    def _chat(self, system: str, user: str, max_tokens: int) -> str | None:
        try:
            text = clean_llm(self.clients.llm.chat(user, max_tokens=max_tokens, temperature=0.2, system=system, retries=1))
            return text or None
        except Exception as e:  # noqa: BLE001
            log.warning("text llm chat failed: %s", safe_error(e))
            return None

    # ------------------------------------------------------------------ ask
    def _clip(self, r: dict, snap: Snapshot) -> dict:
        src, video = r.get("source") or "", r.get("original_video") or ""
        ref = snap.seg_by_source.get(src)
        chunk = snap.chunk_by_video.get(video) or snap.chunk_by_stable.get(stable_chunk_name(r.get("filename") or video))
        where = ((ref["site_id"], ref["camera"]) if ref else (chunk["site_id"], chunk["camera"]) if chunk
                 else parse_site_camera(r.get("filename") or src) or (r.get("location"), r.get("camera_id")))
        t = num(r.get("segment_start_sec"))
        return {"source": src, "original_video": video, "t": t, "t_end": num(r.get("segment_end_sec"), t + 5),
                "scene_t": (chunk["scene_t0"] + t) if chunk else (ref["scene_t0"] if ref else None),
                "score": round(num(r.get("similarity_score")), 3), "caption": short(r.get("reasoning_content"), 320),
                "site_id": where[0], "camera": where[1]}

    def search(self, question: str, snap: Snapshot, per_location: int = 6, limit: int = 6) -> tuple[list[dict], str | None]:
        vss = self.clients.vss()
        futures = {loc: self._io.submit(vss.post, "/api/v1/search", {
            "query": question, "top_k": per_location, "min_similarity": 0.2,
            "metadata_filters": {"location": loc}}, SEARCH_TIMEOUT) for loc in LOCATIONS}
        clips, syntheses = [], []
        for loc, fut in futures.items():
            try:
                res = fut.result(timeout=SEARCH_TIMEOUT + 3)
            except Exception as e:  # noqa: BLE001
                log.warning("search (%s) failed: %s", loc, safe_error(e))
                continue
            hits = [self._clip(r, snap) for r in res.get("results") or [] if r.get("source")]
            clips += hits
            synth = (res.get("llm_synthesis") or {}).get("response")
            if synth and hits:
                syntheses.append((max(h["score"] for h in hits), synth))
        seen, unique = set(), []
        for c in sorted(clips, key=lambda c: -c["score"]):
            if c["source"] not in seen:
                seen.add(c["source"])
                unique.append(c)
        unique = unique[:limit]
        self.live.vouch([u for c in unique for u in (c["source"], c["original_video"])])
        best = max(syntheses, default=(0, None))[1]
        return unique, best

    def ask(self, question: str, snap: Snapshot, lang: str | None = None) -> dict:
        started = time.time()
        notes: list[str] = []
        try:
            clips, synthesis = self.search(question, snap)
        except Exception as e:  # noqa: BLE001
            log.warning("video search unavailable: %s", safe_error(e))
            clips, synthesis = [], None
            notes.append("video search unavailable")
        answer, engine = None, None
        if self._llm_ready():
            clip_lines = [f"[clip{i}] {c['site_id']}/{c['camera']} scene {fmt_t(c['scene_t'])} "
                          f"(similarity {c['score']}): {c['caption']}" for i, c in enumerate(clips, 1)] or ["(no clips found)"]
            lang_line = "Answer in Simplified Chinese." if lang == "zh" else "Answer in the language of the question."
            prompt = (f"FACTS (from the warehouse video analyzer):\n{facts_block(snap)}\n\n"
                      "CLIPS (semantic video-search hits; captions are machine-generated and may miss hazards):\n"
                      + "\n".join(clip_lines) + f"\n\nQUESTION: {question}\n\n{lang_line} Cite ids in square brackets.")
            fut = self._ask_llm.submit(self._chat, ASK_SYSTEM, prompt, 3000)
            try:
                answer = fut.result(timeout=ASK_LLM_TIMEOUT)
            except FutureTimeout:
                notes.append("language model timed out")
            engine = "llm" if answer else None
        if not answer and synthesis:
            answer, engine = clean_llm(synthesis), "vss_search"
        if not answer:
            answer = self._agent_answer(question)
            engine = "vss_agent" if answer else None
        if not answer:
            answer, engine = rules_answer(question, snap), "rules"
        return {"question": question, "answer": answer, "engine": engine, "clips": clips, "used": cited(answer, snap),
                "notes": notes, "elapsed_ms": int((time.time() - started) * 1000)}

    def _agent_answer(self, question: str) -> str | None:
        try:
            res = self.clients.vss().post("/api/v1/agent/ask", {"question": question, "top_k": 8}, timeout=AGENT_TIMEOUT)
            return clean_llm(res.get("answer")) or None
        except Exception as e:  # noqa: BLE001
            log.warning("agent/ask fallback failed: %s", safe_error(e))
            return None

    # ------------------------------------------------------------------ report
    def _ai_report(self, snap: Snapshot, site_id: str | None, camera: str | None, lang: str) -> dict | None:
        p = report_parts(snap, site_id, camera, lang)
        data = _tables(p, True)
        lang_line = ("Write in Simplified Chinese; keep ids, camera names and numbers unchanged." if lang == "zh"
                     else "Write in English.")
        L = p["L"]
        prompt = (f"DATA for {p['title']}:\n{data}\n\nWrite exactly these Markdown sections and nothing else:\n"
                  f"## {L['s_summary']}\n3-5 bullets, most important first.\n"
                  f"## {L['s_safety']}\n2-4 bullets (write '{L['none_alerts']}' if there are none).\n"
                  f"## {L['s_prod']}\n2-4 bullets on fleet efficiency: AGV/AMR/humanoid moving and loaded shares, "
                  f"machines standing still, congestion and underused zones.\n"
                  f"## {L['s_actions']}\n3-5 numbered actions, each tied to an id.\n"
                  f"No tables, no title. {lang_line}")
        narrative = self._chat(REPORT_SYSTEM, prompt, 3000)
        if not narrative:
            return None
        narrative = re.sub(r"^\s*#\s[^\n]*\n", "", narrative).strip()
        checked, unverified = verify_numbers(narrative, data + "\n" + p["meta"])
        md = f"# {p['title']}\n_{p['meta']}_\n\n_{p['L']['ai_note']}_\n\n{narrative}\n\n{_tables(p, False)}"
        return {"markdown": md, "engine": "llm", "numbers_checked": checked, "numbers_unverified": unverified}

    def report(self, snap: Snapshot, site_id: str | None, camera: str | None, mode: str = "ai",
               lang: str = "en", timeout: float = REPORT_LLM_TIMEOUT) -> dict:
        lang = "zh" if lang == "zh" else "en"
        site_id = None if site_id in (None, "", "all") else site_id
        if mode == "template" or not self._llm_ready():
            return self._fallback_report(snap, site_id, camera, lang, mode)
        key = (snap.version, site_id or "all", camera or "", lang)
        with self._lock:
            hit = self._reports.get(key)
            if hit:
                return {**hit, "cached": True}
            fut = self._inflight.get(key)
            if fut is None:
                fut = self._report_llm.submit(self._ai_report, snap, site_id, camera, lang)
                self._inflight[key] = fut
                fut.add_done_callback(lambda f, k=key: self._report_done(k, f))
        try:
            result = fut.result(timeout=timeout)
        except FutureTimeout:
            result = None
        return {**result, "cached": False} if result else self._fallback_report(snap, site_id, camera, lang, mode)

    def _report_done(self, key: tuple, fut: Future) -> None:
        with self._lock:
            self._inflight.pop(key, None)
            try:
                result = fut.result()
            except Exception as e:  # noqa: BLE001
                log.warning("report generation failed: %s", safe_error(e))
                result = None
            if result:
                self._reports = {k: v for k, v in self._reports.items() if k[0] == key[0]}
                self._reports[key] = result

    def _fallback_report(self, snap: Snapshot, site_id: str | None, camera: str | None, lang: str, mode: str) -> dict:
        if mode != "template" and not site_id and not camera and snap.shift_report_md:
            return {"markdown": snap.shift_report_md, "engine": "analyzer", "cached": False}
        return {"markdown": template_report(report_parts(snap, site_id, camera, lang)), "engine": "template",
                "cached": False}

    def warm_reports(self, snap: Snapshot) -> None:
        """Pre-generate site-level reports so the demo never waits on the first click."""
        if not self._llm_ready():
            return
        for site_id in [None] + [str(s.get("site_id")) for s in snap.sites]:
            self.report(snap, site_id, None, "ai", "en", timeout=REPORT_LLM_TIMEOUT * 2)
