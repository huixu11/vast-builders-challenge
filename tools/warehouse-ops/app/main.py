"""Warehouse Ops Copilot — FastAPI backend.

Serves the single-page app (index.html, app.js, styles.css) and the api/* endpoints. Routes live at
"/" because production mounts the app behind the Ingress prefix /app (rewritten to /); the frontend
only uses relative URLs. Credentials stay server-side (vss_client); the browser never sees a token.

Run: python main.py   (listens on 0.0.0.0:$PORT, default 8080)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import app_data
from app_clips import ClipCache
from app_copilot import Copilot
from app_live import Clients, Detections, LiveSources, safe_error
from vss_client import iter_stream

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wops")


class _DropClientResets(logging.Filter):
    """Windows' proactor loop logs a traceback whenever a browser aborts a video request."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.exc_info and isinstance(record.exc_info[1], ConnectionResetError))


logging.getLogger("asyncio").addFilter(_DropClientResets())

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_REFRESH_SEC = 600
DATA_SETTLE_SEC = 30
PREFETCH_CLIPS = int(os.environ.get("PREFETCH_CLIPS", "24"))
PASS_HEADERS = ("Content-Range", "Content-Length", "Accept-Ranges")

store = app_data.DataStore()
clients = Clients()
live = LiveSources(clients)
detections = Detections(clients, live)
clips = ClipCache(clients)
copilot = Copilot(clients, live)


def _prefetch_event_clips(snap: app_data.Snapshot) -> None:
    """Warm the clip cache with the chunks the safety-alert demo opens first."""
    wanted: list[str] = []
    for e in snap.events:
        for src in [e.get("source")] + [v.get("source") for v in app_data.dicts(e.get("views"))]:
            ref = snap.seg_by_source.get(src or "")
            video = ref["original_video"] if ref else e.get("original_video")
            if video and video not in wanted:
                wanted.append(video)
    for video in wanted[:PREFETCH_CLIPS]:
        resolved = live.resolve(video, snap)
        if resolved:
            clips.fetch_async(resolved)


def _maintenance() -> None:
    """Background loop: data reload, live inventory refresh, clip prefetch and report warm-up."""
    next_live, warmed = 0.0, None
    warming = threading.Event()
    while True:
        try:
            store.refresh(force=True)
            snap = store.snapshot()
            now = time.time()
            if now >= next_live:
                next_live = now + (LIVE_REFRESH_SEC if live.refresh() else 60)
            if snap.version != warmed and now - store.changed_at >= DATA_SETTLE_SEC and live.refreshed_at:
                warmed = snap.version
                if PREFETCH_CLIPS > 0:
                    _prefetch_event_clips(snap)
                if os.environ.get("WARM_REPORTS", "1") != "0" and not warming.is_set():
                    warming.set()

                    def warm(s: app_data.Snapshot = snap) -> None:
                        try:
                            copilot.warm_reports(s)
                        finally:
                            warming.clear()

                    threading.Thread(target=warm, name="warm-reports", daemon=True).start()
        except Exception as e:  # noqa: BLE001
            log.warning("maintenance loop error: %s", safe_error(e))
        time.sleep(10)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_maintenance, name="maintenance", daemon=True).start()
    yield


