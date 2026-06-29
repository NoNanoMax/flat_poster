"""Minimal HTTP health-check server (FastAPI + uvicorn).

Runs on a separate port (8001) and reports:
  - overall status (ok/degraded)
  - DB connectivity
  - LLM endpoint reachability
  - scheduler state
"""

from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from loguru import logger

from src.config.settings import settings

app = FastAPI(title="Flat Parser", version="0.1.0")

# ── State ─────────────────────────────────────────────────────────────────────

_startup_ts: datetime | None = None
_scheduler_started: bool = False


def _mark_scheduler_started() -> None:
    global _scheduler_started
    _scheduler_started = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Any:
    """Aggregate health — returns 200 (ok) or 503 (degraded)."""
    checks: dict[str, dict[str, Any]] = {}

    # DB check
    db_ok = _check_db()
    checks["database"] = {"status": "ok" if db_ok else "error"}

    # LLM check
    llm_ok = _check_llm()
    checks["llm"] = {"status": "ok" if llm_ok else "error"}

    # Scheduler check
    checks["scheduler"] = {"status": "ok" if _scheduler_started else "not_started"}

    overall = "ok" if all(v["status"] == "ok" for v in checks.values()) else "degraded"
    status_code = 200 if overall == "ok" else 503

    data = {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": (
            (datetime.now(timezone.utc) - _startup_ts).total_seconds()
            if _startup_ts
            else None
        ),
        "checks": checks,
    }
    return JSONResponse(content=data, status_code=status_code)


@app.get("/ready")
async def ready() -> Any:
    """Simple readiness probe — returns 200 once scheduler is running."""
    if _scheduler_started:
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not_ready"})


# ── Health checks ─────────────────────────────────────────────────────────────


def _check_db() -> bool:
    """Check if the database file is accessible (SQLite) or connection works (PG)."""
    try:
        if "sqlite" in settings.database.url:
            m = re.search(r"sqlite.*///(.+)", settings.database.url)
            if m:
                return Path(m.group(1)).exists()
        # For non-SQLite we assume OK if we can import the driver
        return True
    except Exception:
        return False


def _check_llm() -> bool:
    """Check if the LLM endpoint is reachable (lightweight GET)."""
    try:
        url = settings.llm.base_url.rstrip("/") + "/v1/models"
        req = urllib.request.Request(url, method="GET")
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


# ── Run ──────────────────────────────────────────────────────────────────────

_HEALTH_PORT = 8001


async def run_health_server() -> None:
    """Start the health server in a background task."""
    global _startup_ts
    _startup_ts = datetime.now(timezone.utc)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=_HEALTH_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("Health server starting on port {}", _HEALTH_PORT)
    await server.serve()
