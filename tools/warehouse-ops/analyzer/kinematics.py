"""People kinematics from YOLO sidecars.

IoU tracker with short-gap re-identification, speeds in m/s using the person's own box height as a
ruler (~1.7 m), per-frame idle/moving classification, evasive motion, occlusion gaps, posture, zone
occupancy and class-agnostic machine hints. Everything works on image coordinates of one camera.
"""
from __future__ import annotations

import bisect
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field

PERSON_HEIGHT_M = 1.7
PERSON_CONF = 0.35
IDLE_MPS = 0.25
SLOW_MPS = 0.5
MIN_TRACK_SEC = 2.0
MIN_CLASSIFY_SEC = 0.6
IOU_MATCH = 0.3
IOU_GAP_SEC = 0.34
REID_GAP_SEC = 2.0
OCCLUSION_MIN_SEC = 0.3
EVASIVE_MPS = 1.5
EVASIVE_WINDOW_SEC = 1.0
STANDSTILL_MPS = 0.4          # tolerance for "idle" on the noisier short-window speed
MAX_PLAUSIBLE_MPS = 4.0       # faster short-window speeds are tracking artifacts (ID switches)
FALL_ASPECT = 1.2
FALL_MIN_SEC = 0.5
MACHINE_CONF = 0.3
MACHINE_AREA = (0.0004, 0.6)  # fraction of the frame
PROXIMITY_KEEP_M = 2.0
GRID_COLS, GRID_ROWS = 4, 3
EDGE_PX = 3


def iou(a, b) -> float:
    inter = _inter(a, b)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _inter(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def foot(b) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, b[3]


@dataclass
class Track:
    tid: int
    t: list[float] = field(default_factory=list)
    boxes: list[list[float]] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)

    def add(self, t: float, box) -> None:
        self.t.append(t)
        self.boxes.append(box)

    @property
    def duration(self) -> float:
        return self.t[-1] - self.t[0]

    def ref_height(self) -> float:
        return max(1.0, statistics.median(b[3] - b[1] for b in self.boxes[-15:]))


def person_boxes(frame: dict) -> list:
    return [d["bbox"] for d in frame["detections"] if d["label"] == "person" and d["confidence"] >= PERSON_CONF]


def track_people(frames: list[dict]) -> list[Track]:
    tracks: list[Track] = []
    for f in frames:
        t = f["time_sec"]
        dets = person_boxes(f)
        live = [tr for tr in tracks if t - tr.t[-1] <= REID_GAP_SEC]
        used_tr: set[int] = set()
        used_det: set[int] = set()

        pairs = sorted(((iou(tr.boxes[-1], b), ti, di) for ti, tr in enumerate(live) if t - tr.t[-1] <= IOU_GAP_SEC
                        for di, b in enumerate(dets)), reverse=True)
        for score, ti, di in pairs:
            if score < IOU_MATCH:
                break
            if ti not in used_tr and di not in used_det:
                live[ti].add(t, dets[di])
                used_tr.add(ti)
                used_det.add(di)

        # Re-identify after a short gap: nearby foot point, similar size, distance bounded by gap length.
        cands = []
        for ti, tr in enumerate(live):
            if ti in used_tr:
                continue
            gap, h = t - tr.t[-1], tr.ref_height()
            fx, fy = foot(tr.boxes[-1])
            for di, b in enumerate(dets):
                if di in used_det or not 0.6 <= (b[3] - b[1]) / h <= 1.6:
                    continue
                bx, by = foot(b)
                dist_m = math.hypot(bx - fx, by - fy) / h * PERSON_HEIGHT_M
                if dist_m <= 0.8 + 2.0 * gap:
                    cands.append((dist_m, ti, di, gap))
        for dist_m, ti, di, gap in sorted(cands):
            if ti in used_tr or di in used_det:
                continue
            tr = live[ti]
            if gap >= OCCLUSION_MIN_SEC:
                tr.gaps.append({"t_lost": round(tr.t[-1], 2), "t_found": round(t, 2), "gap_sec": round(gap, 2),
                                "dist_m": round(dist_m, 2)})
            tr.add(t, dets[di])
            used_tr.add(ti)
            used_det.add(di)

        for di, b in enumerate(dets):
            if di not in used_det:
                tracks.append(Track(len(tracks), [t], [b]))
    return tracks