class SafeErrors:
    """Turn unhandled exceptions into JSON without logging tracebacks (request errors can embed token URLs)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as e:  # noqa: BLE001
            log.warning("unhandled error on %s: %s", scope.get("path"), safe_error(e))
            if not started:
                await JSONResponse({"error": "internal error", "detail": safe_error(e)}, status_code=500)(scope, receive, send)


app = FastAPI(title="Warehouse Ops Copilot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SafeErrors)


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _static(name: str, media_type: str) -> FileResponse:
    return FileResponse(os.path.join(APP_DIR, name), media_type=media_type, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return _static("index.html", "text/html; charset=utf-8")


@app.get("/app.js", include_in_schema=False)
def app_js() -> FileResponse:
    return _static("app.js", "application/javascript; charset=utf-8")


@app.get("/styles.css", include_in_schema=False)
def styles_css() -> FileResponse:
    return _static("styles.css", "text/css; charset=utf-8")


@app.get("/health")
def health() -> dict:
    snap = store.snapshot()
    return {"ok": True, "data_dir_kind": snap.kind, "version": snap.version,
            "vss": {"ready": clients.vss_ready, **live.status()}, "cosmos": clients.cosmos.available,
            "llm": {"available": bool(getattr(clients.llm, "available", True)),
                    "kind": type(clients.llm).__name__,
                    "model": getattr(clients.llm, "_model", None) or ""},
            "clip_cache": clips.status()}


@app.get("/api/overview")
def api_overview() -> dict:
    return app_data.overview(store.snapshot())


@app.get("/api/videos")
def api_videos() -> dict:
    snap = store.snapshot()
    return {**snap.videos, "sites": snap.sites, "data_dir_kind": snap.kind, "version": snap.version}


@app.get("/api/segments")
def api_segments(site_id: str | None = None, camera: str | None = None) -> list[dict]:
    return [s for s in store.snapshot().segments
            if (not site_id or s.get("site_id") == site_id) and (not camera or s.get("camera") == camera)]


@app.get("/api/events")
def api_events() -> list[dict]:
    return store.snapshot().events


@app.get("/api/utilization")
def api_utilization() -> dict:
    snap = store.snapshot()
    return {"cameras": snap.util_cameras, "flags": snap.flags}


@app.get("/api/recommendations")
def api_recommendations() -> dict:
    snap = store.snapshot()
    return {**snap.recommendations_doc, "recommendations": snap.recommendations, "shift_report_md": snap.shift_report_md}


@app.get("/api/clip")
def api_clip(request: Request, source: str = Query(..., max_length=2048)):
    resolved = live.resolve(source, store.snapshot())
    if not resolved:
        return error(403, "source is not part of this deployment's footage")
    cached = clips.get(resolved)
    if cached:
        return FileResponse(cached, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})
    clips.fetch_async(resolved)
    try:
        upstream = clients.vss().open_stream(resolved, request.headers.get("range"))
    except Exception as e:  # noqa: BLE001
        clients.reset(e)
        return error(502, f"video stream unavailable ({safe_error(e)})")
    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        return error(status if status in (404, 416) else 502, f"video stream returned HTTP {status}")
    headers = {k: upstream.headers[k] for k in PASS_HEADERS if k in upstream.headers}
    headers.setdefault("Accept-Ranges", "bytes")
    headers["Cache-Control"] = "private, max-age=3600"
    ctype = upstream.headers.get("Content-Type", "")
    return StreamingResponse(iter_stream(upstream), status_code=upstream.status_code, headers=headers,
                             media_type=ctype if ctype.startswith("video/") else "video/mp4")


@app.get("/api/detections")
def api_detections(source: str = Query(..., max_length=2048), stride: int = Query(3, ge=1, le=30)):
    snap = store.snapshot()
    resolved = live.resolve(source, snap)
    if not resolved:
        return error(403, "source is not part of this deployment's footage")
    try:
        data = detections.get(resolved, stride, snap)
    except Exception as e:  # noqa: BLE001
        clients.reset(e)
        return error(502, f"detections unavailable ({safe_error(e)})")
    return JSONResponse(data, headers={"Cache-Control": "private, max-age=600"})


class AskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    lang: str | None = None


@app.post("/api/ask")
def api_ask(body: AskIn):
    question = body.question.strip()
    if not question:
        return error(400, "question is empty")
    return copilot.ask(question, store.snapshot(), body.lang)


class ReportIn(BaseModel):
    site_id: str | None = None
    camera: str | None = None
    mode: str = "ai"
    lang: str = "en"


@app.post("/api/report")
def api_report(body: ReportIn):
    snap = store.snapshot()
    if body.site_id and body.site_id != "all" and body.site_id not in snap.site_by_id:
        return error(404, f"unknown site {body.site_id}")
    return copilot.report(snap, body.site_id, body.camera or None, body.mode, body.lang)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="info",
                proxy_headers=True, forwarded_allow_ips="*", timeout_keep_alive=30)
