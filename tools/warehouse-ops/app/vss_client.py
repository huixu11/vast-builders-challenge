"""Shared client for the team's VSS backend and GPU model endpoints.

Credential/endpoint resolution (never hardcoded, never printed):
  1. Environment: VSS_URL, VSS_USERNAME, VSS_PASSWORD, GPU_BEARER_TOKEN (K8s Secret path).
  2. Team config file: $VSS_CONFIG, else the single /config/*.config (C:\\config on Windows).
The backend URL falls back from INGRESS_URL to https://<PIPELINE>.thecosmoslabs.com when the
internal ingress is not reachable from the current machine.
"""
from __future__ import annotations

import glob
import os
import re
import threading
import time
from typing import Any, Iterator

import requests

_GPU_HOST_DEFAULT = "166.19.38.112"


def _load_config_file() -> dict[str, str]:
    path = os.environ.get("VSS_CONFIG")
    if not path:
        candidates = sorted(glob.glob("/config/*.config"))
        if len(candidates) != 1:
            return {}
        path = candidates[0]
    if not os.path.exists(path):
        return {}
    cfg: dict[str, str] = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line.rstrip("\r\n"))
            if not m:
                continue
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            cfg[m.group(1)] = v
    return cfg


_CFG = _load_config_file()


def setting(name: str, *config_keys: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    for key in (name, *config_keys):
        if _CFG.get(key):
            return _CFG[key]
    return default


def _reachable(url: str) -> bool:
    try:
        return requests.get(url.rstrip("/") + "/health", timeout=4).status_code == 200
    except requests.RequestException:
        return False


def _public_backend() -> str:
    pipeline = setting("PIPELINE")
    return f"https://{pipeline}.thecosmoslabs.com" if pipeline else ""


def _resolve_backend() -> str:
    # Prefer VSS_URL / INGRESS_URL, but the in-cluster ingress is often unreachable from the
    # app pod; fall back to the public PIPELINE host the laptop already uses.
    candidates: list[str] = []
    for url in (os.environ.get("VSS_URL", ""), _CFG.get("INGRESS_URL", ""), _public_backend()):
        url = url.rstrip("/")
        if url and url not in candidates:
            candidates.append(url)
    for url in candidates:
        if _reachable(url):
            return url
    return candidates[0] if candidates else ""


class VSS:
    """Thin JWT client for the VSS retrieval API. Thread-safe token refresh."""

    def __init__(self) -> None:
        self.base = _resolve_backend()
        self._user = setting("VSS_USERNAME", "USERNAME")
        self._password = setting("VSS_PASSWORD", "PASSWORD")
        self._token: str | None = None
        self._lock = threading.Lock()
        self.session = requests.Session()

    def token(self, refresh: bool = False) -> str:
        with self._lock:
            if self._token is None or refresh:
                r = self.session.post(
                    f"{self.base}/api/v1/auth/login",
                    json={"username": self._user, "password": self._password},
                    timeout=30,
                )
                r.raise_for_status()
                self._token = r.json()["access_token"]
            return self._token

    def _request(self, method: str, path: str, **kw: Any) -> requests.Response:
        kw.setdefault("timeout", 120)
        for attempt in range(2):
            headers = {**kw.pop("headers", {}), "Authorization": f"Bearer {self.token(refresh=attempt > 0)}"}
            r = self.session.request(method, f"{self.base}{path}", headers=headers, **kw)
            if r.status_code != 401:
                return r
        return r

    def get(self, path: str, **params: Any) -> Any:
        r = self._request("GET", path, params=params)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict, timeout: int = 300) -> Any:
        r = self._request("POST", path, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def explore_all(self, location: str | None = None) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            params: dict[str, Any] = {"scope": "all", "limit": 100, "offset": offset}
            if location:
                params["location"] = location
            page = self.get("/api/v1/videos/explore", **params)
            batch = page.get("chunks") or []
            items.extend(batch)
            offset += 100
            if not batch or offset >= (page.get("total") or 0):
                return items

    def detections(self, source: str) -> dict | None:
        r = self._request("GET", "/api/v1/videos/detections", params={"source": source})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def open_stream(self, source: str, range_header: str | None = None) -> requests.Response:
        """Range-capable proxy of /videos/stream; the JWT stays server-side."""
        headers = {"Range": range_header} if range_header else {}
        for attempt in range(2):
            r = self.session.get(
                f"{self.base}/api/v1/videos/stream",
                params={"source": source, "token": self.token(refresh=attempt > 0)},
                headers=headers,
                stream=True,
                timeout=300,
            )
            if r.status_code != 401:
                return r
            r.close()
        return r

    def download(self, source: str, dest: str) -> str:
        r = self.open_stream(source)
        r.raise_for_status()
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
        os.replace(tmp, dest)
        return dest


class Cosmos:
    """OpenAI-compatible chat client for Cosmos3-Reason (video or text)."""

    def __init__(self) -> None:
        self.base = setting("COSMOS3_REASON_URL", default=f"http://{_GPU_HOST_DEFAULT}:8001").rstrip("/")
        self._bearer = setting("GPU_BEARER_TOKEN")
        self._model: str | None = os.environ.get("COSMOS3_REASON_MODEL") or None
        self.session = requests.Session()

    @property
    def available(self) -> bool:
        return bool(self._bearer)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._bearer}"}

    @property
    def model(self) -> str:
        if self._model is None:
            r = self.session.get(f"{self.base}/v1/models", headers=self._headers(), timeout=30)
            r.raise_for_status()
            self._model = r.json()["data"][0]["id"]
        return self._model

    def chat(self, content: list[dict] | str, max_tokens: int = 1500, temperature: float = 0.2,
             system: str | None = None, retries: int = 3) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        last: Exception | None = None
        for attempt in range(retries):
            try:
                r = self.session.post(f"{self.base}/v1/chat/completions", headers=self._headers(), json=body, timeout=600)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()["choices"][0]["message"].get("content") or ""
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"Cosmos call failed after {retries} attempts: {last}")

    @staticmethod
    def video_part(mp4_bytes_b64: str) -> dict:
        return {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{mp4_bytes_b64}"}}


class WandB:
    """W&B Serverless Inference (OpenAI-compatible) for the app's text reasoning.

    Same chat() signature as Cosmos for text content. The model is WANDB_MODEL if set, else the
    first available entry of PREFERRED_MODELS, else the first model the endpoint lists.
    """

    PREFERRED_MODELS = (
        "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B",
        "openai/gpt-oss-120b",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "deepseek-ai/DeepSeek-V3.1",
        "deepseek-ai/DeepSeek-V3-0324",
        "moonshotai/Kimi-K2-Instruct",
        "meta-llama/Llama-3.3-70B-Instruct",
        "meta-llama/Llama-3.1-8B-Instruct",
    )

    def __init__(self, model: str | None = None) -> None:
        self.base = setting("WANDB_BASE_URL", default="https://api.inference.wandb.ai/v1").rstrip("/")
        self._key = setting("WANDB_API_KEY")
        team, project = setting("WANDB_TEAM"), setting("WANDB_PROJECT")
        self._project = f"{team}/{project}" if team and project else ""
        self._model: str | None = model or setting("WANDB_MODEL") or None
        self.session = requests.Session()

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._key}"}
        if self._project:
            headers["OpenAI-Project"] = self._project
        return headers

    def models(self) -> list[str]:
        r = self.session.get(f"{self.base}/models", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    @property
    def model(self) -> str:
        if self._model is None:
            listed = self.models()
            self._model = next((m for m in self.PREFERRED_MODELS if m in listed), listed[0] if listed else "")
        return self._model

    def chat(self, content: list[dict] | str, max_tokens: int = 1500, temperature: float = 0.2,
             system: str | None = None, retries: int = 3) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        last: Exception | None = None
        for attempt in range(retries):
            try:
                r = self.session.post(f"{self.base}/chat/completions", headers=self._headers(), json=body, timeout=300)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()["choices"][0]["message"].get("content") or ""
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"W&B inference call failed after {retries} attempts: {last}")


def text_llm() -> WandB | Cosmos:
    """LLM for text-only reasoning (Q&A, recommendations, reports): W&B if configured, else Cosmos."""
    wandb = WandB()
    return wandb if wandb.available else Cosmos()


def iter_stream(resp: requests.Response, chunk: int = 1 << 16) -> Iterator[bytes]:
    try:
        yield from resp.iter_content(chunk)
    finally:
        resp.close()


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a model reply (handles ```json fences and <think> blocks)."""
    import json

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON found in model reply")
    return json.JSONDecoder().raw_decode(text[start:])[0]
