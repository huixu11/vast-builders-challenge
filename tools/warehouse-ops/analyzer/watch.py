"""Real-time agent loop: watch the VSS archive and analyze new footage as soon as it is fully indexed.

Every --interval seconds the agent lists the indexed chunks in the warehouse locations and compares them with
what the app's data files cover. When a site gains a fully indexed chunk (all of its segments written), the
agent runs the analyzer on that site, which merges the results into the data files; the app reloads them
within ~10 s and badges the new alerts. The new results are also written to VastDB (export_vastdb.py) when the
SDK is installed. Status and an activity log go to .cache/agent_status.json, which the app shows as the agent card.

Run from the repo root: .venv\\Scripts\\python.exe tools/warehouse-ops/analyzer/watch.py [--interval 30] [--no-vlm]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import inventory
from common import ANALYZER_DIR, APP_DIR, cache_path, log, read_json, write_json

try:
    import export_vastdb
except ImportError:  # vastdb SDK not installed: results stay in the app's data files only
    export_vastdb = None
VASTDB = export_vastdb is not None and export_vastdb.reachable()

STATUS_PATH = cache_path("agent_status.json")
RUN_LOG = cache_path("agent_last_run.log")
MAX_LOG = 40
HEARTBEAT_SEC = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_sec(upload_timestamp: str | None) -> float | None:
    """VSS upload timestamps are naive UTC."""
    try:
        t = datetime.fromisoformat(str(upload_timestamp)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - t).total_seconds()


def analyzed() -> dict[str, int]:
    """Chunk filename -> segments already covered by the app's data files."""
    videos = read_json(os.path.join(APP_DIR, "data_videos.json"), {}) or {}
    return {ch["filename"]: len(ch.get("segments") or []) for site in videos.get("sites", [])
            for cam in site.get("cameras", []) for ch in cam.get("chunks", [])}


def scan() -> dict[str, dict]:
    """Chunk filename -> parsed name, segment progress and upload time, for chunks the analyzer understands."""
    out = {}
    for location in inventory.LOCATIONS:
        for ch in inventory.explore(location):
            meta = inventory.parse_name(location, ch.get("filename", ""), ch.get("camera_id") or "")
            if meta:
                out[ch["filename"]] = {**meta, "written": len(ch.get("timeline") or []),
                                       "total": int(ch.get("total_segments") or 0), "uploaded": ch.get("upload_timestamp")}
    return out


class Agent:
    """Owns the status file; a heartbeat thread keeps it fresh while a slow scan or analysis runs."""

    def __init__(self, interval: int) -> None:
        old = read_json(STATUS_PATH, {}) or {}
        history = [e for e in old.get("log", []) if e.get("kind") != "start"][:MAX_LOG]
        self.state = {"status": "starting", "interval_sec": interval, "started_at": now_iso(),
                      "locations": list(inventory.LOCATIONS), "log": history, "analyzing": []}
        self._lock = threading.Lock()
        self.save()
        threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True).start()

    def _heartbeat(self) -> None:
        while True:
            time.sleep(HEARTBEAT_SEC)
            self.save()

    def save(self, **fields) -> None:
        with self._lock:
            self.state.update(fields, heartbeat=now_iso())
            for _ in range(5):
                try:
                    write_json(STATUS_PATH, self.state)
                    return
                except OSError:  # Windows refuses os.replace while the app has the file open
                    time.sleep(0.2)

    def note(self, kind: str, message: str, refs: list[str] | None = None) -> None:
        log(message)
        entry = {"t": now_iso(), "kind": kind, "message": message, **({"refs": refs} if refs else {})}
        with self._lock:
            self.state["log"] = [entry] + self.state["log"][:MAX_LOG - 1]
        self.save()


def run_analyzer(sites: list[str], no_vlm: bool) -> int:
    cmd = [sys.executable, os.path.join(ANALYZER_DIR, "run_analysis.py"), "--sites", ",".join(sites)]
    if no_vlm:
        cmd.append("--no-vlm")
    with open(RUN_LOG, "w", encoding="utf-8") as out:
        return subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, check=False,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode


