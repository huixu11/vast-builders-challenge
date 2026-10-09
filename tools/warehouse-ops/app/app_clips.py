"""Disk cache for proxied clips.

The first request for a clip is proxied straight from VSS (with Range passthrough) while the whole
file is fetched in the background; later requests are served from disk with full Range support,
which keeps seeking and the synchronized multi-camera replay smooth. Bounded by CLIP_CACHE_MB.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from app_live import Clients, safe_error

log = logging.getLogger("wops.clips")


class ClipCache:
    def __init__(self, clients: Clients) -> None:
        self.clients = clients
        self.root = os.environ.get("CLIP_CACHE_DIR") or os.path.join(tempfile.gettempdir(), "warehouse-ops-clips")
        self.max_bytes = int(float(os.environ.get("CLIP_CACHE_MB", "1500")) * 1024 * 1024)
        self.enabled = self.max_bytes > 0
        if self.enabled:
            try:
                os.makedirs(self.root, exist_ok=True)
            except OSError as e:
                log.warning("clip cache disabled: %s", safe_error(e))
                self.enabled = False
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="clip")

    def _path(self, source: str) -> str:
        return os.path.join(self.root, hashlib.sha1(source.encode("utf-8")).hexdigest() + ".mp4")

    def get(self, source: str) -> str | None:
        if not self.enabled:
            return None
        path = self._path(source)
        if not os.path.exists(path):
            return None
        try:
            os.utime(path)
        except OSError:
            pass
        return path

    def fetch_async(self, source: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            if source in self._inflight or os.path.exists(self._path(source)):
                return
            self._inflight.add(source)
        self._pool.submit(self._fetch, source)

    def _fetch(self, source: str) -> None:
        try:
            self.clients.vss().download(source, self._path(source))
            self._evict()
        except Exception as e:  # noqa: BLE001
            log.warning("clip prefetch failed: %s", safe_error(e))
        finally:
            with self._lock:
                self._inflight.discard(source)

    def _evict(self) -> None:
        try:
            files = [os.path.join(self.root, f) for f in os.listdir(self.root) if f.endswith(".mp4")]
            stats = sorted(((os.stat(p).st_mtime, os.path.getsize(p), p) for p in files))
        except OSError:
            return
        total = sum(size for _, size, _ in stats)
        for _, size, path in stats:
            if total <= self.max_bytes:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:  # still being served (Windows) — try again next time
                continue

    def status(self) -> dict:
        if not self.enabled:
            return {"enabled": False}
        try:
            files = [f for f in os.listdir(self.root) if f.endswith(".mp4")]
            size = sum(os.path.getsize(os.path.join(self.root, f)) for f in files)
        except OSError:
            files, size = [], 0
        return {"enabled": True, "files": len(files), "mb": round(size / 1048576, 1), "inflight": len(self._inflight)}
