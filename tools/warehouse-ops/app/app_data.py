"""Analyzer data files: DATA_DIR resolution, mtime-based hot reload, lookup indexes and overview KPIs.

The five data_*.json files follow the shared data contract. Every accessor tolerates missing
files, extra fields and nulls, because the analyzer rewrites the files while the app runs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any

log = logging.getLogger("wops.data")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FILES = {
    "videos": ("data_videos.json", dict),
    "segments": ("data_segments.json", list),
    "events": ("data_events.json", list),
    "utilization": ("data_utilization.json", dict),
    "recommendations": ("data_recommendations.json", dict),
}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
FLAG_PRIORITY = {"bottleneck": 0, "congestion": 1, "labor_surplus": 2, "machine_surplus": 3, "underused_zone": 4}
_TIMESTAMP_PREFIX = re.compile(r"^\d{8}_\d{6}_")


def resolve_data_dir() -> str:
    env = os.environ.get("DATA_DIR")
    if env:
        return os.path.abspath(env)
    if os.path.exists(os.path.join(APP_DIR, "data_videos.json")):
        return APP_DIR
    return os.path.normpath(os.path.join(APP_DIR, "..", "mock_data"))


def basename(uri: str | None) -> str:
    return (uri or "").rsplit("/", 1)[-1]


def stable_chunk_name(filename_or_uri: str | None) -> str:
    """Chunk file name without the upload timestamp prefix; survives a re-ingest of the same video."""
    return _TIMESTAMP_PREFIX.sub("", basename(filename_or_uri))


def num(x: Any, default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def dicts(items: Any) -> list[dict]:
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


class Snapshot:
    """One consistent load of the data files plus lookup indexes. Treat as read-only."""

    def __init__(self, raw: dict[str, Any], data_dir: str, version: str) -> None:
        self.data_dir = data_dir
        self.version = version
        self.videos: dict = raw.get("videos") if isinstance(raw.get("videos"), dict) else {}
        util = raw.get("utilization") if isinstance(raw.get("utilization"), dict) else {}
        recs = raw.get("recommendations") if isinstance(raw.get("recommendations"), dict) else {}
        self.sites = dicts(self.videos.get("sites"))
        self.segments = dicts(raw.get("segments"))
        self.events = sorted(dicts(raw.get("events")), key=lambda e: (
            SEVERITY_RANK.get(e.get("severity"), 3), -num(e.get("confidence"))))
        self.util_cameras = dicts(util.get("cameras"))
        self.flags = dicts(util.get("flags"))
        self.recommendations_doc = recs
        self.recommendations = dicts(recs.get("recommendations"))
        self.shift_report_md = recs.get("shift_report_md") or ""
        mock = bool(self.videos.get("mock")) or os.path.basename(data_dir.rstrip("\\/")) == "mock_data"
        self.kind = "mock" if mock else "real"
        self._build_indexes()

    def _build_indexes(self) -> None:
        self.site_by_id: dict[str, dict] = {}
        self.camera_meta: dict[tuple[str, str], dict] = {}
        self.chunk_by_video: dict[str, dict] = {}
        self.chunk_by_stable: dict[str, dict] = {}
        self.seg_by_source: dict[str, dict] = {}
        self.seg_by_id: dict[str, dict] = {}
        for site in self.sites:
            sid = str(site.get("site_id") or "")
            self.site_by_id[sid] = site
            for cam in dicts(site.get("cameras")):
                cname = str(cam.get("camera") or "")
                self.camera_meta[(sid, cname)] = {"site_id": sid, "camera": cname, "view": cam.get("view") or ""}
                for ch in dicts(cam.get("chunks")):
                    video = ch.get("original_video") or ""
                    ref = {"site_id": sid, "camera": cname, "view": cam.get("view") or "",
                           "chunk_index": ch.get("chunk_index"), "original_video": video,
                           "filename": ch.get("filename") or basename(video),
                           "scene_t0": num(ch.get("scene_t0")), "scene_t1": num(ch.get("scene_t1")),
                           "segments": dicts(ch.get("segments"))}
                    if video:
                        self.chunk_by_video[video] = ref
                        self.chunk_by_stable[stable_chunk_name(ref["filename"])] = ref
                    for seg in ref["segments"]:
                        sref = {"seg_id": f"{sid}|{cname}|{ch.get('chunk_index')}|{seg.get('n')}",
                                "site_id": sid, "camera": cname, "chunk_index": ch.get("chunk_index"),
                                "n": seg.get("n"), "source": seg.get("source") or "",
                                "scene_t0": num(seg.get("scene_t0")), "scene_t1": num(seg.get("scene_t1")),
                                "original_video": video, "filename": ref["filename"],
                                "chunk_scene_t0": ref["scene_t0"]}
                        self.seg_by_id[sref["seg_id"]] = sref
                        if sref["source"]:
                            self.seg_by_source[sref["source"]] = sref
        self.segment_row_by_id = {str(s.get("seg_id")): s for s in self.segments if s.get("seg_id")}
        for row in self.segments:  # segments missing from data_videos still get playable refs
            src = row.get("source")
            if src and src not in self.seg_by_source:
                chunk = self.chunk_by_video.get(row.get("original_video") or "")
                self.seg_by_source[src] = {
                    "seg_id": row.get("seg_id"), "site_id": row.get("site_id"), "camera": row.get("camera"),
                    "chunk_index": row.get("chunk_index"), "n": row.get("n"), "source": src,
                    "scene_t0": num(row.get("scene_t0")), "scene_t1": num(row.get("scene_t1")),
                    "original_video": row.get("original_video") or "",
                    "filename": chunk["filename"] if chunk else basename(row.get("original_video")),
                    "chunk_scene_t0": chunk["scene_t0"] if chunk else num(row.get("scene_t0"))}
        self.event_by_id = {str(e.get("event_id")): e for e in self.events if e.get("event_id")}
        self.flag_by_id = {str(f.get("flag_id")): f for f in self.flags if f.get("flag_id")}
        self.rec_by_id = {str(r.get("rec_id")): r for r in self.recommendations if r.get("rec_id")}
        known = set(self.seg_by_source) | set(self.chunk_by_video)
        for e in self.events:
            known.update(x for x in (e.get("source"), e.get("original_video")) if x)
            known.update(v.get("source") for v in dicts(e.get("views")) if v.get("source"))
        for row in self.segments:
            known.update(x for x in (row.get("source"), row.get("original_video")) if x)
        self.known_sources = known

    # ------------------------------------------------------------------ helpers
    def site_kind(self, site_id: str) -> str:
        site = self.site_by_id.get(site_id) or {}
        kind = site.get("kind")
        if kind in ("continuous", "scenario"):
            return kind
        return "scenario" if num(site.get("duration_sec"), 0) and num(site.get("duration_sec")) <= 60 else "continuous"

    def site_title(self, site_id: str) -> str:
        return str((self.site_by_id.get(site_id) or {}).get("title") or site_id)

    def chunk_at(self, site_id: str, camera: str, scene_t: float) -> dict | None:
        best = None
        for ref in self.chunk_by_video.values():
            if ref["site_id"] == site_id and ref["camera"] == camera:
                if ref["scene_t0"] <= scene_t < ref["scene_t1"]:
                    return ref
                best = best or ref
        return best

    def util_for(self, site_id: str | None = None, camera: str | None = None) -> list[dict]:
        return [c for c in self.util_cameras
                if (not site_id or c.get("site_id") == site_id) and (not camera or c.get("camera") == camera)]


class DataStore:
    """Owns the current Snapshot; reloads files whose mtime/size changed (throttled)."""

    def __init__(self, min_interval: float = 1.5) -> None:
        self._lock = threading.Lock()
        self._min_interval = min_interval
        self._checked_at = 0.0
        self._stamps: dict[str, tuple[int, int]] = {}
        self._raw: dict[str, Any] = {k: kind() for k, (_, kind) in FILES.items()}
        self._dir = ""
        self._snap = Snapshot(self._raw, resolve_data_dir(), "empty")
        self.changed_at = time.time()

    def snapshot(self) -> Snapshot:
        self.refresh()
        return self._snap

    def refresh(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._checked_at < self._min_interval:
            return
        with self._lock:
            if not force and now - self._checked_at < self._min_interval:
                return
            self._checked_at = now
            data_dir = resolve_data_dir()
            if data_dir != self._dir:
                log.info("data directory: %s", data_dir)
                self._dir, self._stamps = data_dir, {}
                self._raw = {k: kind() for k, (_, kind) in FILES.items()}
            changed = False
            for key, (name, kind) in FILES.items():
                path = os.path.join(data_dir, name)
                try:
                    st = os.stat(path)
                except OSError:
                    if key in self._stamps:
                        self._stamps.pop(key)
                        self._raw[key] = kind()
                        changed = True
                    continue
                stamp = (st.st_mtime_ns, st.st_size)
                if self._stamps.get(key) == stamp:
                    continue
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        value = json.load(f)
                except (OSError, ValueError) as e:  # half-written file: keep the previous copy, retry later
                    log.warning("could not load %s (%s); keeping previous copy", name, type(e).__name__)
                    continue
                self._raw[key] = value if isinstance(value, kind) else kind()
                self._stamps[key] = stamp
                changed = True
            if changed or self._snap.version == "empty":
                blob = json.dumps([data_dir, sorted(self._stamps.items())]).encode()
                version = hashlib.sha1(blob).hexdigest()[:12]
                self._snap = Snapshot(self._raw, data_dir, version)
                self.changed_at = now
                log.info("loaded data version %s (%s): %d sites, %d segments, %d events, %d flags",
                         version, self._snap.kind, len(self._snap.sites), len(self._snap.segments),
                         len(self._snap.events), len(self._snap.flags))


# ---------------------------------------------------------------------- overview
def _last(series: list[dict], key: str) -> float:
    return num(series[-1].get(key)) if series else 0.0


def _flag_strength(flag: dict) -> float:
    metric = flag.get("metric") or {}
    value, threshold = num(metric.get("value")), num(metric.get("threshold"))
    if not threshold:
        return 0.0
    return abs(value - threshold) / abs(threshold)


def ranked_flags(snap: Snapshot) -> list[dict]:
    return sorted(snap.flags, key=lambda f: (-_flag_strength(f), FLAG_PRIORITY.get(f.get("type"), 9)))


def camera_cards(snap: Snapshot) -> list[dict]:
    events_by_cam: dict[tuple[str, str], list[dict]] = {}
    for e in snap.events:
        cams = {e.get("camera")} | {v.get("camera") for v in dicts(e.get("views"))}
        for cam in cams:
            events_by_cam.setdefault((e.get("site_id"), cam), []).append(e)
    flags_by_cam: dict[tuple[str, str], list[dict]] = {}
    for f in snap.flags:
        flags_by_cam.setdefault((f.get("site_id"), f.get("camera")), []).append(f)
    cards = []
    for c in snap.util_cameras:
        key = (c.get("site_id"), c.get("camera"))
        series = dicts(c.get("series"))
        totals = c.get("totals") or {}
        evs = events_by_cam.get(key, [])
        status = "alert" if any(e.get("severity") == "high" for e in evs) else (
            "warn" if evs or flags_by_cam.get(key) else "ok")
        cards.append({
            "site_id": key[0], "camera": key[1], "view": c.get("view") or snap.camera_meta.get(key, {}).get("view"),
            "kind": snap.site_kind(key[0]), "status": status,
            "people_now": _last(series, "people"), "idle_now": _last(series, "idle"),
            "machines_moving_now": _last(series, "machines_moving"), "machines_total_now": _last(series, "machines_total"),
            "people_avg": num(totals.get("people_avg")), "idle_ratio": num(totals.get("idle_ratio")),
            "machine_moving_ratio": num(totals.get("machine_moving_ratio")),
            "spark_people": [num(p.get("people")) for p in series],
            "spark_idle": [num(p.get("idle")) for p in series],
            "spark_machines": [num(p.get("machines_moving")) for p in series],
            "event_ids": [e.get("event_id") for e in evs], "flag_ids": [f.get("flag_id") for f in flags_by_cam.get(key, [])],
        })
    return cards


THUMBS_JSON, THUMBS_JPG = "data_thumbs.json", "data_thumbs.jpg"
SEV_ORDER = ("high", "medium", "low")
VIEW_CONFIRM = 0.5  # a synchronized view only counts as showing an event when its own label is this confident


def _thumbs(data_dir: str) -> dict:
    try:
        with open(os.path.join(data_dir, THUMBS_JSON), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) and os.path.exists(os.path.join(data_dir, THUMBS_JPG)) else {}


def library(snap: Snapshot) -> dict:
    """One row per indexed video (chunk) with its analysis coverage and headline metrics."""
    rows_by_video: dict[str, list[dict]] = {}
    for row in snap.segments:
        rows_by_video.setdefault(row.get("original_video") or "", []).append(row)
    events_by_video: dict[str, list[dict]] = {}
    for e in snap.events:
        videos = {e.get("original_video")}
        videos |= {(snap.seg_by_source.get(v.get("source") or "") or {}).get("original_video") for v in dicts(e.get("views"))
                   if v.get("label") not in (None, "", "none") and num(v.get("confidence")) >= VIEW_CONFIRM}
        for video in videos - {None, ""}:
            events_by_video.setdefault(video, []).append(e)
    thumbs = _thumbs(snap.data_dir)
    tiles = thumbs.get("tiles") or {}

    items = []
    for site in sorted(snap.sites, key=lambda s: snap.site_kind(str(s.get("site_id"))) != "continuous"):
        sid = str(site.get("site_id") or "")
        for cam in dicts(site.get("cameras")):
            cname = str(cam.get("camera") or "")
            for ch in sorted(dicts(cam.get("chunks")), key=lambda c: num(c.get("scene_t0"))):
                video = ch.get("original_video") or ""
                rows = rows_by_video.get(video, [])
                people = [r.get("people") or {} for r in rows]
                idle = sum(num(p.get("idle")) for p in people)
                moving = sum(num(p.get("moving")) for p in people)
                machines = [r.get("machines") or {} for r in rows]
                m_total = [sum(num((m.get(k) or {}).get("total")) for k in m) for m in machines]
                m_moving = [sum(num((m.get(k) or {}).get("moving")) for k in m) for m in machines]
                t0, t1 = num(ch.get("scene_t0")), num(ch.get("scene_t1"))
                evs = events_by_video.get(video, [])
                flags = [f for f in snap.flags if f.get("site_id") == sid and f.get("camera") == cname
                         and num(f.get("scene_t0")) < t1 and num(f.get("scene_t1")) > t0]
                filename = ch.get("filename") or basename(video)
                items.append({
                    "site_id": sid, "site_title": snap.site_title(sid), "kind": snap.site_kind(sid),
                    "camera": cname, "view": cam.get("view") or "", "chunk_index": ch.get("chunk_index"),
                    "original_video": video, "filename": filename, "scene_t0": t0, "scene_t1": t1,
                    "segments_total": len(dicts(ch.get("segments"))), "segments_analyzed": len(rows),
                    "people_avg": round(sum(num(p.get("per_frame_mean", p.get("per_frame_median"))) for p in people)
                                        / len(people), 1) if people else None,
                    "idle_ratio": round(idle / (idle + moving), 3) if idle + moving else None,
                    "machines_avg": round(sum(m_total) / len(m_total), 1) if m_total else None,
                    "machines_moving_avg": round(sum(m_moving) / len(m_moving), 1) if m_moving else None,
                    "event_ids": [e.get("event_id") for e in evs],
                    "max_severity": next((s for s in SEV_ORDER if any(e.get("severity") == s for e in evs)), None),
                    "flag_ids": [f.get("flag_id") for f in flags],
                    "caption": next((str(r.get("vlm_summary")) for r in rows if r.get("vlm_summary")), ""),
                    "thumb": tiles.get(filename),
                })
    return {
        "version": snap.version,
        "summary": {"videos": len(items), "cameras": len({(i["site_id"], i["camera"]) for i in items}),
                    "sites": len(snap.sites), "segments": sum(i["segments_total"] for i in items),
                    "segments_analyzed": sum(i["segments_analyzed"] for i in items),
                    "minutes": round(sum(i["scene_t1"] - i["scene_t0"] for i in items) / 60, 1),
                    "with_events": sum(bool(i["event_ids"]) for i in items)},
        "thumbs": ({k: thumbs.get(k) for k in ("tile_w", "tile_h", "cols", "rows")} if tiles else None),
        "items": items,
    }


def thumbs_path(snap: Snapshot) -> str | None:
    path = os.path.join(snap.data_dir, THUMBS_JPG)
    return path if os.path.exists(path) else None


def overview(snap: Snapshot) -> dict:
    cards = camera_cards(snap)
    floor = [c for c in cards if c["kind"] == "continuous"] or cards
    floor_util = [c for c in snap.util_cameras if snap.site_kind(c.get("site_id")) == "continuous"] or snap.util_cameras
    person_s = sum(num((c.get("totals") or {}).get("person_seconds")) for c in floor_util)
    idle_s = sum(num((c.get("totals") or {}).get("idle_person_seconds")) for c in floor_util)
    m_total = sum(num(p.get("machines_total")) for c in floor_util for p in dicts(c.get("series")))
    m_moving = sum(num(p.get("machines_moving")) for c in floor_util for p in dicts(c.get("series")))
    now_t = max((num(dicts(c.get("series"))[-1].get("scene_t1")) for c in floor_util if dicts(c.get("series"))),
                default=0.0)
    alerts = {"high": 0, "medium": 0, "low": 0}
    by_type: dict[str, int] = {}
    for e in snap.events:
        sev = e.get("severity") if e.get("severity") in alerts else "low"
        alerts[sev] += 1
        by_type[str(e.get("type"))] = by_type.get(str(e.get("type")), 0) + 1
    video_sec = sum(num(s.get("duration_sec")) * len(dicts(s.get("cameras"))) for s in snap.sites)
    return {
        "data_dir_kind": snap.kind, "version": snap.version,
        "generated_at": snap.videos.get("generated_at") or snap.recommendations_doc.get("generated_at"),
        "kpis": {
            "people_now": round(sum(c["people_now"] for c in floor), 1),
            "people_avg": round(sum(c["people_avg"] for c in floor), 1),
            "now_scene_t": now_t,
            "idle_ratio": round(idle_s / person_s, 3) if person_s else 0.0,
            "idle_person_minutes": round(idle_s / 60, 1),
            "machines_active_now": round(sum(c["machines_moving_now"] for c in floor), 1),
            "machines_total_now": round(sum(c["machines_total_now"] for c in floor), 1),
            "machine_moving_ratio": round(m_moving / m_total, 3) if m_total else 0.0,
            "alerts": {**alerts, "total": sum(alerts.values()), "by_type": by_type},
            "flags": len(snap.flags),
            "cameras": len(snap.util_cameras) or len(snap.camera_meta),
            "sites": len(snap.sites),
            "segments": len(snap.segments),
            "video_minutes": round(video_sec / 60, 1),
            "floor_cameras": len(floor),
        },
        "cameras": cards,
        "alerts": [{k: e.get(k) for k in ("event_id", "type", "severity", "confidence", "site_id", "camera",
                                          "scene_t", "title")} for e in snap.events[:12]],
        "top_flags": ranked_flags(snap)[:5],
        "top_recommendations": snap.recommendations[:3],
    }