def _window(ts: list[float], i: int, half: float) -> tuple[int, int]:
    return bisect.bisect_left(ts, ts[i] - half - 1e-6), bisect.bisect_right(ts, ts[i] + half + 1e-6) - 1


def track_kinematics(tr: Track, width: int, height: int) -> dict:
    """Per-sample speeds (1 s and ~0.33 s windows) on foot points, using local box height as the ruler."""
    n = len(tr.t)

    def ruler_ok(b) -> bool:  # side truncation does not change box height
        return b[1] > EDGE_PX and b[3] < height - EDGE_PX

    def foot_ok(b) -> bool:
        return b[3] < height - EDGE_PX

    ruler_idx = [i for i, b in enumerate(tr.boxes) if ruler_ok(b)]
    ruler = statistics.median(tr.boxes[i][3] - tr.boxes[i][1] for i in ruler_idx) \
        if len(ruler_idx) >= max(5, 0.3 * n) else None

    # Smoothed foot points on the foot-valid subsequence.
    vi = [i for i, b in enumerate(tr.boxes) if foot_ok(b)]
    vt = [tr.t[i] for i in vi]
    raw = [foot(tr.boxes[i]) for i in vi]
    pts = []
    for k in range(len(vi)):
        lo, hi = max(0, k - 2), min(len(vi), k + 3)
        pts.append((sum(p[0] for p in raw[lo:hi]) / (hi - lo), sum(p[1] for p in raw[lo:hi]) / (hi - lo)))

    rt = [tr.t[i] for i in ruler_idx]
    rh = [tr.boxes[i][3] - tr.boxes[i][1] for i in ruler_idx]

    def local_h(t: float) -> float | None:
        lo, hi = bisect.bisect_left(rt, t - 0.5), bisect.bisect_right(rt, t + 0.5)
        return statistics.median(rh[lo:hi]) if hi > lo else ruler

    v_local: list[float | None] = [None] * n
    v_short: list[float | None] = [None] * n
    if ruler is not None:
        for k, i in enumerate(vi):
            h = local_h(vt[k])
            if not h:
                continue
            lo, hi = _window(vt, k, 0.5)
            if vt[hi] - vt[lo] >= 0.5:
                v = math.dist(pts[hi], pts[lo]) / (vt[hi] - vt[lo]) / h * PERSON_HEIGHT_M
                v_local[i] = v if v <= MAX_PLAUSIBLE_MPS else None
            lo, hi = _window(vt, k, 1 / 6)
            if vt[hi] - vt[lo] >= 0.25:
                hb = [tr.boxes[vi[j]][3] - tr.boxes[vi[j]][1] for j in (lo, hi)]
                if all(abs(x / h - 1) < 0.25 for x in hb):
                    v = math.dist(pts[hi], pts[lo]) / (vt[hi] - vt[lo]) / h * PERSON_HEIGHT_M
                    v_short[i] = v if v <= MAX_PLAUSIBLE_MPS else None

    speeds = [v for v in v_local if v is not None]
    return {
        "ruler_px": ruler,
        "v_local": v_local,
        "v_short": v_short,
        "mean_speed": statistics.fmean(speeds) if speeds else None,
        "classifiable": ruler is not None and tr.duration >= MIN_CLASSIFY_SEC,
        "evasive": _evasive(tr.t, v_short),
        "posture": _posture(tr, ruler, ruler_ok),
    }


