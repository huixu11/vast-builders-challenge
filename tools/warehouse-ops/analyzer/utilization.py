"""Per-camera utilization (5 s series, totals, fleet, heatmaps) and explainable rule-based flags."""
from __future__ import annotations

import statistics
from collections import defaultdict

MACHINE_TYPES = ("agv", "amr", "humanoid", "forklift")
MACHINE_MIN_TOTAL = 2.0
MACHINE_MOVING_RATIO = 0.4
MACHINE_WINDOW_SEC = 60.0
CONGESTION_PERSONS = 4.0
UNDERUSED_OCC = 0.2
UNDERUSED_MIN_PEAK = 0.3
BUSY_CAMERA_PEOPLE = 4.0
BOTTLENECK_PERSONS = 3.0
BOTTLENECK_MOVING_SHARE = 0.3
BOTTLENECK_MOVE_SPEED = 0.6
BOTTLENECK_MIN_SEC = 10.0
MAX_FLAGS_PER_TYPE = 3
GRID_ROWS, GRID_COLS = 3, 4


def _runs(rows: list[dict], ok) -> list[list[dict]]:
    """Maximal runs of time-contiguous rows satisfying `ok`."""
    runs, cur = [], []
    for row in rows:
        if ok(row) and (not cur or abs(row["scene_t0"] - cur[-1]["scene_t1"]) < 1e-6):
            cur.append(row)
            continue
        if cur:
            runs.append(cur)
        cur = [row] if ok(row) else []
    if cur:
        runs.append(cur)
    return runs


def _span(run: list[dict]) -> tuple[float, float, float]:
    t0, t1 = run[0]["scene_t0"], run[-1]["scene_t1"]
    return t0, t1, t1 - t0


def _mean_grid(grids: list[list[list[float]]]) -> list[list[float]]:
    return [[round(statistics.fmean(g[r][c] for g in grids), 2) for c in range(GRID_COLS)] for r in range(GRID_ROWS)]


def _zone_name(col: int, row: int) -> str:
    return f"zone ({['far', 'mid', 'near'][row]} row, column {col + 1})"


def camera_series(rows: list[dict]) -> tuple[list[dict], dict, dict]:
    series = [{"scene_t0": r["scene_t0"], "scene_t1": r["scene_t1"], "people": r["people"], "idle": r["idle"],
               "moving": r["moving"], "machines_total": r["machines_total"], "machines_moving": r["machines_moving"],
               "agv_total": r["machines"]["agv"]["total"], "agv_moving": r["machines"]["agv"]["moving"],
               "agv_loaded": r["machines"]["agv"]["loaded"]}
              for r in rows]
    dur = [r["scene_t1"] - r["scene_t0"] for r in rows]
    person_s = sum(r["people"] * d for r, d in zip(rows, dur))
    idle_s = sum(r["idle"] * d for r, d in zip(rows, dur))
    m_total = sum(r["machines_total"] for r in rows)
    totals = {
        "people_avg": round(statistics.fmean(r["people"] for r in rows), 2),
        "idle_ratio": round(idle_s / person_s, 3) if person_s else 0.0,
        "machine_moving_ratio": round(sum(r["machines_moving"] for r in rows) / m_total, 3) if m_total else 0.0,
        "person_seconds": round(person_s, 1),
        "idle_person_seconds": round(idle_s, 1),
        "machines_avg": round(m_total / len(rows), 2),
        "duration_sec": round(sum(dur), 1),
    }
    heatmap = {"cols": GRID_COLS, "rows": GRID_ROWS,
               "occupancy": _mean_grid([r["zones"]["occupancy"] for r in rows]),
               "idle": _mean_grid([r["zones"]["idle"] for r in rows])}
    return series, totals, heatmap


def fleet_summary(rows: list[dict]) -> dict:
    """Per machine type: average count, share of machine-time moving, stationary count; AGV loaded share.
    Window shares: 5 s windows with any machine moving, and with machines in view but none moving.
    Rows need "machines" ({type: {total, moving[, loaded]}}); works on utilization rows and segment records."""
    n = len(rows)
    out: dict = {"types": {}, "source": "vlm" if rows and all(r.get("machines_source") == "vlm" for r in rows)
                 else "mixed"}
    if not n:
        return out
    for t in MACHINE_TYPES:
        ms = [(r.get("machines") or {}).get(t) or {} for r in rows]
        total, moving = sum(m.get("total", 0) for m in ms), sum(m.get("moving", 0) for m in ms)
        if not total:
            continue
        d = {"avg": round(total / n, 2), "moving_ratio": round(moving / total, 3),
             "stationary_avg": round((total - moving) / n, 2)}
        if t == "agv":
            d["loaded_ratio"] = round(sum(m.get("loaded", 0) for m in ms) / total, 3)
        out["types"][t] = d
    present = [r for r in rows if sum(m.get("total", 0) for m in (r.get("machines") or {}).values())]
    moving = [r for r in present if sum(m.get("moving", 0) for m in r["machines"].values())]
    out["active_window_share"] = round(len(moving) / n, 3)
    out["stalled_window_share"] = round((len(present) - len(moving)) / n, 3)
    return out


