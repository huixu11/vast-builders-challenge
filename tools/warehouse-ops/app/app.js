"use strict";
/* Warehouse Ops Copilot — single-page app. Vanilla JS, no build step, no external resources.
   Every URL is relative (no leading slash) because production serves the app under /app. */
(() => {
  // ===================================================================== i18n
  const I18N = {
    en: {
      tagline: "Video-grounded safety & efficiency · NVIDIA VSS on VAST",
      nav_overview: "Overview", nav_alerts: "Safety alerts", nav_resources: "Resources & bottlenecks",
      nav_replay: "Multi-camera replay", nav_ask: "Ask", nav_report: "Shift report",
      live: "LIVE", data_real: "Analyzer data", data_mock: "Mock data", vss: "VSS", cosmos: "LLM",
      loading: "Loading warehouse data…", retry: "Retry", error_load: "Could not load data from the backend.",
      timeout: "Request timed out", updated: "New analyzer results loaded", refresh_view: "Refresh view",
      kpi_people: "People on floor now", kpi_people_sub: "avg {avg} · {n} floor cameras · window ending {t}",
      kpi_idle: "Idle labor", kpi_idle_sub: "{m} idle person-minutes in the window",
      kpi_machines: "Machines moving now", kpi_machines_sub: "{p} of machine-time moving",
      kpi_alerts: "Open safety alerts", kpi_flags: "Operational flags", kpi_flags_sub: "bottlenecks · surplus · congestion",
      kpi_footage: "Camera views analysed", kpi_footage_sub: "{m} min of video · {n} segments",
      cam_status: "Camera status", open_wall: "Open video wall", alert_feed: "Live alert feed",
      top_flags: "Top operational flags", top_recs: "Recommended actions", view_all: "View all",
      people: "people", idle: "idle", machines: "machines", avg: "avg", moving: "moving",
      status_ok: "Normal", status_warn: "Watch", status_alert: "Alert", scenario: "scenario",
      scenario_views: "{n} synchronized views", no_alerts_site: "No alerts", new: "NEW",
      sev_high: "High", sev_medium: "Medium", sev_low: "Low",
      type_collision: "Collision", type_near_miss: "Near-miss", type_person_in_path: "Person in path",
      type_robot_proximity: "Robot proximity", type_fall: "Fall", type_blocked_aisle: "Blocked aisle",
      ftype_labor_surplus: "Labor surplus", ftype_machine_surplus: "Idle machines", ftype_congestion: "Congestion",
      ftype_underused_zone: "Underused zone", ftype_bottleneck: "Bottleneck",
      view_floor: "floor", view_lane: "lane", view_ceiling: "ceiling", view_eye: "eye-level",
      all_types: "All types", all_sites: "All sites", show_acked: "Show acknowledged",
      ack: "Acknowledge", acked: "Acknowledged", alerts_empty: "No alerts match these filters.",
      alerts_none: "No safety alerts in the analyzed footage.", select_alert: "Select an alert to review it.",
      scene_time: "scene", seg_time: "segment t", confidence: "confidence",
      jump_event: "Jump to event", boxes: "Detections", legend_person: "person", legend_machine: "machine / vehicle",
      views_title: "Camera views", evidence: "Evidence", ev_vlm: "Vision-language model (Cosmos3-Reason)",
      ev_kin: "Kinematics (YOLO tracks)", ev_cons: "Consensus",
      cmp_title: "Why this alert is more accurate", cmp_old: "Stock pipeline caption",
      cmp_old_foot: "Caption-only pipeline: no alert, no severity, no timestamp",
      cmp_new: "Warehouse Ops Copilot", cmp_new_foot: "Multi-view VLM verdict cross-checked with motion tracking",
      no_caption: "(no caption stored for this segment)", no_value: "—",
      open_replay: "Multi-camera replay", ask_about: "Ask Copilot about this",
      ask_about_q: "What happened in {id} and what should we change to prevent it?",
      clip_error: "Clip unavailable right now", primary: "primary",
      site: "Site", camera: "Camera", people_time: "People over time", machines_time: "Machines over time",
      s_people: "people", s_idle: "idle", s_moving: "moving", s_m_total: "machines in view", s_m_moving: "machines moving",
      idle_by_cam: "Idle ratio by camera", util_by_cam: "Machine utilization by camera",
      heatmap: "Zone heatmap", occupancy: "Occupancy", idle_layer: "Idle", window_avg: "window average",
      flags: "Operational flags", recs: "Recommendations", rationale: "Why", impact: "Expected impact",
      threshold: "threshold", no_flags: "No operational flags for this site.", no_recs: "No recommendations yet.",
      no_util: "No utilization data yet — the analyzer is still running.",
      seg_detail: "Moment {t}", vlm_summary: "VLM summary", pipeline_caption: "Pipeline caption",
      congestion: "congestion", seg_hint: "Click a chart to inspect a 5-second window.",
      chart_hint: "Click the chart to inspect a moment · shaded bands are flags · red ticks are safety alerts",
      eye_views: "Eye-level views", speed: "Speed", buffering: "Buffering…", sync_note: "All views share one clock",
      events_title: "Events at this site", replay_hint: "Click a tile to enlarge it", no_videos: "No videos indexed yet.",
      ask_title: "Ask the warehouse", ask_ph: "Ask about safety, idle labor, machines, bottlenecks…", send: "Send",
      suggested: "Suggested questions", think1: "Searching the video archive…", think2: "Grounding on analyzer facts…",
      think3: "Reasoning with the language model…",
      engine_llm: "Language model · grounded on analyzer facts + video search",
      engine_cosmos: "Language model · grounded on analyzer facts + video search",
      engine_vss_search: "VSS search synthesis", engine_vss_agent: "VSS agent", engine_rules: "Offline answer from analyzer data",
      clips: "Matching clips", cited: "Cited", ask_error: "The copilot could not answer right now.",
      how_title: "How answers are grounded",
      how_1: "Facts: safety alerts, flags, per-camera metrics and recommendations from the analyzer.",
      how_2: "Video search: VSS hybrid search over both locations finds matching clips.",
      how_3: "The language model answers using only those facts and clips and cites their ids.",
      ask_welcome: "Ask anything about safety, labor and machines in the analyzed footage. Answers cite the alerts, flags and clips they rely on.",
      q1: "Which camera has the most idle workers?", q2: "Show forklift near-misses", q3: "Where should I move idle workers?",
      q4: "Was anyone hit by a forklift?", q5: "Are AGVs or robots sitting idle anywhere?",
      report_scope: "Report scope", all_cams: "All cameras", gen_ai: "Generate with AI", metrics_only: "Metrics only",
      copy: "Copy", download: "Download .md", print: "Print", writing: "The language model is writing the narrative…",
      verified: "{n} numbers in the narrative checked against analyzer data",
      unverified: "{n} numbers not found in the data: {list}",
      engine_template: "Metrics-only report (deterministic)", engine_analyzer: "Analyzer shift report",
      engine_llm_r: "AI narrative + computed tables",
      engine_cosmos_r: "AI narrative + computed tables", copied: "Copied to clipboard", cached: "cached",
      report_fail: "AI narrative unavailable — showing the metrics-only report.",
    },
    zh: {
      tagline: "基于视频的安全与效率洞察 · NVIDIA VSS on VAST",
      nav_overview: "总览", nav_alerts: "安全告警", nav_resources: "资源与瓶颈",
      nav_replay: "多机位回放", nav_ask: "问答", nav_report: "班次报告",
      live: "实时", data_real: "分析数据", data_mock: "模拟数据", vss: "VSS", cosmos: "LLM",
      loading: "正在加载仓库数据…", retry: "重试", error_load: "无法从后端加载数据。",
      timeout: "请求超时", updated: "已加载新的分析结果", refresh_view: "刷新视图",
      kpi_people: "当前在场人数", kpi_people_sub: "平均 {avg} · {n} 个地面摄像头 · 截至 {t}",
      kpi_idle: "空闲人力", kpi_idle_sub: "窗口内空闲 {m} 人·分钟",
      kpi_machines: "当前运行设备", kpi_machines_sub: "设备时间中 {p} 处于运行",
      kpi_alerts: "未处理安全告警", kpi_flags: "运营标记", kpi_flags_sub: "瓶颈 · 冗余 · 拥堵",
      kpi_footage: "已分析摄像头视角", kpi_footage_sub: "{m} 分钟视频 · {n} 个片段",
      cam_status: "摄像头状态", open_wall: "打开视频墙", alert_feed: "实时告警流",
      top_flags: "主要运营标记", top_recs: "建议措施", view_all: "查看全部",
      people: "人", idle: "空闲", machines: "设备", avg: "平均", moving: "移动",
      status_ok: "正常", status_warn: "关注", status_alert: "告警", scenario: "场景",
      scenario_views: "{n} 个同步视角", no_alerts_site: "无告警", new: "新",
      sev_high: "高", sev_medium: "中", sev_low: "低",
      type_collision: "碰撞", type_near_miss: "险情（未遂）", type_person_in_path: "人员闯入行驶路径",
      type_robot_proximity: "机器人近距离", type_fall: "跌倒", type_blocked_aisle: "通道堵塞",
      ftype_labor_surplus: "人力冗余", ftype_machine_surplus: "设备闲置", ftype_congestion: "拥堵",
      ftype_underused_zone: "区域利用不足", ftype_bottleneck: "瓶颈",
      view_floor: "地面", view_lane: "通道", view_ceiling: "顶视", view_eye: "平视",
      all_types: "全部类型", all_sites: "全部站点", show_acked: "显示已确认",
      ack: "确认", acked: "已确认", alerts_empty: "没有符合筛选条件的告警。",
      alerts_none: "分析的视频中没有安全告警。", select_alert: "选择一条告警进行查看。",
      scene_time: "场景", seg_time: "片段内", confidence: "置信度",
      jump_event: "跳到事件", boxes: "检测框", legend_person: "人员", legend_machine: "设备 / 车辆",
      views_title: "摄像头视角", evidence: "证据", ev_vlm: "视觉语言模型（Cosmos3-Reason）",
      ev_kin: "运动学（YOLO 轨迹）", ev_cons: "综合判定",
      cmp_title: "为什么这条告警更准确", cmp_old: "原始流水线描述",
      cmp_old_foot: "仅描述的流水线：无告警、无严重度、无时间戳",
      cmp_new: "Warehouse Ops Copilot", cmp_new_foot: "多视角 VLM 判定 + 运动轨迹交叉验证",
      no_caption: "（该片段无描述）", no_value: "—",
      open_replay: "多机位回放", ask_about: "向 Copilot 提问",
      ask_about_q: "{id} 发生了什么？我们应该如何改进以防止再次发生？",
      clip_error: "视频暂时不可用", primary: "主视角",
      site: "站点", camera: "摄像头", people_time: "人数随时间变化", machines_time: "设备随时间变化",
      s_people: "人数", s_idle: "空闲", s_moving: "移动", s_m_total: "画面内设备", s_m_moving: "运行设备",
      idle_by_cam: "各摄像头空闲比例", util_by_cam: "各摄像头设备利用率",
      heatmap: "区域热力图", occupancy: "占用", idle_layer: "空闲", window_avg: "窗口平均",
      flags: "运营标记", recs: "建议", rationale: "原因", impact: "预期效果",
      threshold: "阈值", no_flags: "该站点无运营标记。", no_recs: "暂无建议。",
      no_util: "暂无利用率数据——分析器仍在运行。",
      seg_detail: "时刻 {t}", vlm_summary: "VLM 摘要", pipeline_caption: "流水线描述",
      congestion: "拥堵", seg_hint: "点击图表查看某个 5 秒窗口。",
      chart_hint: "点击图表查看某一时刻 · 阴影带为运营标记 · 红色刻度为安全告警",
      eye_views: "平视视角", speed: "速度", buffering: "缓冲中…", sync_note: "所有视角共享同一时钟",
      events_title: "该站点的事件", replay_hint: "点击画面可放大", no_videos: "尚无已索引的视频。",
      ask_title: "向仓库提问", ask_ph: "询问安全、空闲人力、设备、瓶颈…", send: "发送",
      suggested: "推荐问题", think1: "正在检索视频库…", think2: "正在结合分析数据…",       think3: "语言模型推理中…",
      engine_llm: "语言模型 · 基于分析数据与视频检索",
      engine_cosmos: "语言模型 · 基于分析数据与视频检索",
      engine_vss_search: "VSS 检索综合", engine_vss_agent: "VSS 智能体", engine_rules: "基于分析数据的离线回答",
      clips: "相关片段", cited: "引用", ask_error: "Copilot 暂时无法回答。",
      how_title: "回答如何溯源",
      how_1: "事实：来自分析器的安全告警、运营标记、各摄像头指标和建议。",
      how_2: "视频检索：VSS 混合检索覆盖两个地点，找到相关片段。",
      how_3: "语言模型仅依据这些事实和片段作答，并引用其编号。",
      ask_welcome: "可以询问已分析视频中的安全、人力和设备情况。回答会引用所依据的告警、标记和片段。",
      q1: "哪个摄像头的空闲工人最多？", q2: "显示叉车险情", q3: "我应该把空闲工人调到哪里？",
      q4: "有人被叉车撞到吗？", q5: "有没有闲置的 AGV 或机器人？",
      report_scope: "报告范围", all_cams: "全部摄像头", gen_ai: "用 AI 生成", metrics_only: "仅指标",
      copy: "复制", download: "下载 .md", print: "打印", writing: "语言模型正在撰写叙述…",
      verified: "叙述中的 {n} 个数字已与分析数据核对", unverified: "{n} 个数字未在数据中找到：{list}",
      engine_template: "纯指标报告（确定性）", engine_analyzer: "分析器班次报告",
      engine_llm_r: "AI 叙述 + 计算表格",
      engine_cosmos_r: "AI 叙述 + 计算表格", copied: "已复制到剪贴板", cached: "已缓存",
      report_fail: "AI 叙述暂不可用——显示纯指标报告。",
    },
  };

  // ===================================================================== state
  const saved = {
    get(k, d) { try { const v = localStorage.getItem("wops." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("wops." + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  };
  const S = {
    lang: saved.get("lang", "en") === "zh" ? "zh" : "en",
    acked: new Set(saved.get("acked", [])),
    data: null, idx: null, byId: null, version: null, kind: null, newIds: new Set(),
    view: "overview", arg: "", cleanups: [], boxes: true,
    filters: { type: "", site: "", sev: { high: true, medium: true, low: true }, showAcked: true },
    res: { site: null, camera: null, t: null, flag: null, rec: null, layer: "occupancy" },
    replay: { site: null, t: 0, eye: false, boxes: false, rate: 1, focus: -1 },
    chat: [], asking: false,
    report: { site: "all", camera: "", cache: {}, current: null },
    segCache: {},
  };

  // ===================================================================== helpers
  const C = { cyan: "#22d3ee", orange: "#fb923c", amber: "#fbbf24", red: "#f43f5e", green: "#34d399",
    blue: "#60a5fa", violet: "#a78bfa", slate: "#64748b" };
  const SEV_COLOR = { high: C.red, medium: C.amber, low: C.blue };
  const FLAG_COLOR = { labor_surplus: C.amber, machine_surplus: C.orange, congestion: C.red, underused_zone: C.blue, bottleneck: C.violet };
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const enc = encodeURIComponent;
  const num = (x, d = 0) => { const v = typeof x === "number" ? x : parseFloat(x); return Number.isFinite(v) ? v : d; };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const fmtT = (sec) => {
    const tenths = Math.round(Math.max(0, num(sec)) * 10);
    const whole = Math.floor(tenths / 10), frac = tenths % 10;
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}${frac ? "." + frac : ""}`;
  };
  const pct = (x) => `${Math.round(num(x) * 100)}%`;
  const fmtNum = (x, digits = 1) => { const v = num(x); return Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : v.toFixed(digits); };
  const fmtScalar = (x) => (typeof x === "boolean" ? (x ? "yes" : "no") : typeof x === "number" ? String(+x.toFixed(3)) : String(x));
  const tr = (key, vars) => {
    let s = I18N[S.lang][key] ?? I18N.en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
    return s;
  };
  const humanize = (s) => String(s ?? "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const label = (prefix, key) => I18N[S.lang][prefix + key] ?? I18N.en[prefix + key] ?? humanize(key);
  const typeLabel = (type) => label("type_", type);
  const flagLabel = (type) => label("ftype_", type);
  const viewLabel = (v) => (v ? label("view_", v) : "");
  const sevLabel = (s) => label("sev_", s);
  const clipUrl = (src) => "api/clip?source=" + enc(src);
  const siteKind = (s) => s?.kind || (num(s?.duration_sec, 999) <= 60 ? "scenario" : "continuous");
  const siteTitle = (id) => S.idx?.site[id]?.title || id || "";
  const flagStrength = (f) => { const m = f.metric || {}; const th = num(m.threshold); return th ? Math.abs(num(m.value) - th) / Math.abs(th) : 0; };

  const icon = (body) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
  const ICON = {
    shield: icon('<path d="M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6z"/><path d="M12 8v5M12 16v.5"/>'),
    bars: icon('<path d="M4 20V11M10 20V5M16 20v-6M21 20H3"/>'),
    grid: icon('<rect x="3" y="4" width="8" height="7" rx="1.5"/><rect x="13" y="4" width="8" height="7" rx="1.5"/><rect x="3" y="13" width="8" height="7" rx="1.5"/><rect x="13" y="13" width="8" height="7" rx="1.5"/>'),
    chat: icon('<path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8M8 13h5"/>'),
    doc: icon('<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 12h7M9 16h7"/>'),
    users: icon('<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.6-3.6 3-5.5 6-5.5s5.4 1.9 6 5.5"/><circle cx="17" cy="9" r="2.6"/><path d="M16 14.6c2.6.2 4.4 2 5 5.4"/>'),
    clock: icon('<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>'),
    machine: icon('<path d="M3 17V9h7l3 4h3v4"/><path d="M16 17V4M16 15h5"/><circle cx="6.5" cy="18" r="2"/><circle cx="13" cy="18" r="2"/>'),
    alert: icon('<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.2v.3"/>'),
    flag: icon('<path d="M5 21V4h11l-2.5 4L16 12H5"/>'),
    camera: icon('<rect x="2.5" y="6.5" width="13" height="11" rx="2"/><path d="m15.5 11 6-3.2v8.4l-6-3.2"/>'),
    play: icon('<path d="M7 4.5v15l12.5-7.5z" fill="currentColor" stroke="none"/>'),
    pause: icon('<path d="M6.5 4.5h4v15h-4zM13.5 4.5h4v15h-4z" fill="currentColor" stroke="none"/>'),
    check: icon('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
    spark: icon('<path d="M12 3l1.9 5.6 5.6 1.9-5.6 1.9L12 18l-1.9-5.6-5.6-1.9 5.6-1.9z"/><path d="M19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>'),
    target: icon('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>'),
    expand: icon('<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>'),
    send: icon('<path d="M3.5 11.5 21 3.5l-7.5 17-2.2-6.8z"/><path d="M11.3 13.7 21 3.5"/>'),
    copy: icon('<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V4H3.5v12h5"/>'),
    download: icon('<path d="M12 4v11m-5-5 5 5 5-5M5 20h14"/>'),
    print: icon('<path d="M7 9V3.5h10V9M7 17H4v-7.5h16V17h-3"/><path d="M7 14h10v6.5H7z"/>'),
    chart: icon('<path d="M3 17l5-6 4 3 4-7 5 5"/><path d="M3 21h18"/>'),
    burst: icon('<path d="M12 2.5l2 5.5 5.5-2-3 5 4.5 3.5-5.8.6.8 5.9-4-4.3-4 4.3.8-5.9L3 14.5 7.5 11l-3-5 5.5 2z"/>'),
    walker: icon('<circle cx="13" cy="4.5" r="2"/><path d="M10 21l2.5-6.5L15 17v4M12.5 14.5l-1-5.5 4 2.5 2.5-.5M11.5 9l-3.5 2-1 3.5"/>'),
    robot: icon('<rect x="4.5" y="8" width="15" height="11" rx="2.5"/><path d="M12 4v4M9 13h.01M15 13h.01M9 16.5h6"/>'),
    fall: icon('<circle cx="17" cy="5" r="2"/><path d="M3 20h18M6 16l5-3 3 2 4-5"/>'),
    block: icon('<circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/>'),
  };
  const TYPE_ICON = { collision: ICON.burst, near_miss: ICON.alert, person_in_path: ICON.walker,
    robot_proximity: ICON.robot, fall: ICON.fall, blocked_aisle: ICON.block };
  const typeIcon = (type) => TYPE_ICON[type] || ICON.alert;

  async function api(path, { method = "GET", body, timeout = 20000 } = {}) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeout);
    try {
      const res = await fetch(path, { method, signal: ctl.signal, cache: "no-store",
        headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON body */ }
      if (!res.ok) throw new Error(data?.error || (typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`));
      return data;
    } catch (e) {
      throw e.name === "AbortError" ? new Error(tr("timeout")) : e;
    } finally {
      clearTimeout(timer);
    }
  }

  function onCleanup(fn) { S.cleanups.push(fn); }
  function runCleanups() { for (const fn of S.cleanups.splice(0)) { try { fn(); } catch { /* best effort */ } } }
  function stopVideo(v) { try { v.pause(); v.removeAttribute("src"); v.load(); } catch { /* detached */ } }

  let toastTimer = 0;
  function toast(msg, action) {
    const el = $("#toast");
    el.innerHTML = `<span>${esc(msg)}</span>${action ? `<button type="button" class="btn sm">${esc(action.label)}</button>` : ""}`;
    el.hidden = false;
    requestAnimationFrame(() => el.classList.add("show"));
    const hide = () => { el.classList.remove("show"); setTimeout(() => { el.hidden = true; }, 250); };
    if (action) $("button", el).onclick = () => { hide(); action.run(); };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hide, action ? 9000 : 3200);
  }

  const emptyState = (ico, text) => `<div class="empty">${ico}<p>${esc(text)}</p></div>`;
  const loadingHtml = () => `<div class="loading-screen"><div class="spinner big"></div><p>${esc(tr("loading"))}</p></div>`;

  // ===================================================================== data + index
  function buildIndex(videos) {
    const idx = { sites: [], site: {}, cams: {}, chunkByVideo: {}, segBySource: {} };
    for (const raw of videos?.sites || []) {
      const site = { ...raw, cameras: raw.cameras || [] };
      idx.sites.push(site);
      idx.site[site.site_id] = site;
      for (const cam of site.cameras) {
        const chunks = [];
        for (const ch of cam.chunks || []) {
          const c = { ...ch, site_id: site.site_id, camera: cam.camera, view: cam.view, scene_t0: num(ch.scene_t0), scene_t1: num(ch.scene_t1) };
          chunks.push(c);
          if (c.original_video) idx.chunkByVideo[c.original_video] = c;
          for (const sg of ch.segments || []) {
            if (sg.source) idx.segBySource[sg.source] = { ...sg, scene_t0: num(sg.scene_t0), scene_t1: num(sg.scene_t1), chunk: c };
          }
        }
        chunks.sort((a, b) => a.scene_t0 - b.scene_t0);
        idx.cams[site.site_id + "|" + cam.camera] = { ...cam, site_id: site.site_id, chunks };
      }
    }
    idx.sites.sort((a, b) => (siteKind(a) === "continuous" ? 0 : 1) - (siteKind(b) === "continuous" ? 0 : 1));
    return idx;
  }

  function chunkAt(siteId, camera, sceneT) {
    const chunks = S.idx.cams[siteId + "|" + camera]?.chunks || [];
    if (!chunks.length) return null;
    return chunks.find((c) => sceneT >= c.scene_t0 && sceneT < c.scene_t1) || (sceneT >= chunks.at(-1).scene_t1 ? chunks.at(-1) : chunks[0]);
  }

  // A stored segment URI plays from its parent chunk (more context, smoother seeking) when known.
  function playTarget(source, tInSeg) {
    const seg = S.idx.segBySource[source];
    if (seg?.chunk?.original_video) return { src: seg.chunk.original_video, t: seg.scene_t0 + tInSeg - seg.chunk.scene_t0, chunk: seg.chunk };
    const chunk = S.idx.chunkByVideo[source];
    return { src: source, t: tInSeg, chunk: chunk || null };
  }

  function camOrder(site) {
    const rank = (c) => ({ ceiling: 0, eye: 1 })[c.view] ?? 0;
    return (site?.cameras || []).map((c) => S.idx.cams[site.site_id + "|" + c.camera] || c)
      .sort((a, b) => rank(a) - rank(b) || String(a.camera).localeCompare(String(b.camera)));
  }

  async function loadAll() {
    const [overview, videos, events, util, recs] = await Promise.all([
      api("api/overview"), api("api/videos"), api("api/events"), api("api/utilization"), api("api/recommendations")]);
    S.data = { overview: overview || {}, events: Array.isArray(events) ? events : [],
      util: { cameras: util?.cameras || [], flags: util?.flags || [] }, recs: recs || {} };
    S.idx = buildIndex(videos);
    S.byId = {
      event: Object.fromEntries(S.data.events.map((e) => [e.event_id, e])),
      flag: Object.fromEntries(S.data.util.flags.map((f) => [f.flag_id, f])),
      rec: Object.fromEntries((S.data.recs.recommendations || []).map((r) => [r.rec_id, r])),
    };
    S.version = overview?.version || videos?.version;
    S.kind = overview?.data_dir_kind || videos?.data_dir_kind;
    S.segCache = {};
    const seen = new Set(saved.get("seen", []));
    const ids = S.data.events.map((e) => e.event_id);
    S.newIds = new Set(seen.size ? ids.filter((id) => !seen.has(id)) : []);
    saved.set("seen", [...new Set([...seen, ...ids])].slice(-500));
    updateHeader();
  }

  function loadSegments(siteId, camera) {
    const key = siteId + "|" + camera;
    if (!S.segCache[key]) {
      S.segCache[key] = api(`api/segments?site_id=${enc(siteId)}&camera=${enc(camera)}`)
        .then((rows) => (rows || []).sort((a, b) => num(a.scene_t0) - num(b.scene_t0)))
        .catch(() => { delete S.segCache[key]; return []; });
    }
    return S.segCache[key];
  }

  // ===================================================================== header
  function updateHeader() {
    const pill = $("#dataPill");
    pill.className = "pill " + (S.kind === "real" ? "ok" : "warn");
    pill.textContent = S.kind === "real" ? tr("data_real") : tr("data_mock");
    pill.title = `data version ${S.version || "?"}`;
    const open = (S.data?.events || []).filter((e) => !S.acked.has(e.event_id)).length;
    const badge = $("#alertBadge");
    badge.hidden = !open;
    badge.textContent = open;
  }

  function setConn(h) {
    const vssOk = !!(h?.vss?.chunks > 0);
    const v = $("#vssPill"), c = $("#cosmosPill");
    v.classList.toggle("ok", vssOk); v.classList.toggle("bad", !vssOk);
    v.title = vssOk ? `${h.vss.chunks} chunks in the live VSS inventory` : "VSS unreachable — using stored URIs";
    const llmOk = !!(h?.llm?.available || h?.cosmos);
    c.classList.toggle("ok", llmOk); c.classList.toggle("bad", !llmOk);
    c.title = llmOk ? (h?.llm?.model || h?.llm?.kind || "text LLM available") : "Language model unavailable — fallbacks active";
  }

  function applyStatic() {
    document.documentElement.lang = S.lang === "zh" ? "zh-CN" : "en";
    $$("[data-i18n]").forEach((el) => { el.textContent = tr(el.dataset.i18n); });
    $$(".lang button").forEach((b) => b.classList.toggle("on", b.dataset.lang === S.lang));
    if (S.data) updateHeader();
  }

  // ===================================================================== charts
  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
  }
  const niceStep = (span) => [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((s) => span / s <= 8) || 600;

  function sparkline(series, { w = 240, h = 44, max } = {}) {
    const all = series.flatMap((s) => s.values || []).map((v) => num(v));
    if (!all.length) return `<svg class="spark" viewBox="0 0 ${w} ${h}"></svg>`;
    const top = max ?? Math.max(1e-6, ...all);
    const n = Math.max(...series.map((s) => (s.values || []).length));
    const x = (i) => (n <= 1 ? w / 2 : (i / (n - 1)) * (w - 2) + 1);
    const y = (v) => h - 2 - (num(v) / top) * (h - 6);
    const body = series.map((s) => {
      const pts = (s.values || []).map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
      if (!pts.length) return "";
      const area = s.fill ? `<polygon points="${x(0).toFixed(1)},${h} ${pts.join(" ")} ${x(pts.length - 1).toFixed(1)},${h}" fill="${s.color}" opacity=".15"/>` : "";
      return `${area}<polyline points="${pts.join(" ")}" fill="none" stroke="${s.color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`;
    }).join("");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${body}</svg>`;
  }

  function lineChart(o) {
    const W = o.width || 760, H = o.height || 210, P = { l: 38, r: 12, t: 14, b: 24 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const t0 = o.t0, t1 = Math.max(o.t1, o.t0 + 1e-3);
    const yMax = niceMax(Math.max(1, ...o.series.flatMap((s) => s.points.map((p) => p.v))));
    const x = (t) => P.l + ((t - t0) / (t1 - t0)) * iw;
    const y = (v) => P.t + ih - (v / yMax) * ih;
    let axes = "";
    for (let i = 0; i <= 4; i++) {
      const v = (yMax * i) / 4, yy = y(v).toFixed(1);
      axes += `<line class="gl" x1="${P.l}" x2="${W - P.r}" y1="${yy}" y2="${yy}"/><text class="ax" x="${P.l - 6}" y="${+yy + 3}" text-anchor="end">${fmtNum(v)}</text>`;
    }
    const step = niceStep(t1 - t0);
    for (let tt = Math.ceil(t0 / step - 1e-9) * step; tt <= t1 + 1e-6; tt += step) {
      const xx = x(tt).toFixed(1);
      axes += `<line class="tk" x1="${xx}" x2="${xx}" y1="${P.t + ih}" y2="${P.t + ih + 4}"/><text class="ax" x="${xx}" y="${H - 6}" text-anchor="middle">${fmtT(tt)}</text>`;
    }
    const bands = (o.bands || []).map((b) => {
      const a = x(Math.max(t0, b.t0)), z = x(Math.min(t1, b.t1));
      return `<rect class="band${b.sel ? " sel" : ""}" data-flag="${esc(b.id)}" x="${a.toFixed(1)}" y="${P.t}" width="${Math.max(4, z - a).toFixed(1)}" height="${ih}" fill="${b.color}"><title>${esc(b.label)}</title></rect>`;
    }).join("");
    const lines = o.series.map((s) => {
      if (!s.points.length) return "";
      const pts = s.points.map((p) => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
      const area = s.area ? `<polygon points="${x(s.points[0].t).toFixed(1)},${P.t + ih} ${pts} ${x(s.points.at(-1).t).toFixed(1)},${P.t + ih}" fill="${s.color}" opacity=".16"/>` : "";
      return `${area}<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"${s.dash ? ' stroke-dasharray="5 4"' : ""}/>`;
    }).join("");
    const marks = (o.markers || []).map((m) => `<g class="mark" data-event="${esc(m.id)}"><line x1="${x(m.t).toFixed(1)}" x2="${x(m.t).toFixed(1)}" y1="${P.t}" y2="${P.t + ih}" stroke="${m.color}" stroke-width="2"/><circle cx="${x(m.t).toFixed(1)}" cy="${P.t + 5}" r="5.5" fill="${m.color}"/><title>${esc(m.label)}</title></g>`).join("");
    const cursor = o.cursor != null ? `<line class="cursor" x1="${x(o.cursor).toFixed(1)}" x2="${x(o.cursor).toFixed(1)}" y1="${P.t}" y2="${P.t + ih}"/>` : "";
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" data-t0="${t0}" data-t1="${t1}" data-l="${P.l}" data-iw="${iw}" data-w="${W}">${axes}${bands}${lines}${cursor}${marks}<line class="guide" y1="${P.t}" y2="${P.t + ih}" x1="-10" x2="-10"/></svg>`;
  }

  function bindChart(host, { points, tip, onPick }) {
    const svg = $("svg.chart", host);
    if (!svg) return;
    const tipEl = document.createElement("div");
    tipEl.className = "chart-tip";
    tipEl.hidden = true;
    host.appendChild(tipEl);
    const t0 = +svg.dataset.t0, t1 = +svg.dataset.t1, l = +svg.dataset.l, iw = +svg.dataset.iw, W = +svg.dataset.w;
    const guide = $(".guide", svg);
    const timeAt = (ev) => { const r = svg.getBoundingClientRect(); return t0 + ((((ev.clientX - r.left) / r.width) * W - l) / iw) * (t1 - t0); };
    const nearest = (t) => points.reduce((best, p, i) => (Math.abs(p.t - t) < Math.abs(points[best].t - t) ? i : best), 0);
    svg.addEventListener("mousemove", (ev) => {
      if (!points.length) return;
      const t = timeAt(ev);
      if (t < t0 - 1 || t > t1 + 1) { tipEl.hidden = true; return; }
      const p = points[nearest(t)];
      const vx = l + ((p.t - t0) / (t1 - t0)) * iw;
      guide.setAttribute("x1", vx); guide.setAttribute("x2", vx);
      tipEl.innerHTML = tip(p);
      tipEl.hidden = false;
      const hr = host.getBoundingClientRect();
      let left = ev.clientX - hr.left + 14;
      if (left > hr.width - 190) left -= 210;
      tipEl.style.left = left + "px";
      tipEl.style.top = Math.max(0, ev.clientY - hr.top - 12) + "px";
    });
    svg.addEventListener("mouseleave", () => { tipEl.hidden = true; guide.setAttribute("x1", -10); guide.setAttribute("x2", -10); });
    svg.addEventListener("click", (ev) => {
      const mark = ev.target.closest("[data-event]"), band = ev.target.closest("[data-flag]");
      if (mark) { location.hash = "#alerts/" + enc(mark.dataset.event); return; }
      if (band) { onPick?.({ flag: band.dataset.flag }); return; }
      if (points.length) onPick?.({ t: points[nearest(timeAt(ev))].t0 });
    });
  }

  function barList(items, { selected, fmt = pct, max = 1, threshold } = {}) {
    return `<div class="bars">${items.map((it) => `
      <button type="button" class="bar-row${it.key === selected ? " sel" : ""}" data-cam="${esc(it.key)}">
        <span class="bar-label">${esc(it.label)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${clamp((num(it.value) / max) * 100, 0, 100).toFixed(1)}%;background:${it.color}"></span>${threshold != null ? `<span class="bar-th" style="left:${clamp((threshold / max) * 100, 0, 100)}%"></span>` : ""}</span>
        <span class="bar-val mono">${esc(fmt(it.value))}</span>
      </button>`).join("")}</div>`;
  }

  // ===================================================================== evidence renderer (schema-agnostic)
  const isCountMap = (o) => o && typeof o === "object" && !Array.isArray(o) && Object.keys(o).length && Object.values(o).every((x) => typeof x === "number");
  const countChips = (o) => `<div class="chips">${Object.entries(o).map(([k, x]) => `<span class="chip sm">${esc(humanize(k))} <b>${esc(fmtScalar(x))}</b></span>`).join("")}</div>`;

  function renderArray(arr, depth) {
    if (!arr.length) return `<p class="muted">${tr("no_value")}</p>`;
    if (arr.every((x) => typeof x === "number")) {
      if (arr.length >= 4) {
        return `<div class="ev-spark">${sparkline([{ values: arr, color: C.cyan, fill: true }], { w: 220, h: 34 })}<span class="mono muted">${fmtScalar(Math.min(...arr))} – ${fmtScalar(Math.max(...arr))}</span></div>`;
      }
      return `<p class="mono">${arr.map(fmtScalar).join(" – ")}</p>`;
    }
    if (arr.every((x) => x === null || typeof x !== "object")) return `<ul class="ev-list">${arr.map((x) => `<li>${esc(fmtScalar(x))}</li>`).join("")}</ul>`;
    const rows = arr.filter((x) => x && typeof x === "object" && !Array.isArray(x));
    if (depth > 2 || !rows.length) return `<code>${esc(JSON.stringify(arr).slice(0, 300))}</code>`;
    const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))].slice(0, 6);
    const cellOf = (v) => (v === undefined || v === null ? "" : Array.isArray(v) ? v.map(fmtScalar).join("–") : typeof v === "object" ? JSON.stringify(v) : fmtScalar(v));
    return `<table class="mini"><thead><tr>${cols.map((c) => `<th>${esc(humanize(c))}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 12).map((r) => `<tr>${cols.map((c) => `<td class="mono">${esc(cellOf(r[c]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }

  function renderValue(v, depth = 0) {
    if (v === null || v === undefined || v === "") return `<p class="muted">${tr("no_value")}</p>`;
    if (typeof v === "string") return `<p>${esc(v)}</p>`;
    if (typeof v !== "object") return `<p class="mono">${esc(fmtScalar(v))}</p>`;
    if (Array.isArray(v)) return renderArray(v, depth);
    const entries = Object.entries(v).filter(([, x]) => x !== null && x !== undefined && x !== "");
    const isText = (x) => typeof x === "string" && x.length > 48;
    let html = entries.filter(([, x]) => isText(x)).map(([k, x]) => `<div class="ev-text"><span class="k">${esc(humanize(k))}</span><p>${esc(x)}</p></div>`).join("");
    const scalars = entries.filter(([, x]) => typeof x !== "object" && !isText(x));
    if (scalars.length) html += `<dl class="kv">${scalars.map(([k, x]) => `<dt>${esc(humanize(k))}</dt><dd class="mono">${esc(fmtScalar(x))}</dd>`).join("")}</dl>`;
    html += entries.filter(([, x]) => typeof x === "object").map(([k, x]) => `<div class="ev-sub"><span class="k">${esc(humanize(k))}</span>${Array.isArray(x) ? renderArray(x, depth + 1) : isCountMap(x) ? countChips(x) : depth < 2 ? renderValue(x, depth + 1) : `<code>${esc(JSON.stringify(x).slice(0, 300))}</code>`}</div>`).join("");
    return html || `<p class="muted">${tr("no_value")}</p>`;
  }

  // ===================================================================== markdown (escape first, then a small safe subset)
  function md(src, cite) {
    const inline = (s) => {
      let x = esc(s);
      x = x.replace(/`([^`]+)`/g, (m, code) => (cite && cite(code)) || `<code>${code}</code>`);
      x = x.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      x = x.replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
      x = x.replace(/(^|[\s(])_([^_\s][^_]*?)_(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
      if (cite) {
        x = x.replace(/\[([^\]\s][^\]]{0,200})\]/g, (m, inner) => {
          const parts = inner.split(/\s*[,;]\s*/).map((p) => cite(p.trim()));
          return parts.every(Boolean) ? parts.join(" ") : m;
        });
      }
      return x;
    };
    const lines = String(src || "").replace(/\r/g, "").split("\n");
    let html = "", para = [];
    const flush = () => { if (para.length) { html += `<p>${inline(para.join(" "))}</p>`; para = []; } };
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      let m;
      if (!line.trim()) { flush(); i++; continue; }
      if ((m = line.match(/^\s*(#{1,4})\s+(.*)$/))) { flush(); const n = m[1].length; html += `<h${n}>${inline(m[2])}</h${n}>`; i++; continue; }
      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { flush(); html += "<hr>"; i++; continue; }
      if (/^\s*\|.*\|\s*$/.test(line)) {
        flush();
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
        const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const body = rows.filter((r, k) => !(k === 1 && /^\s*\|?[\s:|-]+\|?\s*$/.test(r)));
        const [head, ...rest] = body;
        html += `<div class="table-wrap"><table><thead><tr>${cells(head).map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rest.map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
        continue;
      }
      if (/^\s*[-*•]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        flush();
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const re = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*•]\s+/;
        const items = [];
        while (i < lines.length && re.test(lines[i])) {
          let item = lines[i++].replace(re, "");
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !re.test(lines[i])) item += " " + lines[i++].trim();
          items.push(`<li>${inline(item)}</li>`);
        }
        html += ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`;
        continue;
      }
      if (/^\s*>/.test(line)) {
        flush();
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
        html += `<blockquote>${inline(quote.join(" "))}</blockquote>`;
        continue;
      }
      para.push(line.trim());
      i++;
    }
    flush();
    return html;
  }

  function idChip(id, label) {
    if (S.byId.event[id]) { const e = S.byId.event[id]; return `<a class="cite ev sev-${esc(e.severity)}" href="#alerts/${enc(id)}" title="${esc(e.title || "")}">${ICON.alert}${esc(label || id)}</a>`; }
    if (S.byId.flag[id]) return `<a class="cite fl" href="#resources/${enc(id)}" title="${esc(S.byId.flag[id].message || "")}">${ICON.flag}${esc(label || id)}</a>`;
    if (S.byId.rec[id]) return `<a class="cite rc" href="#resources/${enc(id)}" title="${esc(S.byId.rec[id].title || "")}">${ICON.spark}${esc(label || id)}</a>`;
    return null;
  }
  const refChip = (id) => idChip(id) || `<span class="cite">${esc(id)}</span>`;

  // Turns bare event/flag/recommendation ids in rendered text into chips (LLMs do not always bracket them).
  function linkIds(root) {
    const ids = [...Object.keys(S.byId.event), ...Object.keys(S.byId.flag), ...Object.keys(S.byId.rec)]
      .sort((a, b) => b.length - a.length).map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!ids.length) return;
    const re = new RegExp(`(${ids.join("|")})(?![A-Za-z0-9_])`, "g");
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) if (!walker.currentNode.parentElement.closest("a, code, .cite")) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const text = node.nodeValue;
      re.lastIndex = 0;
      if (!re.test(text)) continue;
      const tpl = document.createElement("template");
      tpl.innerHTML = esc(text).replace(re, (m, id, offset, all) => (/[A-Za-z0-9_]/.test(all[offset - 1] || "") ? m : idChip(id) || m));
      node.replaceWith(tpl.content);
    }
  }

  // ===================================================================== video overlay + player
  class Overlay {
    constructor(video, canvas) {
      this.video = video; this.canvas = canvas; this.ctx = canvas.getContext("2d");
      this.dets = null; this.enabled = true; this.token = 0; this.alive = true; this.src = null; this.key = "";
      this.loop = this.loop.bind(this);
      requestAnimationFrame(this.loop);
      onCleanup(() => { this.alive = false; });
    }
    async load(source) {
      const token = ++this.token;
      this.dets = null; this.src = source; this.key = "";
      if (!source) return;
      try {
        const d = await api(`api/detections?source=${enc(source)}&stride=3`, { timeout: 45000 });
        if (token === this.token && this.alive) this.dets = d;
      } catch { /* the overlay is optional */ }
    }
    frameAt(t) {
      const fr = this.dets?.frames;
      if (!fr?.length) return null;
      let lo = 0, hi = fr.length - 1;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (fr[mid].t <= t) lo = mid; else hi = mid - 1; }
      let best = fr[lo];
      if (lo + 1 < fr.length && Math.abs(fr[lo + 1].t - t) < Math.abs(best.t - t)) best = fr[lo + 1];
      return Math.abs(best.t - t) <= 0.25 ? best : null;
    }
    loop() {
      if (!this.alive) return;
      if (!this.video.isConnected) { this.alive = false; return; }
      this.draw();
      requestAnimationFrame(this.loop);
    }
    draw() {
      const v = this.video, c = this.canvas, dpr = window.devicePixelRatio || 1;
      const cw = v.clientWidth, ch = v.clientHeight;
      const f = this.enabled && this.dets ? this.frameAt(v.currentTime) : null;
      const key = `${cw}x${ch}|${f ? f.t : "-"}|${this.enabled}`;
      if (key === this.key || !cw || !ch) return;
      this.key = key;
      if (c.width !== Math.round(cw * dpr) || c.height !== Math.round(ch * dpr)) {
        c.width = Math.round(cw * dpr); c.height = Math.round(ch * dpr);
        c.style.width = cw + "px"; c.style.height = ch + "px";
      }
      const ctx = this.ctx;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      if (!f) return;
      const vw = this.dets.width || v.videoWidth || 1920, vh = this.dets.height || v.videoHeight || 1080;
      const sc = Math.min(cw / vw, ch / vh), ox = (cw - vw * sc) / 2, oy = (ch - vh * sc) / 2;
      const small = cw < 420;
      ctx.lineWidth = small ? 1.4 : 2;
      ctx.font = `600 ${small ? 9 : 11}px Inter, "Segoe UI", system-ui, sans-serif`;
      for (const [x1, y1, x2, y2, lab, conf] of f.boxes) {
        const person = lab === "person";
        const color = person ? C.cyan : C.orange;
        const x = ox + x1 * sc, y = oy + y1 * sc, w = (x2 - x1) * sc, h = (y2 - y1) * sc;
        ctx.strokeStyle = color;
        ctx.strokeRect(x, y, w, h);
        if (small && person) continue;
        const tag = `${lab} ${Math.round(conf * 100)}`;
        const tw = ctx.measureText(tag).width + 8, th = small ? 12 : 15, ty = y - th < 0 ? y : y - th;
        ctx.fillStyle = color;
        ctx.fillRect(x, ty, tw, th);
        ctx.fillStyle = "#031018";
        ctx.fillText(tag, x + 4, ty + th - 4);
      }
    }
  }

  function mountPlayer(host, o) {
    host.innerHTML = `
      <div class="player">
        <div class="video-wrap loading">
          <video muted playsinline preload="auto"></video>
          <canvas class="overlay"></canvas>
          <div class="v-tl"><span class="rec-dot"></span><span>${esc(o.label || "")}</span><span class="v-scene mono"></span></div>
          <div class="v-legend"><span class="lg person">${tr("legend_person")}</span><span class="lg machine">${tr("legend_machine")}</span></div>
          <div class="v-state"><div class="spinner"></div></div>
          <div class="v-error">${ICON.camera}<span>${tr("clip_error")}</span></div>
        </div>
        <div class="controls">
          <button type="button" class="icon-btn" data-act="play" aria-label="Play or pause">${ICON.play}</button>
          <div class="scrub"><div class="scrub-fill"></div><div class="scrub-marks"></div></div>
          <span class="time mono">0:00 / 0:00</span>
          <button type="button" class="btn sm" data-act="jump">${ICON.target}${tr("jump_event")}</button>
          <label class="toggle sm"><input type="checkbox" data-act="boxes"${S.boxes ? " checked" : ""}><span>${tr("boxes")}</span></label>
          <button type="button" class="icon-btn" data-act="fs" aria-label="Fullscreen">${ICON.expand}</button>
        </div>
      </div>`;
    const wrap = $(".video-wrap", host), video = $("video", host), scrub = $(".scrub", host);
    const fill = $(".scrub-fill", host), marks = $(".scrub-marks", host), time = $(".time", host), scene = $(".v-scene", host);
    const playBtn = $('[data-act="play"]', host);
    const overlay = new Overlay(video, $("canvas", host));
    overlay.enabled = S.boxes;
    overlay.load(o.src);
    video.src = clipUrl(o.src);
    let started = false, last = 0;
    video.addEventListener("loadedmetadata", () => {
      const d = video.duration || 0;
      marks.innerHTML = (o.markers || []).map((m) => `<i class="mk ${esc(m.cls || "")}" style="left:${clamp((m.t / Math.max(d, 0.01)) * 100, 0, 100)}%" title="${esc(m.label || "")}"></i>`).join("");
      if (!started) {
        started = true;
        video.currentTime = clamp(o.t - (o.preroll ?? 2), 0, Math.max(0, d - 0.1));
        if (o.autoplay !== false) video.play().catch(() => {});
      }
    });
    video.addEventListener("timeupdate", () => {
      const d = video.duration || 0, cur = video.currentTime;
      fill.style.width = d ? `${(cur / d) * 100}%` : "0";
      time.textContent = `${fmtT(cur)} / ${fmtT(d)}`;
      scene.textContent = `· ${tr("scene_time")} ${fmtT((o.sceneOffset || 0) + cur)}`;
      if (last < o.t && cur >= o.t && cur - last < 1) { wrap.classList.remove("flash"); void wrap.offsetWidth; wrap.classList.add("flash"); }
      last = cur;
    });
    const busy = (on) => wrap.classList.toggle("loading", on);
    video.addEventListener("waiting", () => busy(true));
    ["canplay", "playing", "seeked"].forEach((ev) => video.addEventListener(ev, () => busy(false)));
    video.addEventListener("error", () => { busy(false); wrap.classList.add("err"); });
    video.addEventListener("play", () => { playBtn.innerHTML = ICON.pause; });
    video.addEventListener("pause", () => { playBtn.innerHTML = ICON.play; });
    playBtn.onclick = () => (video.paused ? video.play().catch(() => {}) : video.pause());
    $('[data-act="jump"]', host).onclick = () => { video.pause(); video.currentTime = o.t; };
    $('[data-act="boxes"]', host).onchange = (ev) => { S.boxes = ev.target.checked; overlay.enabled = S.boxes; };
    $('[data-act="fs"]', host).onclick = () => (document.fullscreenElement ? document.exitFullscreen() : wrap.requestFullscreen?.());
    let dragging = false;
    const seekTo = (ev) => { const r = scrub.getBoundingClientRect(); if (video.duration) video.currentTime = clamp((ev.clientX - r.left) / r.width, 0, 1) * video.duration; };
    scrub.addEventListener("pointerdown", (ev) => { dragging = true; scrub.setPointerCapture(ev.pointerId); seekTo(ev); });
    scrub.addEventListener("pointermove", (ev) => { if (dragging) seekTo(ev); });
    scrub.addEventListener("pointerup", () => { dragging = false; });
    video.addEventListener("click", () => playBtn.click());
    onCleanup(() => stopVideo(video));
    return { video, overlay };
  }

  // ===================================================================== overview
  function kpiCard(ico, title, value, sub, accent, ratio) {
    return `<div class="kpi accent-${accent}"><div class="kpi-h">${ico}<span>${esc(title)}</span></div>
      <div class="kpi-v">${value}</div>${ratio != null ? `<div class="kpi-bar"><i style="width:${clamp(num(ratio) * 100, 0, 100)}%"></i></div>` : ""}
      <div class="kpi-s">${esc(sub)}</div></div>`;
  }

  function camCard(c) {
    const chunks = S.idx.cams[c.site_id + "|" + c.camera]?.chunks || [];
    const ch = chunks.at(-1);
    const media = ch ? `<video class="thumb" muted loop playsinline autoplay preload="auto" src="${clipUrl(ch.original_video)}"></video>` : "";
    const spark = sparkline([{ values: c.spark_people, color: C.cyan, fill: true }, { values: c.spark_idle, color: C.amber }], { w: 260, h: 40 });
    return `<a class="cam-card st-${esc(c.status)}" href="#resources/${enc(c.site_id)}/${enc(c.camera)}">
      <div class="thumb-wrap">${media}<span class="cam-tag">${ICON.camera}${esc(c.camera)} · ${esc(viewLabel(c.view))}</span><span class="st-pill"><i></i>${tr("status_" + c.status)}</span></div>
      <div class="cam-body"><div class="cam-stats">
        <div><b>${fmtNum(c.people_now)}</b><span>${tr("people")} · ${tr("avg")} ${fmtNum(c.people_avg)}</span></div>
        <div><b class="${num(c.idle_ratio) >= 0.5 ? "amber" : ""}">${pct(c.idle_ratio)}</b><span>${tr("idle")}</span></div>
        <div><b>${fmtNum(c.machines_moving_now)}/${fmtNum(c.machines_total_now)}</b><span>${tr("machines")} ${tr("moving")}</span></div>
      </div>${spark}</div></a>`;
  }

  function scenarioCard(site) {
    const events = S.data.events.filter((e) => e.site_id === site.site_id);
    const top = events[0];
    const cams = camOrder(site);
    const cam = top?.camera || cams[0]?.camera;
    const sceneT = top ? num(top.scene_t) : num(site.duration_sec) / 2;
    const ch = cam ? chunkAt(site.site_id, cam, sceneT) : null;
    const status = events.some((e) => e.severity === "high") ? "alert" : events.length ? "warn" : "ok";
    const media = ch ? `<video class="thumb hover-play" muted playsinline preload="metadata" src="${clipUrl(ch.original_video)}#t=${Math.max(0, sceneT - ch.scene_t0).toFixed(1)}"></video>` : "";
    const href = top ? `#alerts/${enc(top.event_id)}` : `#replay/${enc(site.site_id)}@0`;
    return `<a class="cam-card scenario st-${status}" href="${href}">
      <div class="thumb-wrap">${media}<span class="cam-tag">${ICON.camera}${esc(site.site_id)} · ${esc(cam || "")}</span><span class="st-pill"><i></i>${tr("status_" + status)}</span></div>
      <div class="cam-body"><div class="scn-title">${esc(site.title || site.site_id)}</div>
        <div class="scn-meta">${tr("scenario_views", { n: cams.length })} · ${fmtT(site.duration_sec)}</div>
        <div class="scn-events">${events.length ? events.slice(0, 2).map((e) => `<span class="sev-tag sev-${esc(e.severity)}">${typeIcon(e.type)}${esc(typeLabel(e.type))} @ ${fmtT(e.scene_t)}</span>`).join("") : `<span class="muted">${tr("no_alerts_site")}</span>`}</div>
      </div></a>`;
  }

  function feedItem(e, i) {
    const acked = S.acked.has(e.event_id);
    const side = S.newIds.has(e.event_id) ? `<span class="new">${tr("new")}</span>` : acked ? `<span class="ackd">${ICON.check}</span>` : `<span class="sev-tag sev-${esc(e.severity)}">${esc(sevLabel(e.severity))}</span>`;
    return `<a class="feed-item sev-${esc(e.severity)}${acked ? " acked" : ""}" href="#alerts/${enc(e.event_id)}" style="--i:${i}">
      <span class="sev-bar"></span><span class="feed-ico">${typeIcon(e.type)}</span>
      <span class="feed-main"><b>${esc(e.title || typeLabel(e.type))}</b><small>${esc(e.site_id)} · ${esc(e.camera)} · ${esc(typeLabel(e.type))} · ${pct(e.confidence)}</small></span>
      <span class="feed-side"><span class="mono">${fmtT(e.scene_t)}</span>${side}</span></a>`;
  }

  const flagItem = (f) => `<a class="flag-item" href="#resources/${enc(f.flag_id)}" style="--c:${FLAG_COLOR[f.type] || C.slate}">
      <span class="ftag">${esc(flagLabel(f.type))}</span><span class="flag-msg">${esc(f.message || "")}</span>
      <span class="mono flag-val">${esc(fmtScalar(num((f.metric || {}).value)))}<small>/${esc(fmtScalar(num((f.metric || {}).threshold)))}</small></span></a>`;

  const recItem = (r, i) => `<a class="rec-item" href="#resources/${enc(r.rec_id)}"><span class="rec-num">${i + 1}</span>
      <span><b>${esc(r.title || "")}</b><small>${esc(r.expected_impact || r.action || "")}</small></span></a>`;

  function renderOverview(el) {
    const o = S.data.overview || {}, k = o.kpis || {};
    const open = S.data.events.filter((e) => !S.acked.has(e.event_id));
    const sevCount = (s) => open.filter((e) => e.severity === s).length;
    const floorCams = (o.cameras || []).filter((c) => c.kind === "continuous");
    const scenarios = S.idx.sites.filter((s) => siteKind(s) === "scenario");
    const flags = (o.top_flags || []).slice(0, 5);
    const recs = (o.top_recommendations || []).slice(0, 3);
    const alertsKpi = `<div class="kpi accent-red"><div class="kpi-h">${ICON.alert}<span>${tr("kpi_alerts")}</span></div>
      <div class="kpi-v">${open.length}</div>
      <div class="sev-row">${["high", "medium", "low"].map((s) => `<span class="sev-tag sev-${s}">${sevLabel(s)} ${sevCount(s)}</span>`).join("")}</div></div>`;
    el.innerHTML = `
      <section class="kpis">
        ${kpiCard(ICON.users, tr("kpi_people"), fmtNum(k.people_now), tr("kpi_people_sub", { avg: fmtNum(k.people_avg), n: k.floor_cameras ?? floorCams.length, t: fmtT(k.now_scene_t) }), "cyan")}
        ${kpiCard(ICON.clock, tr("kpi_idle"), pct(k.idle_ratio), tr("kpi_idle_sub", { m: fmtNum(k.idle_person_minutes) }), num(k.idle_ratio) >= 0.5 ? "amber" : "cyan", k.idle_ratio)}
        ${kpiCard(ICON.machine, tr("kpi_machines"), `${fmtNum(k.machines_active_now)}<small>/${fmtNum(k.machines_total_now)}</small>`, tr("kpi_machines_sub", { p: pct(k.machine_moving_ratio) }), "orange", k.machine_moving_ratio)}
        ${alertsKpi}
        ${kpiCard(ICON.flag, tr("kpi_flags"), String(k.flags ?? S.data.util.flags.length), tr("kpi_flags_sub"), "violet")}
        ${kpiCard(ICON.camera, tr("kpi_footage"), String(k.cameras ?? 0), tr("kpi_footage_sub", { m: fmtNum(k.video_minutes), n: k.segments ?? 0 }), "blue")}
      </section>
      <section class="ov-grid">
        <div class="card">
          <div class="card-h"><h2>${ICON.camera}${tr("cam_status")}</h2><a class="link" href="#replay">${tr("open_wall")} →</a></div>
          <div class="cam-grid">${floorCams.map(camCard).join("")}${scenarios.map(scenarioCard).join("")}</div>
        </div>
        <div class="ov-side">
          <div class="card feed-card">
            <div class="card-h"><h2><span class="live-dot"></span>${tr("alert_feed")}</h2><a class="link" href="#alerts">${tr("view_all")} →</a></div>
            <div class="feed">${S.data.events.slice(0, 8).map(feedItem).join("") || emptyState(ICON.shield, tr("alerts_none"))}</div>
          </div>
          <div class="card"><div class="card-h"><h2>${ICON.flag}${tr("top_flags")}</h2><a class="link" href="#resources">${tr("view_all")} →</a></div>
            <div class="flag-items">${flags.map(flagItem).join("") || emptyState(ICON.flag, tr("no_flags"))}</div></div>
          <div class="card"><div class="card-h"><h2>${ICON.spark}${tr("top_recs")}</h2></div>
            <div class="rec-items">${recs.map(recItem).join("") || emptyState(ICON.spark, tr("no_recs"))}</div></div>
        </div>
      </section>`;
    $$("video.thumb", el).forEach((v) => {
      onCleanup(() => stopVideo(v));
      if (!v.classList.contains("hover-play")) return;
      const card = v.closest(".cam-card");
      card.addEventListener("mouseenter", () => v.play().catch(() => {}));
      card.addEventListener("mouseleave", () => v.pause());
    });
  }

  // ===================================================================== safety alerts
  function visibleAlerts() {
    const F = S.filters;
    return S.data.events.filter((e) => (!F.type || e.type === F.type) && (!F.site || e.site_id === F.site)
      && F.sev[e.severity] !== false && (F.showAcked || !S.acked.has(e.event_id)));
  }

  function renderAlerts(el, arg) {
    const F = S.filters;
    if (!S.data.events.length) { el.innerHTML = `<div class="card">${emptyState(ICON.shield, tr("alerts_none"))}</div>`; return; }
    const types = [...new Set(S.data.events.map((e) => e.type))];
    const sites = [...new Set(S.data.events.map((e) => e.site_id))];
    el.innerHTML = `
      <div class="alerts-layout">
        <aside class="card alert-list">
          <div class="card-h"><h2>${ICON.shield}${tr("nav_alerts")}</h2><span class="count" id="alCount"></span></div>
          <div class="filters">
            <select id="fType" aria-label="type"><option value="">${tr("all_types")}</option>${types.map((x) => `<option value="${esc(x)}"${F.type === x ? " selected" : ""}>${esc(typeLabel(x))}</option>`).join("")}</select>
            <select id="fSite" aria-label="site"><option value="">${tr("all_sites")}</option>${sites.map((x) => `<option value="${esc(x)}"${F.site === x ? " selected" : ""}>${esc(x)}</option>`).join("")}</select>
            <div class="sev-filter">${["high", "medium", "low"].map((s) => `<button type="button" class="chip sev-${s}${F.sev[s] ? " on" : ""}" data-sev="${s}">${sevLabel(s)}</button>`).join("")}</div>
            <label class="toggle"><input type="checkbox" id="fAcked"${F.showAcked ? " checked" : ""}><span>${tr("show_acked")}</span></label>
          </div>
          <div class="list" id="alList"></div>
        </aside>
        <section class="alert-detail" id="alDetail"></section>
      </div>`;
    let selected = S.byId.event[arg] ? arg : null;
    const drawList = () => {
      const items = visibleAlerts();
      if (!selected || !S.byId.event[selected]) selected = items[0]?.event_id || null;
      $("#alCount").textContent = items.length;
      $("#alList").innerHTML = items.map((e) => `
        <a class="al-item sev-${esc(e.severity)}${e.event_id === selected ? " sel" : ""}${S.acked.has(e.event_id) ? " acked" : ""}" href="#alerts/${enc(e.event_id)}" data-id="${esc(e.event_id)}">
          <span class="sev-bar"></span><span class="feed-ico">${typeIcon(e.type)}</span>
          <span class="al-main"><b>${esc(e.title || typeLabel(e.type))}</b><small>${esc(e.site_id)} · ${esc(e.camera)} · ${fmtT(e.scene_t)}</small>
            <span class="al-tags"><span class="sev-tag sev-${esc(e.severity)}">${esc(sevLabel(e.severity))}</span><span class="tag">${esc(typeLabel(e.type))}</span><span class="tag mono">${pct(e.confidence)}</span>${S.acked.has(e.event_id) ? `<span class="tag ok">${ICON.check}${tr("acked")}</span>` : ""}</span></span></a>`).join("")
        || emptyState(ICON.shield, tr("alerts_empty"));
    };
    const drawDetail = () => {
      runCleanups();
      renderAlertDetail($("#alDetail"), S.byId.event[selected], () => { drawList(); updateHeader(); });
    };
    drawList();
    drawDetail();
    $("#alList").addEventListener("click", (ev) => {
      const a = ev.target.closest(".al-item");
      if (!a) return;
      ev.preventDefault();
      selected = a.dataset.id;
      history.replaceState(null, "", "#alerts/" + enc(selected));
      $$(".al-item", el).forEach((x) => x.classList.toggle("sel", x === a));
      drawDetail();
    });
    const refilter = () => { const prev = selected; drawList(); if (selected !== prev) drawDetail(); };
    $("#fType").onchange = (ev) => { F.type = ev.target.value; refilter(); };
    $("#fSite").onchange = (ev) => { F.site = ev.target.value; refilter(); };
    $("#fAcked").onchange = (ev) => { F.showAcked = ev.target.checked; refilter(); };
    $$("[data-sev]", el).forEach((b) => { b.onclick = () => { F.sev[b.dataset.sev] = !F.sev[b.dataset.sev]; b.classList.toggle("on"); refilter(); }; });
  }

  function renderAlertDetail(host, e, onAck) {
    if (!e) { host.innerHTML = `<div class="card">${emptyState(ICON.shield, tr("select_alert"))}</div>`; return; }
    const ev = e.evidence || {};
    const views = (e.views || []).filter((v) => v && v.source);
    if (!views.length && e.source) views.push({ camera: e.camera, source: e.source, t_in_segment: e.t_in_segment, label: tr("primary"), confidence: e.confidence });
    let active = Math.max(0, views.findIndex((v) => v.camera === e.camera));
    const acked = S.acked.has(e.event_id);
    const replayT = Math.max(0, num(e.scene_t) - 2).toFixed(1);
    host.innerHTML = `
      <div class="card detail sev-${esc(e.severity)}">
        <div class="detail-h">
          <div>
            <div class="detail-tags"><span class="sev-badge sev-${esc(e.severity)}">${esc(sevLabel(e.severity))}</span><span class="type-badge">${typeIcon(e.type)}${esc(typeLabel(e.type))}</span><span class="muted mono small">${esc(e.event_id)}</span></div>
            <h1>${esc(e.title || typeLabel(e.type))}</h1>
            <div class="detail-meta"><span>${esc(siteTitle(e.site_id))}</span><span>${ICON.camera}<b>${esc(e.camera)}</b></span>
              <span>${tr("scene_time")} <b class="mono">${fmtT(e.scene_t)}</b></span><span>${tr("seg_time")} <span class="mono">${num(e.t_in_segment).toFixed(1)} s</span></span>
              <span class="conf">${tr("confidence")} <span class="conf-bar"><i style="width:${clamp(num(e.confidence) * 100, 0, 100)}%"></i></span><b class="mono">${pct(e.confidence)}</b></span></div>
          </div>
          <button type="button" class="btn ${acked ? "ghost" : "primary"}" id="ackBtn">${acked ? ICON.check + tr("acked") : tr("ack")}</button>
        </div>
        <div id="player"></div>
        <div class="views-row"><span class="label">${tr("views_title")}</span><div class="chips" id="viewChips"></div></div>
        ${e.description ? `<p class="desc">${esc(e.description)}</p>` : ""}
        <h3 class="sec-h">${tr("evidence")}</h3>
        <div class="evidence">
          <div class="ev-card"><div class="ev-h">${ICON.spark}${tr("ev_vlm")}</div>${renderValue(ev.vlm)}</div>
          <div class="ev-card"><div class="ev-h">${ICON.chart}${tr("ev_kin")}</div>${renderValue(ev.kinematics)}</div>
          <div class="ev-card cons"><div class="ev-h">${ICON.check}${tr("ev_cons")}</div>${renderValue(ev.consensus)}</div>
        </div>
        <h3 class="sec-h">${tr("cmp_title")}</h3>
        <div class="compare">
          <div class="cmp old"><div class="cmp-h">✕ ${tr("cmp_old")}</div><blockquote>${esc(ev.pipeline_caption_said || tr("no_caption"))}</blockquote><div class="cmp-foot">${tr("cmp_old_foot")}</div></div>
          <div class="cmp new"><div class="cmp-h">✓ ${tr("cmp_new")}</div>
            <p class="cmp-verdict"><span class="sev-tag sev-${esc(e.severity)}">${esc(sevLabel(e.severity))}</span><b>${esc(typeLabel(e.type))}</b> @ <span class="mono">${fmtT(e.scene_t)}</span> · ${pct(e.confidence)}</p>
            <p>${esc((typeof ev.vlm?.summary === "string" && ev.vlm.summary) || e.description || e.title || "")}</p><div class="cmp-foot">${tr("cmp_new_foot")}</div></div>
        </div>
        <div class="detail-actions">
          <a class="btn" href="#replay/${enc(e.site_id)}@${replayT}">${ICON.grid}${tr("open_replay")}</a>
          <a class="btn" href="#ask/${enc(tr("ask_about_q", { id: e.event_id }))}">${ICON.chat}${tr("ask_about")}</a>
        </div>
      </div>`;
    const drawChips = () => {
      $("#viewChips", host).innerHTML = views.map((v, i) => `<button type="button" class="chip view-chip${i === active ? " on" : ""}" data-i="${i}">${ICON.camera}${esc(v.camera)}${v.label ? ` <small>${esc(humanize(v.label))}</small>` : ""}${v.confidence != null ? ` <b class="mono">${pct(v.confidence)}</b>` : ""}</button>`).join("");
    };
    const play = () => {
      const v = views[active];
      if (!v) { $("#player", host).innerHTML = emptyState(ICON.camera, tr("clip_error")); return; }
      const tInSeg = v.t_in_segment != null ? num(v.t_in_segment) : num(e.t_in_segment);
      const target = playTarget(v.source, tInSeg);
      mountPlayer($("#player", host), {
        src: target.src, t: target.t, preroll: 2.5,
        sceneOffset: target.chunk ? target.chunk.scene_t0 : num(e.scene_t) - tInSeg,
        label: `${v.camera} · ${typeLabel(e.type)}`,
        markers: [{ t: target.t, cls: "sev-" + e.severity, label: `${typeLabel(e.type)} @ ${fmtT(e.scene_t)}` }],
      });
    };
    drawChips();
    play();
    $("#viewChips", host).addEventListener("click", (evt) => {
      const b = evt.target.closest(".view-chip");
      if (!b || +b.dataset.i === active) return;
      active = +b.dataset.i;
      runCleanups();
      drawChips();
      play();
    });
    $("#ackBtn", host).onclick = () => {
      if (S.acked.has(e.event_id)) S.acked.delete(e.event_id); else S.acked.add(e.event_id);
      saved.set("acked", [...S.acked]);
      const b = $("#ackBtn", host), on = S.acked.has(e.event_id);
      b.className = "btn " + (on ? "ghost" : "primary");
      b.innerHTML = on ? ICON.check + tr("acked") : tr("ack");
      if (on) toast(`${tr("acked")}: ${e.title || e.event_id}`);
      onAck?.();
    };
  }

  // ===================================================================== resources & bottlenecks
  function applyResArg(arg) {
    const R = S.res;
    if (!arg) return;
    const flag = S.byId.flag[arg], rec = S.byId.rec[arg];
    if (flag) { Object.assign(R, { site: flag.site_id, camera: flag.camera, flag: flag.flag_id, t: num(flag.scene_t0), rec: null }); return; }
    if (rec) {
      R.rec = rec.rec_id; R.flag = null;
      const ref = (rec.refs || []).map((id) => S.byId.flag[id] || S.byId.event[id]).find(Boolean);
      if (ref) { R.site = ref.site_id; R.camera = ref.camera; }
      return;
    }
    const [site, camera] = arg.split("/");
    if (S.idx.site[site]) Object.assign(R, { site, camera: camera || null, flag: null, rec: null, t: null });
  }

  function renderResources(el, arg) {
    const R = S.res;
    applyResArg(arg);
    const utilCams = S.data.util.cameras;
    const sites = S.idx.sites.filter((s) => utilCams.some((c) => c.site_id === s.site_id));
    if (!sites.length) { el.innerHTML = `<div class="card">${emptyState(ICON.bars, tr("no_util"))}</div>`; return; }
    if (!sites.some((s) => s.site_id === R.site)) { R.site = sites[0].site_id; R.camera = null; R.t = null; }
    const cams = utilCams.filter((c) => c.site_id === R.site)
      .sort((a, b) => (({ ceiling: 0, eye: 1 })[a.view] ?? 0) - (({ ceiling: 0, eye: 1 })[b.view] ?? 0) || String(a.camera).localeCompare(String(b.camera)));
    const siteFlags = S.data.util.flags.filter((f) => f.site_id === R.site).sort((a, b) => flagStrength(b) - flagStrength(a));
    if (!cams.some((c) => c.camera === R.camera)) {
      R.camera = (siteFlags[0] && cams.some((c) => c.camera === siteFlags[0].camera) ? siteFlags[0].camera : cams[0].camera);
      R.t = null;
    }
    const cam = cams.find((c) => c.camera === R.camera);
    const site = S.idx.site[R.site];
    const siteIds = new Set([...siteFlags.map((f) => f.flag_id), ...S.data.events.filter((e) => e.site_id === R.site).map((e) => e.event_id)]);
    const allRecs = S.data.recs.recommendations || [];
    const recs = allRecs.filter((r) => (r.refs || []).some((id) => siteIds.has(id)));
    const recList = recs.length ? recs : allRecs;
    const idleItems = cams.map((c) => ({ key: c.camera, label: c.camera, value: num(c.totals?.idle_ratio), color: num(c.totals?.idle_ratio) >= 0.5 ? C.amber : C.cyan }));
    const utilItems = cams.map((c) => ({ key: c.camera, label: c.camera, value: num(c.totals?.machine_moving_ratio), color: C.orange }));
    el.innerHTML = `<div class="res-root">
      <div class="res-head">
        <div class="seg-tabs">${sites.map((s) => `<button type="button" class="seg${s.site_id === R.site ? " on" : ""}" data-site="${esc(s.site_id)}"><b>${esc(s.site_id)}</b><small>${esc(siteKind(s) === "scenario" ? tr("scenario") : (s.cameras || []).length + " " + tr("camera").toLowerCase())}</small></button>`).join("")}</div>
        <div class="chips cam-chips">${cams.map((c) => `<button type="button" class="chip${c.camera === R.camera ? " on" : ""}" data-cam="${esc(c.camera)}">${esc(c.camera)} <small>${esc(viewLabel(c.view))}</small></button>`).join("")}</div>
      </div>
      <div class="res-title"><h1>${esc(site?.title || R.site)}</h1><span class="muted">${esc(R.camera)} · ${esc(viewLabel(cam?.view))} · ${tr("avg")} ${fmtNum(cam?.totals?.people_avg)} ${tr("people")} · ${pct(cam?.totals?.idle_ratio)} ${tr("idle")}</span></div>
      <div class="res-grid">
        <div class="card res-people"><div class="card-h"><h2>${ICON.users}${tr("people_time")}</h2>
          <div class="legend"><span style="--c:${C.cyan}">${tr("s_people")}</span><span style="--c:${C.amber}">${tr("s_idle")}</span><span style="--c:${C.green}">${tr("s_moving")}</span></div></div>
          <div class="chart-host" id="chPeople"></div><p class="hint">${tr("chart_hint")}</p></div>
        <div class="card res-heat"><div class="card-h"><h2>${ICON.grid}${tr("heatmap")}</h2>
          <div class="seg-ctrl">${["occupancy", "idle"].map((l) => `<button type="button" data-layer="${l}" class="${R.layer === l ? "on" : ""}">${tr(l === "idle" ? "idle_layer" : "occupancy")}</button>`).join("")}</div></div>
          <div class="heat-wrap" id="heat"><video muted playsinline preload="auto"></video><canvas></canvas><div class="heat-cap mono"></div></div>
          <div id="segDetail" class="seg-detail"></div></div>
        <div class="card res-mach"><div class="card-h"><h2>${ICON.machine}${tr("machines_time")}</h2>
          <div class="legend"><span style="--c:${C.slate}">${tr("s_m_total")}</span><span style="--c:${C.orange}">${tr("s_m_moving")}</span></div></div>
          <div class="chart-host" id="chMach"></div></div>
        <div class="card res-bars"><div class="card-h"><h2>${ICON.bars}${tr("idle_by_cam")}</h2></div>${barList(idleItems, { selected: R.camera, threshold: 0.5 })}
          <div class="card-h sub"><h2>${ICON.machine}${tr("util_by_cam")}</h2></div>${barList(utilItems, { selected: R.camera })}</div>
        <div class="card res-flags"><div class="card-h"><h2>${ICON.flag}${tr("flags")}</h2><span class="count">${siteFlags.length}</span></div>
          <div class="flag-list">${siteFlags.map((f) => flagRow(f)).join("") || emptyState(ICON.flag, tr("no_flags"))}</div></div>
        <div class="card res-recs"><div class="card-h"><h2>${ICON.spark}${tr("recs")}</h2></div>
          <div class="rec-list">${recList.map((r, i) => recCard(r, i)).join("") || emptyState(ICON.spark, tr("no_recs"))}</div></div>
      </div></div>`;
    const heat = setupHeatmap($("#heat", el), cam);
    const drawCharts = () => {
      const series = cam.series || [];
      const pts = (key) => series.map((p) => ({ t: (num(p.scene_t0) + num(p.scene_t1)) / 2, v: num(p[key]) }));
      const t0 = series.length ? num(series[0].scene_t0) : 0;
      const t1 = series.length ? num(series.at(-1).scene_t1) : num(site?.duration_sec, 1);
      const span = t1 - t0;
      const bands = siteFlags.filter((f) => f.camera === R.camera && num(f.scene_t1) - num(f.scene_t0) < span * 0.9)
        .map((f) => ({ id: f.flag_id, t0: num(f.scene_t0), t1: num(f.scene_t1), color: FLAG_COLOR[f.type] || C.slate, sel: f.flag_id === R.flag, label: `${flagLabel(f.type)} · ${f.message || ""}` }));
      const markers = S.data.events.filter((e) => e.site_id === R.site && (e.camera === R.camera || (e.views || []).some((v) => v.camera === R.camera)))
        .map((e) => ({ id: e.event_id, t: num(e.scene_t), color: SEV_COLOR[e.severity] || C.red, label: `${typeLabel(e.type)} @ ${fmtT(e.scene_t)}` }));
      const points = series.map((p) => ({ ...p, t: (num(p.scene_t0) + num(p.scene_t1)) / 2, t0: num(p.scene_t0) }));
      $("#chPeople", el).innerHTML = lineChart({ t0, t1, height: 220, bands, markers, cursor: R.t != null ? R.t + 2.5 : null,
        series: [{ points: pts("people"), color: C.cyan, area: true }, { points: pts("idle"), color: C.amber }, { points: pts("moving"), color: C.green, dash: true }] });
      $("#chMach", el).innerHTML = lineChart({ t0, t1, height: 170, markers, cursor: R.t != null ? R.t + 2.5 : null,
        series: [{ points: pts("machines_total"), color: C.slate, dash: true }, { points: pts("machines_moving"), color: C.orange, area: true }] });
      const tipPeople = (p) => `<b>${fmtT(p.scene_t0)}–${fmtT(p.scene_t1)}</b><span style="--c:${C.cyan}">${tr("s_people")} ${fmtNum(p.people)}</span><span style="--c:${C.amber}">${tr("s_idle")} ${fmtNum(p.idle)}</span><span style="--c:${C.green}">${tr("s_moving")} ${fmtNum(p.moving)}</span>`;
      const tipMach = (p) => `<b>${fmtT(p.scene_t0)}–${fmtT(p.scene_t1)}</b><span style="--c:${C.slate}">${tr("s_m_total")} ${fmtNum(p.machines_total)}</span><span style="--c:${C.orange}">${tr("s_m_moving")} ${fmtNum(p.machines_moving)}</span>`;
      const pick = ({ t, flag }) => {
        if (flag) { const f = S.byId.flag[flag]; R.flag = flag; R.t = num(f?.scene_t0); history.replaceState(null, "", "#resources/" + enc(flag)); markFlags(); }
        else { R.t = t; }
        drawCharts(); heat.update();
      };
      bindChart($("#chPeople", el), { points, tip: tipPeople, onPick: pick });
      bindChart($("#chMach", el), { points, tip: tipMach, onPick: pick });
    };
    const markFlags = () => $$(".flag-row", el).forEach((r) => r.classList.toggle("sel", r.dataset.flag === R.flag));
    drawCharts();
    if (R.rec) {
      const recId = R.rec;
      R.rec = null;
      setTimeout(() => { const card = $(`#rec-${CSS.escape(recId)}`, el); card?.scrollIntoView({ behavior: "smooth", block: "center" }); card?.classList.add("flash"); }, 60);
    }
    if (R.flag && arg) setTimeout(() => $(`.flag-row[data-flag="${CSS.escape(R.flag)}"]`, el)?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 60);
    $(".res-root", el).addEventListener("click", (ev) => {
      const siteBtn = ev.target.closest("[data-site]"), camBtn = ev.target.closest("[data-cam]"), flagEl = ev.target.closest(".flag-row"), layer = ev.target.closest("[data-layer]");
      if (siteBtn) { Object.assign(R, { site: siteBtn.dataset.site, camera: null, t: null, flag: null, rec: null }); history.replaceState(null, "", "#resources/" + enc(R.site)); rerender(); }
      else if (camBtn) { Object.assign(R, { camera: camBtn.dataset.cam, t: null, flag: null }); history.replaceState(null, "", `#resources/${enc(R.site)}/${enc(R.camera)}`); rerender(); }
      else if (flagEl && !ev.target.closest("a")) {
        const f = S.byId.flag[flagEl.dataset.flag];
        if (!f) return;
        Object.assign(R, { flag: f.flag_id, t: num(f.scene_t0) });
        history.replaceState(null, "", "#resources/" + enc(f.flag_id));
        if (f.camera !== R.camera) { R.camera = f.camera; rerender(); return; }
        markFlags(); drawCharts(); heat.update();
      } else if (layer) { R.layer = layer.dataset.layer; $$("[data-layer]", el).forEach((b) => b.classList.toggle("on", b === layer)); heat.update(); }
    });
    function rerender() { runCleanups(); renderResources(el, ""); }
  }

  function flagRow(f) {
    const m = f.metric || {};
    const zone = Array.isArray(f.zone) && f.zone.length >= 2 ? ` · zone (${f.zone[0]},${f.zone[1]})` : "";
    const ratio = num(m.threshold) ? clamp(num(m.value) / (num(m.threshold) * 2), 0, 1) : 0;
    return `<div class="flag-row${f.flag_id === S.res.flag ? " sel" : ""}" data-flag="${esc(f.flag_id)}" style="--c:${FLAG_COLOR[f.type] || C.slate}">
      <span class="ftag">${esc(flagLabel(f.type))}</span>
      <div class="flag-main"><b>${esc(f.camera)}${esc(zone)} · <span class="mono">${fmtT(f.scene_t0)}–${fmtT(f.scene_t1)}</span></b><p>${esc(f.message || "")}</p></div>
      <div class="flag-metric"><span class="mono small">${esc(humanize(m.name || ""))}</span><b class="mono">${esc(fmtScalar(num(m.value)))}</b>
        <span class="mbar"><i style="width:${(ratio * 100).toFixed(0)}%"></i><em style="left:50%"></em></span><small>${tr("threshold")} ${esc(fmtScalar(num(m.threshold)))}</small></div></div>`;
  }

  function recCard(r, i) {
    return `<div class="rec-card${r.rec_id === S.res.rec ? " sel" : ""}" id="rec-${esc(r.rec_id)}">
      <div class="rec-h"><span class="rec-num">${i + 1}</span><b>${esc(r.title || "")}</b></div>
      ${r.action ? `<p class="rec-action">${esc(r.action)}</p>` : ""}
      <dl class="rec-kv">${r.rationale ? `<dt>${tr("rationale")}</dt><dd>${esc(r.rationale)}</dd>` : ""}${r.expected_impact ? `<dt>${tr("impact")}</dt><dd>${esc(r.expected_impact)}</dd>` : ""}</dl>
      <div class="chips">${(r.refs || []).map(refChip).join("")}</div></div>`;
  }

  function setupHeatmap(host, cam) {
    const R = S.res;
    const video = $("video", host), canvas = $("canvas", host), cap = $(".heat-cap", host);
    const ctx = canvas.getContext("2d");
    const duration = num(S.idx.site[R.site]?.duration_sec, 0);
    let rows = null, chunk = null;
    loadSegments(R.site, R.camera).then((r) => { rows = r; update(); });
    const rowAt = (t) => rows?.find((r) => t >= num(r.scene_t0) && t < num(r.scene_t1));
    const frameTime = () => (R.t != null ? R.t + 2.5 : duration / 2);
    function seekVideo() {
      const t = frameTime();
      const ch = chunkAt(R.site, R.camera, t);
      if (!ch) return;
      const local = clamp(t - ch.scene_t0, 0, ch.scene_t1 - ch.scene_t0 - 0.05);
      if (ch !== chunk) { chunk = ch; video.src = `${clipUrl(ch.original_video)}#t=${local.toFixed(2)}`; }
      else if (video.readyState >= 1) video.currentTime = local;
    }
    function draw() {
      const cw = host.clientWidth, chh = host.clientHeight, dpr = window.devicePixelRatio || 1;
      if (!cw || !chh) return;
      canvas.width = Math.round(cw * dpr); canvas.height = Math.round(chh * dpr);
      canvas.style.width = cw + "px"; canvas.style.height = chh + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, chh);
      const row = R.t != null ? rowAt(R.t) : null;
      const zones = row?.zones || cam?.heatmap || {};
      const grid = Array.isArray(zones[R.layer]) ? zones[R.layer] : [];
      const nr = grid.length || num(zones.rows, 3), nc = grid[0]?.length || num(zones.cols, 4);
      const vw = video.videoWidth || 1920, vh = video.videoHeight || 1080;
      const sc = Math.min(cw / vw, chh / vh), ox = (cw - vw * sc) / 2, oy = (chh - vh * sc) / 2, W = vw * sc, H = vh * sc;
      const max = Math.max(0.01, ...grid.flat().map((v) => num(v)));
      const cellW = W / nc, cellH = H / nr;
      ctx.font = `700 ${Math.max(11, Math.min(18, cellH / 4))}px Inter, "Segoe UI", system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (let r = 0; r < nr; r++) {
        for (let c = 0; c < nc; c++) {
          const v = num(grid[r]?.[c]), a = v / max;
          const x = ox + c * cellW, y = oy + r * cellH;
          ctx.fillStyle = heatColor(a);
          ctx.fillRect(x, y, cellW, cellH);
          ctx.strokeStyle = "rgba(148,163,184,.35)"; ctx.lineWidth = 1;
          ctx.strokeRect(x + 0.5, y + 0.5, cellW - 1, cellH - 1);
          ctx.fillStyle = "rgba(2,6,23,.65)";
          ctx.fillRect(x + cellW / 2 - 24, y + cellH / 2 - 11, 48, 22);
          ctx.fillStyle = "#e2e8f0";
          ctx.fillText(fmtNum(v), x + cellW / 2, y + cellH / 2 + 1);
        }
      }
      for (const f of S.data.util.flags) {
        if (f.site_id !== R.site || f.camera !== R.camera || !Array.isArray(f.zone) || f.zone.length < 2) continue;
        const [c, r] = f.zone, sel = f.flag_id === R.flag;
        ctx.strokeStyle = FLAG_COLOR[f.type] || C.slate;
        ctx.lineWidth = sel ? 4 : 2;
        ctx.setLineDash(sel ? [] : [6, 4]);
        ctx.strokeRect(ox + c * cellW + 2, oy + r * cellH + 2, cellW - 4, cellH - 4);
        ctx.setLineDash([]);
      }
      cap.textContent = `${R.camera} · ${row ? `${fmtT(row.scene_t0)}–${fmtT(row.scene_t1)}` : tr("window_avg")} · ${R.layer === "idle" ? tr("idle_layer") : tr("occupancy")}`;
      renderSegDetail($("#segDetail"), row);
    }
    function update() { seekVideo(); draw(); }
    video.addEventListener("loadeddata", draw);
    video.addEventListener("seeked", draw);
    const ro = new ResizeObserver(() => draw());
    ro.observe(host);
    onCleanup(() => { ro.disconnect(); stopVideo(video); });
    update();
    return { update };
  }

  function heatColor(a) {
    const stops = [[34, 211, 238], [251, 191, 36], [244, 63, 94]];
    const s = clamp(a, 0, 1) * 2, i = Math.min(1, Math.floor(s)), f = s - i;
    const [r, g, b] = stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * f));
    return `rgba(${r},${g},${b},${(0.08 + clamp(a, 0, 1) * 0.5).toFixed(3)})`;
  }

  function renderSegDetail(host, row) {
    if (!host) return;
    if (!row) { host.innerHTML = `<p class="hint">${tr("seg_hint")}</p>`; return; }
    const p = row.people || {}, m = row.machines || {};
    const mTotal = Object.values(m).reduce((s, x) => s + num(x?.total), 0), mMoving = Object.values(m).reduce((s, x) => s + num(x?.moving), 0);
    const vlm = typeof row.vlm_summary === "string" ? row.vlm_summary : row.vlm_summary ? JSON.stringify(row.vlm_summary) : "";
    host.innerHTML = `
      <div class="seg-h"><b>${tr("seg_detail", { t: `${fmtT(row.scene_t0)}–${fmtT(row.scene_t1)}` })}</b>${row.congestion ? `<span class="cong cong-${esc(row.congestion)}">${tr("congestion")}: ${esc(row.congestion)}</span>` : ""}</div>
      <div class="seg-stats"><span><b>${fmtNum(p.per_frame_median)}</b> ${tr("people")}</span><span><b class="amber">${fmtNum(p.idle)}</b> ${tr("idle")}</span><span><b>${fmtNum(p.moving)}</b> ${tr("moving")}</span><span><b>${fmtNum(mMoving)}/${fmtNum(mTotal)}</b> ${tr("machines")}</span></div>
      ${vlm ? `<div class="seg-text"><span class="k">${ICON.spark}${tr("vlm_summary")}</span><p>${esc(vlm)}</p></div>` : ""}
      ${row.pipeline_caption ? `<div class="seg-text old"><span class="k">${tr("pipeline_caption")}</span><p>${esc(row.pipeline_caption)}</p></div>` : ""}
      <div class="seg-foot"><div class="chips">${(row.event_ids || []).map(refChip).join("")}</div><a class="btn sm" href="#replay/${enc(row.site_id || S.res.site)}@${num(row.scene_t0)}">${ICON.grid}${tr("open_replay")}</a></div>`;
  }

  // ===================================================================== multi-camera replay
  function renderReplay(el, arg) {
    const R = S.replay;
    if (arg) {
      const [sid, tt] = arg.split("@");
      if (S.idx.site[sid]) { if (sid !== R.site) R.focus = -1; R.site = sid; R.t = num(tt, 0); }
    }
    const sites = S.idx.sites;
    if (!sites.length) { el.innerHTML = `<div class="card">${emptyState(ICON.grid, tr("no_videos"))}</div>`; return; }
    if (!S.idx.site[R.site]) {
      const withEvents = sites.find((s) => siteKind(s) === "scenario" && S.data.events.some((e) => e.site_id === s.site_id && e.severity === "high"));
      R.site = (withEvents || sites[0]).site_id;
      const first = S.data.events.find((e) => e.site_id === R.site);
      R.t = first ? Math.max(0, num(first.scene_t) - 2) : 0;
    }
    const site = S.idx.site[R.site];
    const scenario = siteKind(site) === "scenario";
    const events = S.data.events.filter((e) => e.site_id === R.site);
    const cams = camOrder(site).filter((c) => !scenario || R.eye || c.view !== "eye").slice(0, 10);
    const lead = cams.findIndex((c) => c.camera === events[0]?.camera);
    if (lead > 0) cams.unshift(cams.splice(lead, 1)[0]);
    const duration = num(site.duration_sec) || Math.max(1, ...cams.flatMap((c) => (c.chunks || []).map((ch) => ch.scene_t1)));
    const chunkLen = cams[0]?.chunks?.length > 1 ? cams[0].chunks[0].scene_t1 - cams[0].chunks[0].scene_t0 : 0;
    el.innerHTML = `
      <div class="card replay-head">
        <label class="field inline"><span>${tr("site")}</span><select id="rpSite">${sites.map((s) => `<option value="${esc(s.site_id)}"${s.site_id === R.site ? " selected" : ""}>${esc(s.site_id)} — ${esc(s.title || "")}</option>`).join("")}</select></label>
        ${scenario ? `<label class="toggle"><input type="checkbox" id="rpEye"${R.eye ? " checked" : ""}><span>${tr("eye_views")}</span></label>` : ""}
        <label class="toggle"><input type="checkbox" id="rpBoxes"${R.boxes ? " checked" : ""}><span>${tr("boxes")}</span></label>
        <div class="seg-ctrl" id="rpRate">${[0.5, 1, 2].map((r) => `<button type="button" data-rate="${r}" class="${R.rate === r ? "on" : ""}">${r}×</button>`).join("")}</div>
        <span class="muted small">${ICON.clock}${tr("sync_note")} · ${tr("replay_hint")}</span>
      </div>
      <div class="tiles n${cams.length}${R.focus >= 0 ? " has-focus" : ""}" id="rpTiles">${cams.map((c, i) => `
        <div class="tile${i === R.focus ? " focus" : ""}" data-i="${i}">
          <video muted playsinline preload="auto"></video><canvas class="overlay"></canvas>
          <div class="tile-label">${ICON.camera}${esc(c.camera)} <small>${esc(viewLabel(c.view))}</small></div>
          <div class="tile-state"><div class="spinner"></div></div><div class="tile-err">${tr("clip_error")}</div>
        </div>`).join("")}</div>
      <div class="card transport">
        <button type="button" class="icon-btn big" id="rpPlay" aria-label="Play or pause">${ICON.play}</button>
        <div class="rp-time mono" id="rpTime"></div>
        <div class="rp-scrub" id="rpScrub">
          ${chunkLen ? Array.from({ length: Math.max(0, Math.round(duration / chunkLen) - 1) }, (_, i) => `<i class="rp-tick" style="left:${(((i + 1) * chunkLen) / duration) * 100}%"></i>`).join("") : ""}
          <div class="rp-fill"></div>
          ${events.map((e) => `<button type="button" class="rp-mark sev-${esc(e.severity)}" data-t="${num(e.scene_t)}" style="left:${(num(e.scene_t) / duration) * 100}%" title="${esc(typeLabel(e.type))} @ ${fmtT(e.scene_t)}"></button>`).join("")}
          <div class="rp-head"></div>
        </div>
      </div>
      ${events.length ? `<div class="rp-events"><span class="label">${tr("events_title")}</span>${events.map((e) => `<button type="button" class="chip sev-${esc(e.severity)}" data-t="${num(e.scene_t)}">${typeIcon(e.type)}${esc(typeLabel(e.type))} · ${esc(e.camera)} · <span class="mono">${fmtT(e.scene_t)}</span></button><a class="link small" href="#alerts/${enc(e.event_id)}">${tr("evidence")} →</a>`).join("")}</div>` : ""}`;
    const engine = createReplay(el, site, cams, duration);
    engine.load(R.t);
    if (arg) engine.play();
    $("#rpSite", el).onchange = (ev) => { R.site = ev.target.value; R.t = 0; R.focus = -1; location.hash = `#replay/${enc(R.site)}@0`; };
    const eye = $("#rpEye", el);
    if (eye) eye.onchange = () => { R.eye = eye.checked; R.focus = -1; runCleanups(); renderReplay(el, ""); };
    $("#rpBoxes", el).onchange = (ev) => engine.setBoxes(ev.target.checked);
    $$("#rpRate button", el).forEach((b) => { b.onclick = () => { engine.setRate(+b.dataset.rate); $$("#rpRate button", el).forEach((x) => x.classList.toggle("on", x === b)); }; });
    $("#rpPlay", el).onclick = () => engine.toggle();
    $$("[data-t]", el).forEach((b) => { b.onclick = (ev) => { ev.stopPropagation(); engine.load(Math.max(0, +b.dataset.t - 2)); engine.play(); }; });
    $("#rpTiles", el).addEventListener("click", (ev) => {
      const tile = ev.target.closest(".tile");
      if (!tile) return;
      const i = +tile.dataset.i;
      R.focus = R.focus === i ? -1 : i;
      $$(".tile", el).forEach((x) => x.classList.toggle("focus", +x.dataset.i === R.focus));
      $("#rpTiles", el).classList.toggle("has-focus", R.focus >= 0);
    });
    const scrub = $("#rpScrub", el);
    let dragging = false, lastSeek = 0;
    const timeAt = (ev) => { const r = scrub.getBoundingClientRect(); return clamp((ev.clientX - r.left) / r.width, 0, 1) * duration; };
    scrub.addEventListener("pointerdown", (ev) => { if (ev.target.closest(".rp-mark")) return; dragging = true; scrub.setPointerCapture(ev.pointerId); engine.load(timeAt(ev)); });
    scrub.addEventListener("pointermove", (ev) => { if (dragging && Date.now() - lastSeek > 120) { lastSeek = Date.now(); engine.load(timeAt(ev)); } });
    scrub.addEventListener("pointerup", (ev) => { if (dragging) { dragging = false; engine.load(timeAt(ev)); } });
    const onKey = (ev) => { if (ev.code === "Space" && !/INPUT|SELECT|TEXTAREA|BUTTON/.test(document.activeElement?.tagName || "")) { ev.preventDefault(); engine.toggle(); } };
    document.addEventListener("keydown", onKey);
    onCleanup(() => document.removeEventListener("keydown", onKey));
  }

  function createReplay(host, site, cams, duration) {
    const R = S.replay;
    let playing = false, raf = 0;
    const tiles = cams.map((cam, i) => {
      const el = $(`.tile[data-i="${i}"]`, host);
      const video = $("video", el);
      const tile = { cam, el, video, overlay: new Overlay(video, $("canvas", el)), chunk: null, pending: null };
      tile.overlay.enabled = R.boxes;
      video.addEventListener("loadedmetadata", () => {
        if (tile.pending != null) { video.currentTime = clamp(tile.pending, 0, Math.max(0, video.duration - 0.05)); tile.pending = null; }
        video.playbackRate = R.rate;
        if (playing) video.play().catch(() => {});
      });
      video.addEventListener("waiting", () => el.classList.add("buffering"));
      ["canplay", "playing", "seeked"].forEach((name) => video.addEventListener(name, () => el.classList.remove("buffering")));
      video.addEventListener("error", () => { el.classList.remove("buffering"); el.classList.add("err"); });
      return tile;
    });
    const master = () => tiles.find((x) => !x.el.classList.contains("err") && x.chunk) || tiles[0];
    const timeEl = $("#rpTime", host), fill = $(".rp-fill", host), head = $(".rp-head", host), playBtn = $("#rpPlay", host);
    function paint() {
      const p = clamp(R.t / duration, 0, 1) * 100;
      fill.style.width = p + "%";
      head.style.left = p + "%";
      timeEl.textContent = `${fmtT(R.t)} / ${fmtT(duration)}`;
      $$(".rp-mark", host).forEach((m) => m.classList.toggle("hot", Math.abs(+m.dataset.t - R.t) < 1));
    }
    function load(t) {
      R.t = clamp(t, 0, Math.max(0, duration - 0.05));
      for (const tile of tiles) {
        const ch = chunkAt(site.site_id, tile.cam.camera, R.t);
        if (!ch) continue;
        const local = clamp(R.t - ch.scene_t0, 0, ch.scene_t1 - ch.scene_t0);
        if (tile.chunk !== ch) {
          tile.chunk = ch;
          tile.pending = local;
          tile.el.classList.add("buffering");
          tile.el.classList.remove("err");
          tile.video.src = clipUrl(ch.original_video);
          tile.overlay.dets = null;
          tile.overlay.src = null;
          if (R.boxes) tile.overlay.load(ch.original_video);
        } else if (tile.video.readyState >= 1) {
          tile.video.currentTime = local;
        } else {
          tile.pending = local;
        }
      }
      paint();
    }
    function play() {
      if (R.t >= duration - 0.1) load(0);
      playing = true;
      tiles.forEach((x) => { if (x.video.readyState >= 1) x.video.play().catch(() => {}); });
      playBtn.innerHTML = ICON.pause;
    }
    function pause() {
      playing = false;
      tiles.forEach((x) => x.video.pause());
      playBtn.innerHTML = ICON.play;
    }
    function tick() {
      if (!host.isConnected) return;
      const m = master();
      if (playing && m.chunk && m.video.readyState >= 2 && m.pending == null) {
        const local = m.video.currentTime;
        R.t = m.chunk.scene_t0 + local;
        for (const x of tiles) {
          if (x === m || !x.chunk || x.video.readyState < 1 || x.pending != null) continue;
          const want = R.t - x.chunk.scene_t0;
          if (want < 0 || want > (x.video.duration || 0)) continue;
          if (Math.abs(x.video.currentTime - want) > 0.3) x.video.currentTime = want;
          if (x.video.paused && !x.video.ended) x.video.play().catch(() => {});
        }
        if (m.video.ended || local >= m.chunk.scene_t1 - m.chunk.scene_t0 - 0.06) {
          if (m.chunk.scene_t1 < duration - 0.1) load(m.chunk.scene_t1 + 0.001);
          else { pause(); R.t = duration; }
        }
      }
      paint();
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    onCleanup(() => { cancelAnimationFrame(raf); tiles.forEach((x) => stopVideo(x.video)); });
    return {
      load, play, pause,
      toggle: () => (playing ? pause() : play()),
      setRate(r) { R.rate = r; tiles.forEach((x) => { x.video.playbackRate = r; }); },
      setBoxes(on) {
        R.boxes = on;
        tiles.forEach((x) => { x.overlay.enabled = on; if (on && x.chunk && x.overlay.src !== x.chunk.original_video) x.overlay.load(x.chunk.original_video); });
      },
    };
  }

  // ===================================================================== ask
  const ENGINE_LABEL = { llm: "engine_llm", cosmos: "engine_cosmos", vss_search: "engine_vss_search", vss_agent: "engine_vss_agent", rules: "engine_rules" };

  function renderAsk(el, arg) {
    el.innerHTML = `
      <div class="ask-layout">
        <section class="card chat">
          <div class="card-h"><h2>${ICON.chat}${tr("ask_title")}</h2><span class="muted small">${tr("engine_cosmos")}</span></div>
          <div class="chat-log" id="chatLog"></div>
          <form class="chat-input" id="chatForm" autocomplete="off">
            <input id="chatInput" maxlength="500" placeholder="${esc(tr("ask_ph"))}" aria-label="${esc(tr("ask_ph"))}">
            <button class="btn primary" type="submit">${ICON.send}${tr("send")}</button>
          </form>
        </section>
        <aside class="ask-side">
          <div class="card"><div class="card-h"><h2>${ICON.spark}${tr("suggested")}</h2></div>
            <div class="suggest">${[1, 2, 3, 4, 5].map((i) => `<button type="button" class="suggest-q" data-q="${esc(tr("q" + i))}">${esc(tr("q" + i))}</button>`).join("")}</div></div>
          <div class="card how"><div class="card-h"><h2>${ICON.check}${tr("how_title")}</h2></div>
            <ol><li>${tr("how_1")}</li><li>${tr("how_2")}</li><li>${tr("how_3")}</li></ol></div>
        </aside>
      </div>`;
    renderChat();
    const input = $("#chatInput", el);
    $("#chatForm", el).onsubmit = (ev) => { ev.preventDefault(); askQuestion(input.value); input.value = ""; };
    $$(".suggest-q", el).forEach((b) => { b.onclick = () => askQuestion(b.dataset.q); });
    const timer = setInterval(updatePending, 500);
    onCleanup(() => clearInterval(timer));
    if (arg) {
      history.replaceState(null, "", "#ask");
      const lastUser = [...S.chat].reverse().find((m) => m.role === "user");
      if (lastUser?.text !== arg) askQuestion(arg);
    } else {
      input.focus();
    }
  }

  async function askQuestion(q) {
    q = String(q || "").trim();
    if (!q || S.asking) return;
    S.asking = true;
    S.chat.push({ role: "user", text: q });
    const msg = { role: "bot", pending: true, started: Date.now() };
    S.chat.push(msg);
    renderChat();
    try {
      Object.assign(msg, await api("api/ask", { method: "POST", body: { question: q, lang: S.lang }, timeout: 110000 }), { pending: false });
    } catch (e) {
      Object.assign(msg, { pending: false, error: e.message, question: q });
    }
    S.asking = false;
    renderChat();
  }

  function updatePending() {
    $$(".bubble.pending .phase").forEach((el) => {
      const s = (Date.now() - +el.dataset.started) / 1000;
      el.textContent = `${tr(s < 3 ? "think1" : s < 6 ? "think2" : "think3")} ${Math.floor(s)}s`;
    });
  }

  function clipCard(c, mi, j) {
    const src = c.original_video || c.source;
    const t = c.original_video ? num(c.t) : 0;
    return `<div class="clip" id="clip-${mi}-${j}">
      <div class="clip-media"><video muted playsinline preload="metadata" src="${clipUrl(src)}#t=${(t + 1).toFixed(1)}" data-t="${t}"></video>
        <button type="button" class="clip-play" data-clip="${mi}-${j}" aria-label="Play clip">${ICON.play}</button><span class="clip-n">${j + 1}</span></div>
      <div class="clip-info"><div class="clip-h"><b>${esc(c.site_id || "?")} · ${esc(c.camera || "")}</b>${c.scene_t != null ? `<span class="mono">${fmtT(c.scene_t)}</span>` : ""}<span class="score">${Math.round(num(c.score) * 100)}%</span></div>
        <p>${esc(c.caption || "")}</p></div></div>`;
  }

  function msgHtml(m, i) {
    if (m.role === "user") return `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`;
    const avatar = `<div class="avatar">${ICON.spark}</div>`;
    if (m.pending) return `<div class="msg bot">${avatar}<div class="bubble pending"><span class="dots"><i></i><i></i><i></i></span><span class="phase" data-started="${m.started}">${tr("think1")}</span></div></div>`;
    if (m.error) return `<div class="msg bot">${avatar}<div class="bubble err"><p>${tr("ask_error")} <span class="muted">(${esc(m.error)})</span></p><button type="button" class="btn sm" data-retry="${esc(m.question)}">${tr("retry")}</button></div></div>`;
    const clips = m.clips || [];
    const cite = (id) => {
      const k = /^clip\s?(\d+)$/i.exec(id);
      if (k && clips[+k[1] - 1]) return `<a class="cite cl" href="#ask" data-clip="${i}-${+k[1] - 1}">${ICON.camera}clip ${k[1]}</a>`;
      return idChip(id);
    };
    return `<div class="msg bot">${avatar}<div class="bubble">
      <div class="md">${md(m.answer, cite)}</div>
      <div class="msg-meta"><span class="engine engine-${esc(m.engine)}">${ICON.spark}${tr(ENGINE_LABEL[m.engine] || "engine_rules")}</span><span class="mono">${(num(m.elapsed_ms) / 1000).toFixed(1)} s</span>${(m.notes || []).map((n) => `<span class="muted">${esc(n)}</span>`).join("")}</div>
      ${(m.used || []).length ? `<div class="used"><span class="label">${tr("cited")}</span>${m.used.map((u) => idChip(u.id) || "").join("")}</div>` : ""}
      ${clips.length ? `<div class="label">${tr("clips")}</div><div class="clips">${clips.map((c, j) => clipCard(c, i, j)).join("")}</div>` : ""}
    </div></div>`;
  }

  function renderChat() {
    const log = $("#chatLog");
    if (!log) return;
    $$("video", log).forEach(stopVideo);
    log.innerHTML = S.chat.length ? S.chat.map(msgHtml).join("") : `<div class="chat-empty">${ICON.spark}<p>${esc(tr("ask_welcome"))}</p></div>`;
    $$(".msg.bot .md", log).forEach(linkIds);
    log.onclick = (ev) => {
      const play = ev.target.closest(".clip-play"), cite = ev.target.closest("a.cite.cl"), retry = ev.target.closest("[data-retry]");
      if (retry) { askQuestion(retry.dataset.retry); return; }
      const key = play?.dataset.clip || cite?.dataset.clip;
      if (!key) return;
      ev.preventDefault();
      const card = $(`#clip-${key}`, log);
      if (!card) return;
      const v = $("video", card);
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
      if (play || v.paused) { $(".clip-play", card).hidden = true; v.controls = true; v.currentTime = num(v.dataset.t); v.play().catch(() => {}); }
    };
    log.scrollTop = log.scrollHeight;
    updatePending();
  }

  // ===================================================================== shift report
  function renderReport(el, arg) {
    const P = S.report;
    if (arg) { const [sid, cam] = arg.split("/"); P.site = S.idx.site[sid] ? sid : "all"; P.camera = cam || ""; }
    const site = S.idx.site[P.site];
    if (!site) P.site = "all";
    const cams = site ? camOrder(site) : [];
    if (P.camera && !cams.some((c) => c.camera === P.camera)) P.camera = "";
    el.innerHTML = `
      <div class="report-layout">
        <aside class="card report-ctrl">
          <div class="card-h"><h2>${ICON.doc}${tr("report_scope")}</h2></div>
          <label class="field"><span>${tr("site")}</span><select id="rSite"><option value="all">${tr("all_sites")}</option>${S.idx.sites.map((s) => `<option value="${esc(s.site_id)}"${s.site_id === P.site ? " selected" : ""}>${esc(s.site_id)} — ${esc(s.title || "")}</option>`).join("")}</select></label>
          <label class="field"><span>${tr("camera")}</span><select id="rCam"${site ? "" : " disabled"}><option value="">${tr("all_cams")}</option>${cams.map((c) => `<option value="${esc(c.camera)}"${c.camera === P.camera ? " selected" : ""}>${esc(c.camera)} (${esc(viewLabel(c.view))})</option>`).join("")}</select></label>
          <div class="report-btns"><button type="button" class="btn primary" id="rAi">${ICON.spark}${tr("gen_ai")}</button><button type="button" class="btn" id="rTpl">${ICON.bars}${tr("metrics_only")}</button></div>
          <div id="rStatus" class="r-status"></div>
          <div class="report-btns tools"><button type="button" class="btn ghost" id="rCopy">${ICON.copy}${tr("copy")}</button><button type="button" class="btn ghost" id="rDl">${ICON.download}${tr("download")}</button><button type="button" class="btn ghost" id="rPrint">${ICON.print}${tr("print")}</button></div>
        </aside>
        <article class="card md report-doc" id="rDoc"><div class="skeleton"></div><div class="skeleton short"></div><div class="skeleton"></div></article>
      </div>`;
    const scopeHash = () => history.replaceState(null, "", `#report/${enc(P.site)}${P.camera ? "/" + enc(P.camera) : ""}`);
    $("#rSite", el).onchange = (ev) => { P.site = ev.target.value; P.camera = ""; scopeHash(); runCleanups(); renderReport(el, ""); };
    $("#rCam", el).onchange = (ev) => { P.camera = ev.target.value; scopeHash(); showReports(); };
    $("#rAi", el).onclick = () => loadReport("ai");
    $("#rTpl", el).onclick = () => loadReport("template");
    $("#rCopy", el).onclick = () => { if (P.current) navigator.clipboard?.writeText(P.current.markdown).then(() => toast(tr("copied"))).catch(() => {}); };
    $("#rDl", el).onclick = () => {
      if (!P.current) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([P.current.markdown], { type: "text/markdown" }));
      a.download = `shift-report-${P.site}${P.camera ? "-" + P.camera : ""}.md`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    };
    $("#rPrint", el).onclick = () => window.print();
    showReports();
  }

  const reportKey = (mode) => [S.version, S.report.site, S.report.camera, S.lang, mode].join("|");

  async function showReports() {
    const P = S.report;
    if (P.cache[reportKey("ai")]) { showReport(P.cache[reportKey("ai")]); return; }
    await loadReport("template");
    loadReport("ai");
  }

  async function loadReport(mode) {
    const P = S.report, key = reportKey(mode), scope = reportKey("");
    if (P.cache[key]) { showReport(P.cache[key]); return; }
    const status = $("#rStatus");
    if (mode === "ai" && status) status.innerHTML = `<div class="writing"><div class="spinner"></div>${tr("writing")}</div>`;
    try {
      const res = await api("api/report", { method: "POST", timeout: mode === "ai" ? 130000 : 20000,
        body: { site_id: P.site, camera: P.camera || null, mode, lang: S.lang } });
      if (mode === "ai" && res.engine === "template") {
        if (reportKey("") === scope && $("#rStatus")) $("#rStatus").innerHTML = `<div class="badge warn">${tr("report_fail")}</div>`;
        return;
      }
      if (mode === "template" || res.engine === "llm" || res.engine === "cosmos") P.cache[key] = res;
      if (reportKey("") === scope && S.view === "report") showReport(res);
    } catch (e) {
      if ($("#rStatus") && reportKey("") === scope) $("#rStatus").innerHTML = `<div class="badge warn">${esc(e.message)}</div>`;
    }
  }

  function showReport(res) {
    const doc = $("#rDoc"), status = $("#rStatus");
    if (!doc) return;
    S.report.current = res;
    doc.innerHTML = md(res.markdown, (id) => idChip(id));
    linkIds(doc);
    const engine = { llm: "engine_llm_r", cosmos: "engine_cosmos_r", analyzer: "engine_analyzer" }[res.engine] || "engine_template";
    let badges = `<div class="badge engine-${esc(res.engine)}">${ICON.spark}${tr(engine)}${res.cached ? ` · ${tr("cached")}` : ""}</div>`;
    if (res.engine === "llm" || res.engine === "cosmos") {
      const bad = res.numbers_unverified || [];
      badges += bad.length
        ? `<div class="badge warn">${ICON.alert}${esc(tr("unverified", { n: bad.length, list: bad.join(", ") }))}</div>`
        : `<div class="badge ok">${ICON.check}${esc(tr("verified", { n: res.numbers_checked ?? 0 }))}</div>`;
    }
    if (status) status.innerHTML = badges;
  }

  // ===================================================================== router + boot
  const VIEWS = { overview: renderOverview, alerts: renderAlerts, resources: renderResources, replay: renderReplay, ask: renderAsk, report: renderReport };

  function route() {
    const parts = location.hash.replace(/^#/, "").split("/").map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
    const view = VIEWS[parts[0]] ? parts[0] : "overview";
    S.view = view;
    S.arg = parts.slice(1).join("/");
    $$("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
    runCleanups();
    const el = $("#view");
    el.className = "view view-" + view;
    if (!S.data) { el.innerHTML = loadingHtml(); return; }
    try {
      VIEWS[view](el, S.arg);
    } catch (e) {
      console.error(e);
      el.innerHTML = `<div class="card">${emptyState(ICON.alert, e.message)}</div>`;
    }
    window.scrollTo(0, 0);
  }

  async function poll() {
    try {
      const h = await api("health", { timeout: 8000 });
      setConn(h);
      if (S.version && h.version && h.version !== S.version) {
        await loadAll();
        if (S.view === "overview") { route(); toast(tr("updated")); }
        else toast(tr("updated"), { label: tr("refresh_view"), run: route });
      }
    } catch {
      setConn(null);
    }
  }

  async function boot() {
    applyStatic();
    const clock = $("#clock");
    const tick = () => { clock.textContent = new Date().toLocaleTimeString(S.lang === "zh" ? "zh-CN" : "en-GB", { hour12: false }); };
    tick();
    setInterval(tick, 1000);
    $$(".lang button").forEach((b) => {
      b.onclick = () => { if (S.lang === b.dataset.lang) return; S.lang = b.dataset.lang; saved.set("lang", S.lang); applyStatic(); route(); };
    });
    window.addEventListener("hashchange", route);
    route();
    try {
      await loadAll();
    } catch (e) {
      $("#view").innerHTML = `<div class="card error-card">${emptyState(ICON.alert, `${tr("error_load")} (${e.message})`)}<button type="button" class="btn primary" onclick="location.reload()">${tr("retry")}</button></div>`;
      return;
    }
    route();
    poll();
    setInterval(poll, 15000);
  }

  boot();
})();