def _evasive(ts: list[float], v_short: list[float | None]) -> list[dict]:
    """Standstill (>= 0.5 s) followed within EVASIVE_WINDOW_SEC by a speed spike above EVASIVE_MPS."""
    events, still_start, still_end, last_still = [], None, None, None
    i = 0
    while i < len(ts):
        v, t = v_short[i], ts[i]
        if v is None:
            i += 1
            continue
        if v < STANDSTILL_MPS:
            if still_start is None or (last_still is not None and t - last_still > 0.2):
                still_start = t
            last_still = t
            if t - still_start >= 0.5:
                still_end = (still_start, t)
        elif v > EVASIVE_MPS and still_end and t - still_end[1] <= EVASIVE_WINDOW_SEC:
            j = bisect.bisect_right(ts, t + 1.0)
            peak = max(x for x in v_short[i:j] if x is not None)
            events.append({"t": round(t, 2), "onset_t": round(still_end[1], 2), "peak_mps": round(peak, 2),
                           "standstill_sec": round(still_end[1] - still_end[0], 2)})
            still_start = still_end = last_still = None
            i = j
            continue
        i += 1
    return events


def _posture(tr: Track, ruler: float | None, ruler_ok) -> list[dict]:
    """Wide boxes (w/h > FALL_ASPECT) sustained for FALL_MIN_SEC => possible fall."""
    episodes, run = [], []
    for t, b in zip(tr.t, tr.boxes):
        w, h = b[2] - b[0], b[3] - b[1]
        if ruler_ok(b) and h > 0 and w / h > FALL_ASPECT and (not run or t - run[-1][0] <= 0.1):
            run.append((t, w / h, h))
            continue
        if run and run[-1][0] - run[0][0] >= FALL_MIN_SEC:
            episodes.append(run)
        run = [(t, w / h, h)] if ruler_ok(b) and h > 0 and w / h > FALL_ASPECT else []
    if run and run[-1][0] - run[0][0] >= FALL_MIN_SEC:
        episodes.append(run)
    return [{"t0": round(e[0][0], 2), "t1": round(e[-1][0], 2), "max_aspect": round(max(x[1] for x in e), 2),
             "min_height_ratio": round(min(x[2] for x in e) / ruler, 2) if ruler else None} for e in episodes]