def analyze(agent: Agent, ready: dict[str, dict], no_vlm: bool) -> None:
    sites = sorted({m["site_id"] for m in ready.values()})
    agent.save(status="analyzing", analyzing=sites)
    agent.note("analyzing", f"Analyzing {len(ready)} new video(s) at {', '.join(sites)} with "
                            f"{'YOLO tracks' if no_vlm else 'YOLO tracks + Cosmos'}")
    events_path, util_path = os.path.join(APP_DIR, "data_events.json"), os.path.join(APP_DIR, "data_utilization.json")
    before_events = {e["event_id"] for e in read_json(events_path, []) or []}
    before_flags = {f["flag_id"] for f in (read_json(util_path, {}) or {}).get("flags", [])}
    started = time.time()
    code = run_analyzer(sites, no_vlm)
    took = time.time() - started
    if code != 0:
        agent.note("error", f"Analyzer exited with code {code} after {took:.0f} s; retrying on the next scan "
                            f"(log: {os.path.relpath(RUN_LOG)})")
        agent.save(status="watching", analyzing=[])
        return
    events = [e for e in read_json(events_path, []) or [] if e["event_id"] not in before_events]
    flags = [f for f in (read_json(util_path, {}) or {}).get("flags", []) if f["flag_id"] not in before_flags]
    ages = [a for a in (age_sec(m["uploaded"]) for m in ready.values()) if a is not None]
    since = f"; {max(ages):.0f} s after upload" if ages else ""
    agent.note("done", f"Analysis finished in {took:.0f} s{since}: {len(events)} new alert(s), {len(flags)} new flag(s)",
               refs=[e["event_id"] for e in events] + [f["flag_id"] for f in flags])
    for e in events:
        agent.note("alert", f"{e['severity'].upper()} {e['type'].replace('_', ' ')}: {e['title']} "
                            f"({e['site_id']} {e['camera']}, t={float(e.get('scene_t') or 0):.1f} s)", refs=[e["event_id"]])
    if VASTDB:
        try:
            written = export_vastdb.export(set(sites))
            agent.note("stored", f"Saved to VastDB ({export_vastdb.SCHEMA}): {written['alerts']} alert(s), "
                                 f"{written['flags']} flag(s), {written['segment_metrics']} segment metric row(s)")
        except Exception as e:  # noqa: BLE001
            agent.note("error", f"VastDB write failed ({type(e).__name__}); results are still in the app")
    subprocess.run([sys.executable, os.path.join(ANALYZER_DIR, "thumbnails.py")], capture_output=True, check=False)
    agent.save(status="watching", analyzing=[])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=int, default=30, help="seconds between VSS scans")
    ap.add_argument("--no-vlm", action="store_true", help="analyze new footage with YOLO tracks only (no Cosmos)")
    args = ap.parse_args()

    agent = Agent(args.interval)
    agent.note("start", f"Agent started: watching {', '.join(inventory.LOCATIONS)} every {args.interval} s")
    reported: set[str] = set()
    attempted: dict[str, int] = {}  # filename -> segments written when last analyzed; retried only once more arrive
    while True:
        try:
            indexed = scan()
        except Exception as e:  # noqa: BLE001
            agent.save(status="error", last_scan=now_iso())
            agent.note("error", f"VSS scan failed ({type(e).__name__}); retrying in {args.interval} s")
            time.sleep(args.interval)
            continue
        done = analyzed()
        new = {f: m for f, m in indexed.items() if m["written"] > done.get(f, 0)}
        ready = {f: m for f, m in new.items()
                 if m["total"] and m["written"] >= m["total"] and attempted.get(f) != m["written"]}
        for f, m in new.items():
            if f not in reported:
                reported.add(f)
                agent.note("detected", f"New video in VSS: {m['site_id']} {m['camera']} "
                                       f"({m['written']}/{m['total'] or '?'} segments indexed)")
        agent.save(status="watching", last_scan=now_iso(), videos_indexed=len(indexed),
                   videos_analyzed=sum(done.get(f, 0) >= m["written"] for f, m in indexed.items()),
                   indexing=sorted(f for f in new if f not in ready))
        if ready:
            analyze(agent, ready, args.no_vlm)
            attempted.update({f: m["written"] for f, m in ready.items()})
            reported -= set(ready)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
