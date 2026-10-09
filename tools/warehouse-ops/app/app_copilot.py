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
VERDICT_TEXT = {"contact": "contact with the worker", "forced_evasion": "worker was forced to run clear",
                "short_margin": "too little reaction margin", "close_pass": "forklift passed within 2 m"}

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
    "(a ratio such as 0.61 may be written as 61%). Never invent counts, times or causes. The data has no measure "
    "of worker activity, so never write about idle workers, labor or staffing."
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
    parts = [VERDICT_TEXT.get(str(r.get("verdict")), "dangerous pass")]
    if r.get("peak_mps") is not None:
        parts.append(f"peak escape speed {num(r['peak_mps'])} m/s")
    if r.get("onset_t") is not None:
        parts.append(f"worker started moving at t={num(r['onset_t'])} s")
    if r.get("margin_sec") is not None:
        parts.append(f"{num(r['margin_sec'])} s before the closest approach" if r.get("margin_reliable") else
                     f"closest-approach time uncertain (VLM views disagree by {num(r.get('closest_spread_sec'))} s)")
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
           "min": "min of recorded video", "segments": "5 s segments analysed", "metric": "Metric",
           "value": "Value", "key": "Key metrics", "cams": "Robot fleet (w017)", "alerts": "Safety alerts",
           "flags": "Efficiency & congestion flags", "recs": "Recommended actions", "none_alerts": "No safety alerts in scope.",
           "none_flags": "No efficiency flags in scope.", "none_recs": "No recommendations in scope.",
           "agv_moving": "AGV moving (share of AGV-time)",
           "reaction": "Worker escape (danger · peak speed · margin to closest approach)",
           "v_contact": "contact", "v_forced_evasion": "forced to run", "v_short_margin": "margin too short",
           "v_close_pass": "close pass", "uncertain": "uncertain",
           "machines": "Machines moving (share of machine-time)", "n_alerts": "Safety alerts", "n_flags": "Efficiency flags",
           "camera": "Camera", "view": "View", "stationary": "Machines standing still (avg)",
           "moving": "Machines moving", "time": "Scene time", "where": "Scenario", "type": "Type",
           "severity": "Severity", "conf": "Confidence", "verdict": "Danger", "impact": "Impact",
           "ai_note": "Narrative by the text LLM; every table is computed directly from the analyzer data.",
           "tmpl_note": "Report computed directly from the analyzer data (no language model).",
           "s_summary": "Executive summary", "s_safety": "Safety", "s_prod": "Fleet efficiency",
           "s_actions": "Actions for next shift", "limits": "Limitations",
           "site_w017": "Warehouse 017 · robot floor", "site_run": "Forklift safety scenario · run {n}",
           "view_floor": "floor", "view_lane": "lane",
           "type_near_miss": "near-miss", "type_collision": "collision", "type_person_in_path": "person in path",
           "sev_high": "high", "sev_medium": "medium", "sev_low": "low",
           "ftype_machine_surplus": "under-used machines", "ftype_congestion": "congestion",
           "ftype_underused_zone": "rarely used zone",
           "limit_lines": [
               "Offline batch analysis of {min} minutes of recorded video (3 w017 cameras × 5 min, 3 forklift runs × "
               "10 views × 10 s); this is not a live stream.",
               "People counts and the heatmap use YOLO's \"person\" class, which also counts humanoid robots.",
               "Machine counts and whether a machine is moving come from Cosmos3-Reason descriptions of each 5 s segment "
               "(model estimates).",
               "Escape speed converts pixels to metres using the worker's box height (≈ 1.7 m), so it is approximate.",
               "Closest approach is a VLM estimate; when views disagree by more than 1 s the margin is marked uncertain.",
               "Only 3 forklift runs were analysed, so the safety numbers are examples, not shift statistics.",
           ]},
    "zh": {"report": "班次报告", "all": "全部站点", "scope": "范围", "views": "个摄像头视角",
           "min": "分钟录制视频", "segments": "个 5 秒片段已分析", "metric": "指标",
           "value": "数值", "key": "关键指标", "cams": "机器人车队（w017）", "alerts": "安全告警",
           "flags": "效率与拥堵标记", "recs": "建议措施", "none_alerts": "范围内无安全告警。",
           "none_flags": "范围内无效率标记。", "none_recs": "范围内无建议。",
           "agv_moving": "AGV 运行占比（按 AGV 时间）",
           "reaction": "工人躲避（危险类型 · 逃离速度 · 距最接近时刻余量）",
           "v_contact": "发生接触", "v_forced_evasion": "被迫奔跑躲避", "v_short_margin": "反应余量不足",
           "v_close_pass": "近距离擦过", "uncertain": "不确定",
           "machines": "设备运行占比（按设备时间）", "n_alerts": "安全告警", "n_flags": "效率标记",
           "camera": "摄像头", "view": "视角", "stationary": "静止设备（平均）",
           "moving": "设备运行", "time": "场景时间", "where": "场景", "type": "类型",
           "severity": "严重度", "conf": "置信度", "verdict": "危险类型", "impact": "预期效果",
           "ai_note": "叙述由文本大模型生成；所有表格直接由分析数据计算。",
           "tmpl_note": "报告直接由分析数据计算（未使用语言模型）。",
           "s_summary": "执行摘要", "s_safety": "安全", "s_prod": "车队效率", "s_actions": "下一班次行动",
           "limits": "局限性",
           "site_w017": "w017 仓库 · 机器人作业区", "site_run": "叉车安全场景 · 第 {n} 次",
           "view_floor": "地面", "view_lane": "通道",
           "type_near_miss": "险情（未遂）", "type_collision": "碰撞", "type_person_in_path": "人员闯入行驶路径",
           "sev_high": "高", "sev_medium": "中", "sev_low": "低",
           "ftype_machine_surplus": "设备低利用", "ftype_congestion": "拥堵", "ftype_underused_zone": "区域利用不足",
           "limit_lines": [
               "离线批量分析：共 {min} 分钟录制视频（w017 三个摄像头各 5 分钟；3 次叉车场景，各 10 个视角 × 10 秒），不是实时视频流。",
               "人数和热力图来自 YOLO 的「person」类，人形机器人也会被算进去。",
               "设备数量和是否在运行来自 Cosmos3-Reason 对每个 5 秒片段的描述，属于模型估计。",
               "逃离速度按人体框高度约 1.7 米把像素换算成米，是近似值。",
               "最接近时刻是 VLM 的估计；各视角相差超过 1 秒时，反应余量标为「不确定」。",
               "只分析了 3 次叉车场景，安全数字是案例，不是全班次统计。",
           ]},
}
ROWS = {"en": ("far row", "middle row", "near row"), "zh": ("远排", "中排", "近排")}