def _cell(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    col = min(GRID_COLS - 1, max(0, int(x / width * GRID_COLS)))
    row = min(GRID_ROWS - 1, max(0, int(y / height * GRID_ROWS)))
    return col, row


def _grid() -> list[list[float]]:
    return [[0.0] * GRID_COLS for _ in range(GRID_ROWS)]


def machine_hints(frames: list[dict], width: int, height: int) -> dict:
    """Class-agnostic non-person boxes (labels are unreliable on AGVs/forklifts): tracks, motion, proximity."""
    img_area = float(width * height)
    tracks: list[dict] = []
    per_frame, near_pairs = [], []
    for f in frames:
        t = f["time_sec"]
        persons = person_boxes(f)
        hints = []
        for d in f["detections"]:
            if d["label"] == "person" or d["confidence"] < MACHINE_CONF:
                continue
            b = d["bbox"]
            w, h = b[2] - b[0], b[3] - b[1]
            if w <= 0 or h <= 0 or not MACHINE_AREA[0] <= w * h / img_area <= MACHINE_AREA[1] or not 0.2 <= w / h <= 8:
                continue
            if any(_inter(b, p) / (w * h) > 0.6 for p in persons):
                continue  # bag/accessory carried by a person
            hints.append((b, d["label"]))
        per_frame.append(len(hints))

        for b, label in hints:
            best, best_tr = 0.2, None
            for tr in tracks:
                if 0 < t - tr["t"][-1] <= 0.5:
                    s = iou(tr["boxes"][-1], b)
                    if s > best:
                        best, best_tr = s, tr
            if best_tr is None:
                best_tr = {"t": [], "boxes": [], "labels": Counter()}
                tracks.append(best_tr)
            best_tr["t"].append(t)
            best_tr["boxes"].append(b)
            best_tr["labels"][label] += 1

            for p in persons:
                ph = p[3] - p[1]
                if ph < 20:
                    continue
                fx, fy = foot(p)
                dx, dy = max(b[0] - fx, 0, fx - b[2]), max(b[1] - fy, 0, fy - b[3])
                dist_m = math.hypot(dx, dy) / ph * PERSON_HEIGHT_M
                if dist_m < PROXIMITY_KEEP_M:
                    near_pairs.append((t, dist_m, fx / width, label, id(best_tr)))

    def center(boxes):
        return (statistics.fmean((b[0] + b[2]) / 2 for b in boxes), statistics.fmean((b[1] + b[3]) / 2 for b in boxes))

    kept, moving_ids = [], set()
    for tr in tracks:
        if len(tr["t"]) < 6 or tr["t"][-1] - tr["t"][0] < 0.5:
            continue
        k = max(1, len(tr["boxes"]) // 4)
        c0, c1 = center(tr["boxes"][:k]), center(tr["boxes"][-k:])
        size = math.sqrt(statistics.median((b[2] - b[0]) * (b[3] - b[1]) for b in tr["boxes"]))
        moving = math.dist(c0, c1) / size >= 0.5
        if moving:
            moving_ids.add(id(tr))
        kept.append({"t0": tr["t"][0], "t1": tr["t"][-1], "moving": moving,
                     "x": round(c1[0] / width, 2), "label": tr["labels"].most_common(1)[0][0]})
    labels = Counter(k["label"] for k in kept)

    # Person proximity only to MOVING non-person tracks (static clutter next to people is not a hazard).
    prox: dict[float, dict] = {}
    for t, dist_m, x, label, tid in near_pairs:
        key = round(math.floor(t * 2) / 2, 1)
        if tid in moving_ids and dist_m < prox.get(key, {"d_m": 9e9})["d_m"]:
            prox[key] = {"t": key, "d_m": round(dist_m, 2), "x": round(x, 2), "label": label}
    return {
        "tracks": len(kept),
        "moving": sum(1 for k in kept if k["moving"]),
        "frames_frac": round(sum(1 for c in per_frame if c) / max(1, len(per_frame)), 2),
        "max_simultaneous": max(per_frame, default=0),
        "labels": dict(labels.most_common(3)),
        "track_list": kept,
        "proximity": sorted(prox.values(), key=lambda p: p["t"]),
    }


def analyze(frames: list[dict], width: int, height: int) -> dict:
    """Full kinematic summary for a sequence of sidecar frames (one segment or concatenated segments)."""
    n_frames = max(1, len(frames))
    tracks = track_people(frames)
    kins = [track_kinematics(tr, width, height) for tr in tracks]
    frame_of = {round(f["time_sec"], 3): i for i, f in enumerate(frames)}

    people = [0] * len(frames)
    idle = [0] * len(frames)
    moving = [0] * len(frames)
    occ, z_idle, z_moving, z_slow = _grid(), _grid(), _grid(), _grid()
    z_speed_sum, z_speed_n, z_move_sum = _grid(), _grid(), _grid()
    duration = frames[-1]["time_sec"] - frames[0]["time_sec"] if frames else 0.0
    t_start = frames[0]["time_sec"] if frames else 0.0
    timeline: list[float | None] = [None] * max(1, math.ceil(duration + 1e-6))

    for tr, k in zip(tracks, kins):
        for i, (t, b) in enumerate(zip(tr.t, tr.boxes)):
            fi = frame_of.get(round(t, 3))
            if fi is None:
                continue
            people[fi] += 1
            col, row = _cell(*foot(b), width, height)
            occ[row][col] += 1
            v = k["v_local"][i] if k["classifiable"] else None
            if v is None:
                continue
            if v < IDLE_MPS:
                idle[fi] += 1
                z_idle[row][col] += 1
            else:
                moving[fi] += 1
                z_moving[row][col] += 1
                z_move_sum[row][col] += v
            if v < SLOW_MPS:
                z_slow[row][col] += 1
            z_speed_sum[row][col] += v
            z_speed_n[row][col] += 1
            b_idx = min(len(timeline) - 1, int(t - t_start))
            timeline[b_idx] = max(v, timeline[b_idx] or 0.0)

    long_tracks = [(tr, k) for tr, k in zip(tracks, kins) if tr.duration >= MIN_TRACK_SEC]
    rated = [(tr.duration, k["mean_speed"]) for tr, k in long_tracks if k["mean_speed"] is not None]
    people_pf = sum(people) / n_frames
    classified = (sum(idle) + sum(moving)) / n_frames
    idle_ratio = sum(idle) / (sum(idle) + sum(moving)) if classified else 0.0
    # idle/moving are scaled to every detected person using the classified share, so they add up to the head count.
    idle_pf = people_pf * idle_ratio if classified else 0.0

    def norm(grid):
        return [[round(v / n_frames, 2) for v in row] for row in grid]

    main = max(zip(tracks, kins), key=lambda p: len(p[0].t), default=None)
    return {
        "people": {
            "per_frame_median": statistics.median(people) if people else 0,
            "per_frame_max": max(people, default=0),
            "tracks": len(long_tracks),
            "idle": round(idle_pf, 2),
            "moving": round(people_pf - idle_pf, 2) if classified else 0.0,
            "idle_ratio": round(idle_ratio, 3),
            "mean_speed_mps": round(sum(d * v for d, v in rated) / sum(d for d, _ in rated), 2) if rated else 0.0,
            "per_frame_mean": round(people_pf, 2),
            "classified_share": round(classified / people_pf, 2) if people_pf else 0.0,
            "track_idle": sum(1 for _, v in rated if v < IDLE_MPS),
            "track_moving": sum(1 for _, v in rated if v >= IDLE_MPS),
        },
        "zones": {
            "cols": GRID_COLS, "rows": GRID_ROWS,
            "occupancy": norm(occ), "idle": norm(z_idle), "moving": norm(z_moving), "slow": norm(z_slow),
            "speed": [[round(s / c, 2) if c else None for s, c in zip(rs, rc)] for rs, rc in zip(z_speed_sum, z_speed_n)],
            "move_speed": [[round(s / c, 2) if c else None for s, c in zip(rs, rc)]
                           for rs, rc in zip(z_move_sum, z_moving)],
        },
        "events": {
            "evasive": sorted((dict(e, track=tr.tid, x=_x_at(tr, e["t"], width)) for tr, k in zip(tracks, kins)
                               if tr.duration >= 0.5 for e in k["evasive"]), key=lambda e: e["t"]),
            "occlusions": sorted((dict(g, track=tr.tid) for tr in tracks for g in tr.gaps), key=lambda g: g["t_lost"]),
            "posture": sorted((dict(p, track=tr.tid) for tr, k in zip(tracks, kins) for p in k["posture"]),
                              key=lambda p: p["t0"]),
        },
        "speed_timeline": [None if v is None else round(v, 2) for v in timeline],
        "visible_frac": round(sum(1 for c in people if c) / n_frames, 2),
        "main_track": _main_track_summary(*main) if main else None,
        "machine_hints": machine_hints(frames, width, height),
    }


def _x_at(tr: Track, t: float, width: int) -> float:
    i = min(len(tr.t) - 1, bisect.bisect_left(tr.t, t))
    return round(foot(tr.boxes[i])[0] / width, 2)


def _main_track_summary(tr: Track, k: dict) -> dict:
    shorts = [(v, t) for v, t in zip(k["v_short"], tr.t) if v is not None]
    peak_v, peak_t = max(shorts, default=(None, None))
    return {"t0": round(tr.t[0], 2), "t1": round(tr.t[-1], 2), "samples": len(tr.t),
            "mean_speed": None if k["mean_speed"] is None else round(k["mean_speed"], 2),
            "peak_mps": None if peak_v is None else round(peak_v, 2),
            "peak_t": None if peak_t is None else round(peak_t, 2),
            "ruler_px": None if k["ruler_px"] is None else round(k["ruler_px"])}


def concat_frames(dets: list[dict], seg_len: float = 5.0) -> list[dict]:
    """Concatenate segment sidecars into one timeline (segment k shifted by k * seg_len)."""
    out = []
    for k, d in enumerate(dets):
        out.extend({**f, "time_sec": round(f["time_sec"] + k * seg_len, 4)} for f in d["frames"])
    return out