def camera_flags(site_id: str, camera: str, rows: list[dict], totals: dict) -> list[dict]:
    flags: list[tuple[float, dict]] = []

    def add(ftype: str, zone, t0: float, t1: float, name: str, value: float, threshold: float, message: str,
            score: float) -> None:
        tag = "cam" if zone is None else f"z{zone[0]}{zone[1]}"
        flags.append((score, {"flag_id": f"fl_{ftype}_{site_id}_{camera}_{tag}_{int(t0):04d}", "type": ftype,
                              "site_id": site_id, "camera": camera, "zone": zone, "scene_t0": t0, "scene_t1": t1,
                              "metric": {"name": name, "value": round(value, 2), "threshold": threshold},
                              "message": message}))

    # machine_surplus: >= 2 machines visible but < 40% of machine-time moving, over sliding 60 s windows
    vlm_rows = [r for r in rows if r["machines_source"] == "vlm"]
    if len(vlm_rows) == len(rows) and rows:
        win = max(1, round(MACHINE_WINDOW_SEC / (rows[0]["scene_t1"] - rows[0]["scene_t0"])))
        marked = [False] * len(rows)
        for i in range(len(rows) - win + 1):
            w = rows[i:i + win]
            total = sum(r["machines_total"] for r in w)
            if (len(_runs(w, lambda r: True)) == 1 and total / win >= MACHINE_MIN_TOTAL
                    and sum(r["machines_moving"] for r in w) / total < MACHINE_MOVING_RATIO):
                marked[i:i + win] = [True] * win
        flagged = {id(r) for r, m in zip(rows, marked) if m}
        for run in _runs(rows, lambda r: id(r) in flagged):
            t0, t1, dur = _span(run)
            total = sum(r["machines_total"] for r in run)
            ratio = sum(r["machines_moving"] for r in run) / total
            idle_by_type = defaultdict(float)
            for r in run:
                for mtype, m in r["machines"].items():
                    idle_by_type[mtype] += (m["total"] - m["moving"]) / len(run)
            parts = ", ".join(f"{v:.1f} {k}" for k, v in sorted(idle_by_type.items(), key=lambda kv: -kv[1]) if v >= 0.1)
            add("machine_surplus", None, t0, t1, "machine_moving_ratio", ratio, MACHINE_MOVING_RATIO,
                f"{camera}: {total / len(run):.1f} machines in view on average but only {ratio:.0%} moving "
                f"(t={t0:.0f}-{t1:.0f} s); stationary on average: {parts}.", dur * (1 - ratio))

    # congestion / bottleneck per zone
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            for run in _runs(rows, lambda r: r["zones"]["occupancy"][row][col] >= CONGESTION_PERSONS):
                t0, t1, dur = _span(run)
                peak = max(r["zones"]["occupancy"][row][col] for r in run)
                add("congestion", [col, row], t0, t1, "zone_occupancy", peak, CONGESTION_PERSONS,
                    f"{camera} {_zone_name(col, row)}: up to {peak:.1f} people at once for {dur:.0f} s "
                    f"(t={t0:.0f}-{t1:.0f} s).", dur * peak / CONGESTION_PERSONS)

            def slow_flow(r: dict) -> bool:
                occ = r["zones"]["occupancy"][row][col]
                speed = r["zones"]["move_speed"][row][col]
                return (occ >= BOTTLENECK_PERSONS and speed is not None and speed < BOTTLENECK_MOVE_SPEED
                        and r["zones"]["moving"][row][col] / occ >= BOTTLENECK_MOVING_SHARE)
            for run in _runs(rows, slow_flow):
                t0, t1, dur = _span(run)
                if dur >= BOTTLENECK_MIN_SEC:
                    speed = statistics.fmean(r["zones"]["move_speed"][row][col] for r in run)
                    occ = statistics.fmean(r["zones"]["occupancy"][row][col] for r in run)
                    add("bottleneck", [col, row], t0, t1, "zone_moving_speed_mps", speed, BOTTLENECK_MOVE_SPEED,
                        f"{camera} {_zone_name(col, row)}: {occ:.1f} people on average and those walking move at "
                        f"only {speed:.2f} m/s for {dur:.0f} s (t={t0:.0f}-{t1:.0f} s).",
                        dur * BOTTLENECK_MOVE_SPEED / max(speed, 0.05))

    # underused_zone: floor area that is reachable (used at least once) but nearly empty on a busy camera
    if totals["people_avg"] >= BUSY_CAMERA_PEOPLE and rows:
        t0, t1 = rows[0]["scene_t0"], rows[-1]["scene_t1"]
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                occ = [r["zones"]["occupancy"][row][col] for r in rows]
                avg = round(statistics.fmean(occ), 2)
                if avg < UNDERUSED_OCC and max(occ) >= UNDERUSED_MIN_PEAK:
                    add("underused_zone", [col, row], t0, t1, "zone_occupancy_avg", avg, UNDERUSED_OCC,
                        f"{camera} {_zone_name(col, row)}: only {avg:.2f} people on average over {t1 - t0:.0f} s "
                        f"while the camera averages {totals['people_avg']:.1f} people.", UNDERUSED_OCC - avg)

    best: dict[str, list[tuple[float, dict]]] = defaultdict(list)
    for score, flag in flags:
        best[flag["type"]].append((score, flag))
    out = []
    for items in best.values():
        out += [f for _, f in sorted(items, key=lambda x: -x[0])[:MAX_FLAGS_PER_TYPE]]
    return sorted(out, key=lambda f: (f["type"], f["scene_t0"]))


def build(cam_rows: dict[tuple, list[dict]], views: dict[tuple, str]) -> dict:
    cameras, flags = [], []
    for (site_id, camera), rows in cam_rows.items():
        series, totals, heatmap = camera_series(rows)
        cameras.append({"site_id": site_id, "camera": camera, "view": views[(site_id, camera)], "series": series,
                        "totals": totals, "heatmap": heatmap, "fleet": fleet_summary(rows)})
        flags += camera_flags(site_id, camera, rows, totals)
    return {"cameras": cameras, "flags": flags}