def site_name(sid: str, L: dict) -> str:
    m = re.fullmatch(r"w3_run(\d+)", sid or "")
    return L["site_run"].format(n=m.group(1)) if m else L.get(f"site_{sid}", sid)


def flag_text(f: dict, L: dict, lang: str) -> str:
    if lang != "zh":
        return short(f.get("message"), 220)
    m = f.get("metric") or {}
    ratio = "ratio" in str(m.get("name"))
    v, th = (pct(m.get("value")), pct(m.get("threshold"))) if ratio else (num(m.get("value")), num(m.get("threshold")))
    zone = f.get("zone")
    where = f"{ROWS['zh'][zone[1]]}第 {zone[0] + 1} 格" if isinstance(zone, list) and len(zone) >= 2 and zone[1] < 3 else ""
    if f.get("type") == "machine_surplus":
        n = re.search(r"([\d.]+) machines in view", f.get("message") or "")
        return f"平均 {n.group(1) if n else '-'} 台设备在画面内，只有 {v} 在运行（阈值 {th}）"
    if f.get("type") == "congestion":
        return f"{where}同时最多 {v} 人（阈值 {th}）"
    if f.get("type") == "underused_zone":
        return f"{where}平均只有 {v} 人（阈值 {th}）"
    return short(f.get("message"), 220)


