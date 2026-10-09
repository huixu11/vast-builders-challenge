"""Cached fetchers: YOLO sidecars and raw segment clips (parallel, resumable)."""
from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor

from common import basename_noext, cache_path, log, read_json, vss, write_json
from inventory import Segment


def _retry(fn, attempts: int = 3, what: str = "request"):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            log(f"{what} failed ({type(e).__name__}); retry {i + 1}")
            time.sleep(2 * (i + 1))


def sidecar_path(source: str) -> str:
    return cache_path("det", basename_noext(source) + ".json")


def fetch_sidecars(segments: list[Segment], force: bool = False, workers: int = 6) -> dict[str, dict | None]:
    stats = {"cached": 0, "fetched": 0, "missing": 0, "failed": 0}

    def one(seg: Segment):
        path = sidecar_path(seg.source)
        if not force:
            cached = read_json(path)
            if cached is not None:
                stats["cached"] += 1
                return seg.source, (None if cached.get("missing") else cached)
        try:
            det = _retry(lambda: vss().detections(seg.source), what=f"detections {seg.seg_id}")
        except Exception as e:  # noqa: BLE001
            stats["failed"] += 1
            log(f"detections unavailable for {seg.seg_id}: {type(e).__name__}")
            return seg.source, None
        write_json(path, det if det is not None else {"missing": True})
        stats["fetched" if det is not None else "missing"] += 1
        return seg.source, det

    with ThreadPoolExecutor(workers) as pool:
        out = dict(pool.map(one, segments))
    log(f"sidecars: {stats}")
    return out


def media_path(source: str) -> str:
    return cache_path("media", basename_noext(source) + ".mp4")


class Downloader:
    """Downloads segment clips on demand (deduplicated, up to `workers` in parallel)."""

    def __init__(self, workers: int = 6, force: bool = False) -> None:
        self._pool = ThreadPoolExecutor(workers)
        self._futures: dict[str, Future] = {}
        self._force = force
        self.downloaded = 0
        self.bytes = 0

    def get(self, source: str) -> Future:
        if source not in self._futures:
            self._futures[source] = self._pool.submit(self._download, source)
        return self._futures[source]

    def _download(self, source: str) -> str:
        path = media_path(source)
        if os.path.exists(path) and os.path.getsize(path) > 0 and not self._force:
            return path
        _retry(lambda: vss().download(source, path), what=f"download {basename_noext(source)}")
        self.downloaded += 1
        self.bytes += os.path.getsize(path)
        return path

    def close(self) -> None:
        self._pool.shutdown(wait=True)
