"""
ShowPulser – FastAPI Application
Provides REST API for managing movies and checking status.
Integrates with scheduler via lifespan context manager.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app import database as db
from app import scheduler as sched
from app.browser import browser_pool
from app.config import settings
from app.models import MovieConfig, MovieCreate, ScanStatus

# ── Logging setup ──────────────────────────────────────────────────────────────
_LOG_DIR = Path(settings.logs_dir)
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.add(
    str(_LOG_DIR / "showpulser_{time:YYYY-MM-DD}.log"),
    rotation="00:00",  # New file daily at midnight
    retention="7 days",
    level=settings.log_level,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
)

_START_TIME = time.time()


import os
import httpx
import asyncio

async def self_pinger():
    url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("EXTERNAL_URL")
    if not url:
        logger.info("[Pinger] RENDER_EXTERNAL_URL not set. Self-pinger disabled (normal for local runs).")
        return
    
    health_url = f"{url.rstrip('/')}/health"
    logger.info(f"[Pinger] Starting self-pinger task targeting: {health_url}")
    
    while True:
        await asyncio.sleep(600)  # Ping every 10 minutes
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(health_url)
                logger.info(f"[Pinger] Self-ping status: {resp.status_code}")
        except Exception as e:
            logger.error(f"[Pinger] Self-ping failed: {e}")


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, start browser pool, start scheduler. Shutdown: reverse."""
    logger.info("=" * 60)
    logger.info("ShowPulser starting up...")

    await db.init_db()
    await browser_pool.start()
    await sched.start_scheduler()
    
    # Start self-pinger background task
    pinger_task = asyncio.create_task(self_pinger())

    logger.info("ShowPulser is running ✓")
    logger.info("=" * 60)

    yield

    logger.info("ShowPulser shutting down...")
    pinger_task.cancel()
    await sched.stop_scheduler()
    await browser_pool.stop()
    logger.info("ShowPulser stopped.")


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ShowPulser",
    description="24×7 Movie Show Monitor — BookMyShow & District",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static dashboard
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    """Simple health check for hosting platforms."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status", response_model=ScanStatus, tags=["System"])
async def status():
    """Return current monitoring status."""
    stats = await db.get_stats()
    return ScanStatus(
        running=sched.scheduler.running,
        uptime_seconds=round(time.time() - _START_TIME, 1),
        active_movies=stats["active_movies"],
        last_scan=datetime.fromisoformat(stats["last_scan"]) if stats.get("last_scan") else sched.get_last_scan(),
        next_scan=sched.get_next_scan(),
        total_notifications_sent=stats["total_notifications"],
    )


@app.get("/movies", tags=["Movies"])
async def list_movies():
    """List all actively monitored movies."""
    movies = await db.get_all_movies()
    return {"movies": [m.model_dump() for m in movies]}


@app.post("/movies", status_code=201, tags=["Movies"])
async def add_movie(body: MovieCreate):
    """Add a new movie to monitor."""
    if not body.bms_url and not body.district_url:
        raise HTTPException(status_code=400, detail="At least one URL (bms_url or district_url) is required.")

    movie = MovieConfig(**body.model_dump())
    movie_id = await db.add_movie(movie)
    movie.id = movie_id

    # Add to live scheduler immediately
    await sched.schedule_movie(movie)

    logger.info(f"[API] Added movie '{movie.name}' (id={movie_id})")
    return {"id": movie_id, "message": f"Now monitoring '{movie.name}'"}


@app.delete("/movies/{movie_id}", tags=["Movies"])
async def remove_movie(movie_id: int):
    """Stop monitoring a movie and delete its data."""
    movie = await db.get_movie(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found.")

    await sched.unschedule_movie(movie_id)
    deleted = await db.delete_movie(movie_id)

    logger.info(f"[API] Removed movie '{movie.name}' (id={movie_id})")
    return {"message": f"Stopped monitoring '{movie.name}'"}


@app.post("/movies/{movie_id}/scan", tags=["Movies"])
async def trigger_scan(movie_id: int):
    """Trigger an immediate scan for a specific movie."""
    movie = await db.get_movie(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found.")

    import asyncio
    asyncio.create_task(sched.scan_movie(movie, manual=True))

    return {"message": f"Scan triggered for '{movie.name}'"}


@app.get("/movies/{movie_id}/history", tags=["Movies"])
async def movie_history(movie_id: int, limit: int = 20):
    """Get recent notification history for a movie."""
    movie = await db.get_movie(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found.")

    history = await db.get_movie_history(movie_id, limit)
    return {"movie": movie.name, "history": history}


@app.get("/dashboard", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard():
    """Serve the web dashboard."""
    dashboard_path = _STATIC_DIR / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(content=dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)