def report_parts(snap: Snapshot, site_id: str | None, camera: str | None, lang: str) -> dict[str, str]:
    lang = "zh" if lang == "zh" else "en"
    L = LABELS[lang]
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
    agg = _cam_totals(floor or util)
    segs = [s for s in snap.segments if s.get("site_id") in site_ids and (not camera or s.get("camera") == camera)]
    video_min = sum(num(s.get("duration_sec")) * (1 if camera else len(dicts(s.get("cameras"))))
                    for s in snap.sites if s.get("site_id") in site_ids) / 60

    title = L["all"] if all_sites else site_name(site_id, L)
    title = f"{L['report']} — {title}" + (f" · {camera}" if camera else "")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meta = f"{L['scope']}: {len(util)} {L['views']} · {video_min:.1f} {L['min']} · {len(segs)} {L['segments']} · {generated}"

    sev = {s: sum(1 for e in events if e.get("severity") == s) for s in ("high", "medium", "low")}
    flag_types: dict[str, int] = {}
    for f in flags:
        flag_types[str(f.get("type"))] = flag_types.get(str(f.get("type")), 0) + 1
    reactions = [e for e in events if e.get("reaction")]
    kpi = [f"| {L['metric']} | {L['value']} |", "|---|---|",
           f"| {L['n_alerts']} | " + " · ".join(f"{L['sev_' + s]} {n}" for s, n in sev.items()) + " |"]

    def reaction_cell(r: dict) -> str:
        margin = "" if r.get("margin_sec") is None else (
            f" · {num(r['margin_sec'])} s" if r.get("margin_reliable") else f" · ≈{num(r['margin_sec'])} s ({L['uncertain']})")
        return f"{L.get('v_' + str(r.get('verdict')), r.get('verdict'))} · {num(r.get('peak_mps'))} m/s{margin}"

    if reactions:
        kpi.append(f"| {L['reaction']} | " + "; ".join(f"{site_name(str(e.get('site_id')), L)}: {reaction_cell(e['reaction'])}"
                                                      for e in reactions) + " |")
    if floor:
        kpi += [f"| {L['machines']} | {pct(agg['machine_moving_ratio'])} |",
                f"| {L['agv_moving']} | {pct(agg['agv_moving_ratio'])} |"]
    kpi.append(f"| {L['n_flags']} | {len(flags)}" + (" (" + ", ".join(f"{L.get('ftype_' + k, k)} {v}" for k, v in flag_types.items())
                                                    + ")" if flags else "") + " |")

    cam_rows = [f"| {L['camera']} | {L['view']} | {L['moving']} | {L['agv_moving']} | {L['stationary']} |",
                "|---|---|---|---|---|"]
    for c in floor:
        t, agv = c.get("totals") or {}, _fleet_type(c, "agv")
        stationary = sum(num(d.get("stationary_avg")) for d in ((c.get("fleet") or {}).get("types") or {}).values())
        cam_rows.append(f"| {c.get('camera')} | {L.get('view_' + str(c.get('view')), c.get('view'))} | "
                        f"{pct(t.get('machine_moving_ratio'))} | {pct(agv.get('moving_ratio'))} | {round(stationary, 2)} |")

    alert_rows = [f"| {L['time']} | {L['where']} | {L['type']} | {L['severity']} | {L['conf']} | {L['verdict']} |",
                  "|---|---|---|---|---|---|"]
    alert_rows += [f"| {fmt_t(e.get('scene_t'))} | {site_name(str(e.get('site_id')), L)} · {e.get('camera')} | "
                   f"{L.get('type_' + str(e.get('type')), e.get('type'))} | {L.get('sev_' + str(e.get('severity')), e.get('severity'))} | "
                   f"{pct(e.get('confidence'))} | {L.get('v_' + str((e.get('reaction') or {}).get('verdict')), '-')} |"
                   for e in events]
    flag_items = [f"- **{L.get('ftype_' + str(f.get('type')), f.get('type'))}** · {f.get('camera')} · "
                  f"{fmt_t(f.get('scene_t0'))}–{fmt_t(f.get('scene_t1'))} — {flag_text(f, L, lang)}" for f in flags]
    zh = lang == "zh"
    rec_items = [f"{i}. **{short(r.get('title_zh') if zh and r.get('title_zh') else r.get('title'), 140)}** — "
                 f"{short(r.get('action_zh') if zh and r.get('action_zh') else r.get('action'), 260)}"
                 + (f" _{L['impact']}: {short(r.get('impact_zh') if zh and r.get('impact_zh') else r.get('expected_impact'), 140)}_"
                    if r.get("expected_impact") else "") for i, r in enumerate(recs, 1)]
    limits = [f"- {line.format(min=f'{video_min:.0f}')}" for line in L["limit_lines"]]
    return {
        "title": title, "meta": meta, "L": L,
        "kpi": "\n".join(kpi), "cameras": "\n".join(cam_rows) if floor else "",
        "alerts": "\n".join(alert_rows) if events else L["none_alerts"],
        "flags": "\n".join(flag_items) if flags else L["none_flags"],
        "recs": "\n".join(rec_items) if recs else L["none_recs"],
        "limits": "\n".join(limits),
    }


def _tables(p: dict, with_recs: bool) -> str:
    L = p["L"]
    out = f"## {L['key']}\n{p['kpi']}\n\n" + (f"## {L['cams']}\n{p['cameras']}\n\n" if p["cameras"] else "")
    out += f"## {L['alerts']}\n{p['alerts']}\n\n## {L['flags']}\n{p['flags']}\n"
    out += f"\n## {L['recs']}\n{p['recs']}\n" if with_recs else ""
    return out + f"\n## {L['limits']}\n{p['limits']}\n"


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
                  f"## {L['s_prod']}\n2-4 bullets on fleet efficiency: AGV/AMR/humanoid moving shares, "
                  f"machines standing still, congestion and underused zones.\n"
                  f"## {L['s_actions']}\n3-5 numbered actions, each tied to a specific alert or flag in DATA.\n"
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
            return self._fallback_report(snap, site_id, camera, lang)
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
        return {**result, "cached": False} if result else self._fallback_report(snap, site_id, camera, lang)

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

    def _fallback_report(self, snap: Snapshot, site_id: str | None, camera: str | None, lang: str) -> dict:
        return {"markdown": template_report(report_parts(snap, site_id, camera, lang)), "engine": "template",
                "cached": False}

    def warm_reports(self, snap: Snapshot) -> None:
        """Pre-generate site-level reports so the demo never waits on the first click."""
        if not self._llm_ready():
            return
        for site_id in [None] + [str(s.get("site_id")) for s in snap.sites]:
            self.report(snap, site_id, None, "ai", "en", timeout=REPORT_LLM_TIMEOUT * 2)
