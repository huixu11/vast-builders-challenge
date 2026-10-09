"""Write the analyzer's results into VastDB next to the VSS index.

Schema `warehouse_ops` in the team database holds three tables:
  alerts           safety events (near misses, people in a vehicle's path, collisions)
  flags            idle labor, idle machines, congestion and underused zones
  segment_metrics  people, idle ratio and machines for every analyzed 5 s segment
Every row carries `source`, the segment's S3 URI, which is also the key of the VSS segment table, so the results
join with the pipeline's captions and embeddings. A run replaces the rows of the sites it covers, so the tables always
match the app's data files.

    python export_vastdb.py                         # all sites
    python export_vastdb.py --sites w3_live183050   # only these sites (what the agent loop does)
    python export_vastdb.py --join                  # print alerts joined with the VSS captions
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import textwrap
from datetime import datetime, timezone
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.compute as pc
import urllib3
import vastdb

from common import APP_DIR, log, read_json, vss_client

SCHEMA = "warehouse_ops"
_S, _F, _I = pa.utf8(), pa.float64(), pa.int64()
TABLES = {
    "alerts": pa.schema([
        ("event_id", _S), ("site_id", _S), ("camera", _S), ("type", _S), ("severity", _S), ("confidence", _F),
        ("scene_t", _F), ("title", _S), ("description", _S), ("source", _S), ("original_video", _S),
        ("exported_at", _S)]),
    "flags": pa.schema([
        ("flag_id", _S), ("site_id", _S), ("camera", _S), ("type", _S), ("metric", _S), ("value", _F),
        ("threshold", _F), ("scene_t0", _F), ("scene_t1", _F), ("message", _S), ("source", _S), ("exported_at", _S)]),
    "segment_metrics": pa.schema([
        ("source", _S), ("site_id", _S), ("camera", _S), ("view", _S), ("chunk_index", _I), ("segment", _I),
        ("scene_t0", _F), ("scene_t1", _F), ("people", _F), ("people_idle", _F), ("idle_ratio", _F),
        ("machines", _I), ("machines_moving", _I), ("congestion", _S), ("event_ids", _S), ("summary", _S),
        ("original_video", _S), ("exported_at", _S)]),
}
CAPTION_COLUMNS = ("reasoning_content", "caption", "description", "summary")


def setting(name: str) -> str:
    value = vss_client.setting(name)
    if not value:
        raise SystemExit(f"{name} is not set in the team config")
    return value


def connect():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return vastdb.connect(endpoint=setting("S3_ENDPOINT"), access=setting("ACCESS_KEY"), secret=setting("SECRET_KEY"),
                          ssl_verify=False)


def reachable() -> bool:
    """The data VIP only resolves inside the event network (the VM, the cluster), not from every laptop."""
    host = urlparse(vss_client.setting("S3_ENDPOINT")).hostname
    try:
        return bool(host) and bool(socket.getaddrinfo(host, 443))
    except OSError:
        return False


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_rows(sites: set[str] | None) -> dict[str, list[dict]]:
    def keep(r: dict) -> bool:
        return not sites or r.get("site_id") in sites

    segments = [s for s in read_json(os.path.join(APP_DIR, "data_segments.json"), []) or [] if keep(s)]
    events = [e for e in read_json(os.path.join(APP_DIR, "data_events.json"), []) or [] if keep(e)]
    flags = [f for f in (read_json(os.path.join(APP_DIR, "data_utilization.json"), {}) or {}).get("flags", []) if keep(f)]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def covering(site: str, camera: str, t: float) -> str | None:
        return next((s["source"] for s in segments if s["site_id"] == site and s["camera"] == camera
                     and s["scene_t0"] <= t < s["scene_t1"]), None)

    alerts = [{
        "event_id": e["event_id"], "site_id": e["site_id"], "camera": e.get("camera"), "type": e.get("type"),
        "severity": e.get("severity"), "confidence": _num(e.get("confidence")), "scene_t": _num(e.get("scene_t")),
        "title": e.get("title"), "description": e.get("description"), "source": e.get("source"),
        "original_video": e.get("original_video"), "exported_at": now} for e in events]
    flag_rows = [{
        "flag_id": f["flag_id"], "site_id": f["site_id"], "camera": f.get("camera"), "type": f.get("type"),
        "metric": (f.get("metric") or {}).get("name"), "value": _num((f.get("metric") or {}).get("value")),
        "threshold": _num((f.get("metric") or {}).get("threshold")), "scene_t0": _num(f.get("scene_t0")),
        "scene_t1": _num(f.get("scene_t1")), "message": f.get("message"),
        "source": covering(f["site_id"], f.get("camera"), _num(f.get("scene_t0"))), "exported_at": now} for f in flags]
    metrics = []
    for s in segments:
        people, machines = s.get("people") or {}, [m for m in (s.get("machines") or {}).values() if isinstance(m, dict)]
        metrics.append({
            "source": s["source"], "site_id": s["site_id"], "camera": s["camera"], "view": s.get("view"),
            "chunk_index": int(s.get("chunk_index") or 0), "segment": int(s.get("n") or 0),
            "scene_t0": _num(s.get("scene_t0")), "scene_t1": _num(s.get("scene_t1")),
            "people": _num(people.get("per_frame_mean")), "people_idle": _num(people.get("idle")),
            "idle_ratio": _num(people.get("idle_ratio")), "machines": sum(int(m.get("total") or 0) for m in machines),
            "machines_moving": sum(int(m.get("moving") or 0) for m in machines), "congestion": s.get("congestion"),
            "event_ids": ",".join(s.get("event_ids") or []), "summary": s.get("vlm_summary"),
            "original_video": s.get("original_video"), "exported_at": now})
    return {"alerts": alerts, "flags": flag_rows, "segment_metrics": metrics}


def export(sites: set[str] | None = None) -> dict[str, int]:
    """Replace the rows of `sites` (all sites when None) in every table; returns rows written per table."""
    rows = build_rows(sites)
    with connect().transaction() as tx:
        bucket = tx.bucket(setting("VASTDB_BUCKET"))
        schema = bucket.schema(SCHEMA, fail_if_missing=False) or bucket.create_schema(SCHEMA, fail_if_exists=False)
        for name, columns in TABLES.items():
            table = schema.table(name, fail_if_missing=False)
            if table is not None and [c.name for c in table.columns()] != columns.names:
                table.drop()  # column set changed since the last export
                table = None
            if table is None:
                table = schema.create_table(name, columns, fail_if_exists=False)
            else:
                old = table.select(columns=["site_id"], internal_row_id=True).read_all()
                stale = old.filter(pc.is_in(old["site_id"], value_set=pa.array(sorted(sites)))) if sites else old
                if stale.num_rows:
                    table.delete(stale)
            if rows[name]:
                table.insert(pa.Table.from_pylist(rows[name], schema=columns))
    return {name: len(r) for name, r in rows.items()}


def table_counts() -> dict[str, int]:
    with connect().transaction() as tx:
        schema = tx.bucket(setting("VASTDB_BUCKET")).schema(SCHEMA)
        return {name: schema.table(name).select(columns=["site_id"]).read_all().num_rows for name in TABLES}


def joined_alerts() -> pa.Table:
    """Alerts joined with the VSS segment rows they point at (same `source`), read straight from VastDB."""
    with connect().transaction() as tx:
        bucket = tx.bucket(setting("VASTDB_BUCKET"))
        alerts = bucket.schema(SCHEMA).table("alerts").select(
            columns=["event_id", "severity", "title", "site_id", "camera", "source"]).read_all()
        vss_table = bucket.schema(setting("VDB_SCHEMA")).table(setting("VDB_COLLECTION"))
        names = [c.name for c in vss_table.columns()]
        caption = next((c for c in CAPTION_COLUMNS if c in names), None)
        vss_rows = vss_table.select(columns=["source"] + ([caption] if caption else [])).read_all()
    vss_rows = vss_rows.filter(pc.is_in(vss_rows["source"], value_set=alerts["source"]))
    return alerts.join(vss_rows, "source")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", help="comma-separated site ids (default: all)")
    ap.add_argument("--join", action="store_true", help="print alerts joined with the VSS captions and exit")
    args = ap.parse_args()
    if args.join:
        joined = joined_alerts()
        print(f"{SCHEMA}.alerts joined on source with {setting('VDB_SCHEMA')}.{setting('VDB_COLLECTION')} "
              f"(captions by Cosmos Reason): {joined.num_rows} alert(s)")
        for row in joined.to_pylist():
            caption = next((row[c] for c in CAPTION_COLUMNS if row.get(c)), "(no caption)")
            print(f"\n[{row['severity'].upper()}] {row['title']}: {row['site_id']}, camera {row['camera']}")
            print(f"  segment  {row['source'].rsplit('/', 1)[-1]}")
            print(textwrap.fill(caption, width=110, initial_indent="  Cosmos   ", subsequent_indent=" " * 11))
        return 0
    sites = {s for s in (args.sites or "").split(",") if s} or None
    written = export(sites)
    log(f"VastDB {SCHEMA}: wrote {written['alerts']} alert(s), {written['flags']} flag(s), "
        f"{written['segment_metrics']} segment row(s) for {', '.join(sorted(sites)) if sites else 'all sites'}; "
        f"tables now hold " + ", ".join(f"{k} {v}" for k, v in table_counts().items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
