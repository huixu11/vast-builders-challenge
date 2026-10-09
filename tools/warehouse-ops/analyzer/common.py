"""Shared paths, JSON/cache helpers and thread-local API clients for the offline analyzer."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from typing import Any

ANALYZER_DIR = os.path.dirname(os.path.abspath(__file__))
OPS_DIR = os.path.dirname(ANALYZER_DIR)
APP_DIR = os.path.join(OPS_DIR, "app")
CACHE_DIR = os.path.join(OPS_DIR, ".cache")

sys.path.insert(0, APP_DIR)
import vss_client  # noqa: E402  (shared client; resolves endpoints and credentials itself)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_T0 = time.time()
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def cache_path(*parts: str) -> str:
    path = os.path.join(CACHE_DIR, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def read_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, obj: Any, compact: bool = True) -> int:
    """Atomic write; returns the number of bytes written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compact else None,
                      indent=None if compact else 2)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return len(text.encode("utf-8"))


def stable_hash(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def basename_noext(uri: str) -> str:
    return os.path.splitext(uri.rsplit("/", 1)[-1])[0]


def r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


_local = threading.local()
_init_lock = threading.Lock()


def vss() -> vss_client.VSS:
    """One VSS client per thread; the first one pins the resolved backend so others skip probing."""
    client = getattr(_local, "vss", None)
    if client is None:
        with _init_lock:
            client = vss_client.VSS()
            if client.base:
                os.environ.setdefault("VSS_URL", client.base)
        _local.vss = client
    return client


def cosmos() -> vss_client.Cosmos:
    client = getattr(_local, "cosmos", None)
    if client is None:
        with _init_lock:
            client = vss_client.Cosmos()
            if client.available and not os.environ.get("COSMOS3_REASON_MODEL"):
                os.environ["COSMOS3_REASON_MODEL"] = client.model
        _local.cosmos = client
    return client


extract_json = vss_client.extract_json
