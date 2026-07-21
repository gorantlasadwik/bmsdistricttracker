"""
ShowPulser – Scheduler
AsyncIOScheduler integrated into FastAPI's lifespan.
Runs scan_movie() for each active movie at the configured interval (±30s jitter).
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app import database as db
from app.browser import browser_pool
from app.compare import diff_snapshots, summarise_changes
from app.models import MovieConfig
from app.notifier.dispatcher import dispatch
from app.parsers.bms import BookMyShowParser
from app.parsers.district import DistrictParser

# Global scheduler instance (accessed by API for status checks)
scheduler = AsyncIOScheduler(timezone="UTC")

# Track last/next scan times
_last_scan: datetime | None = None
_scan_lock = asyncio.Lock()

_bms_parser = BookMyShowParser()
_district_parser = DistrictParser()


async def scan_movie(movie: MovieConfig, manual: bool = False) -> None:
    """Fetch + compare + notify for a single movie across all sources."""
    async with _scan_lock:
        global _last_scan
        _last_scan = datetime.utcnow()

    logger.info(f"[Scheduler] Starting scan for '{movie.name}' (id={movie.id}), manual={manual}")

    tasks = []
    if movie.bms_url:
        tasks.append(_scan_source(movie, _bms_parser, movie.bms_url))
    if movie.district_url:
        tasks.append(_scan_source(movie, _district_parser, movie.district_url))

    if not tasks:
        logger.warning(f"[Scheduler] '{movie.name}' has no URLs configured. Skipping.")
        return

    results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"[Scheduler] Scan task raised: {r}")
        elif r is not None:
            snapshots.append(r)

    # Send current status report if this is a manual trigger
    if manual and snapshots:
        try:
            from app.notifier.telegram import TelegramNotifier
            tel_notifier = TelegramNotifier()
            await tel_notifier.send_status_report(movie.name, snapshots)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send manual status report: {e}")

    logger.info(f"[Scheduler] Scan complete for '{movie.name}'")


async def _scan_source(movie: MovieConfig, parser, url: str) -> SourceSnapshot | None:
    """Single source scan: fetch → diff → notify → save."""
    source = parser.source_name
    log_id = await db.log_scan_start(movie.id, source)

    try:
        # Fetch fresh snapshot
        snapshot = await parser.fetch(url, movie.name)
        logger.info(
            f"[Scheduler] Fetched {len(snapshot.theatres)} theatre(s) from {source} for '{movie.name}'"
        )

        # Load previous snapshot for comparison
        old_snapshot = await db.get_last_snapshot(movie.id, source)

        # Diff
        changes = diff_snapshots(old_snapshot, snapshot)

        if changes:
            summary = summarise_changes(changes)
            logger.info(f"[Scheduler] Changes detected for '{movie.name}' on {source}: {summary}")

            # Dispatch notifications (with deduplication)
            sent_count = await dispatch(
                movie_id=movie.id,
                movie_name=movie.name,
                changes=changes,
                source_url=url,
            )
            logger.info(f"[Scheduler] {sent_count} notification(s) dispatched.")
        else:
            logger.debug(f"[Scheduler] No changes for '{movie.name}' on {source}.")

        # Save new snapshot
        await db.save_snapshot(movie.id, snapshot)
        await db.log_scan_end(log_id, "success")
        return snapshot

    except Exception as e:
        logger.error(f"[Scheduler] Error scanning {source} for '{movie.name}': {e}")
        await db.log_scan_end(log_id, "error", str(e))
        return None


async def schedule_movie(movie: MovieConfig) -> None:
    """Add a movie to the scheduler (called when a movie is added via API)."""
    jitter = random.randint(-30, 30)
    interval = max(60, movie.interval + jitter)

    scheduler.add_job(
        scan_movie,
        "interval",
        seconds=interval,
        args=[movie],
        id=f"movie_{movie.id}",
        replace_existing=True,
        name=f"Scan: {movie.name}",
    )
    logger.info(f"[Scheduler] Scheduled '{movie.name}' every {interval}s (±30s jitter applied)")


async def unschedule_movie(movie_id: int) -> None:
    """Remove a movie from the scheduler."""
    job_id = f"movie_{movie_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"[Scheduler] Removed job for movie_id={movie_id}")


async def start_scheduler() -> None:
    """Load all active movies and start the scheduler. Called at app startup."""
    movies = await db.get_all_movies()
    logger.info(f"[Scheduler] Loading {len(movies)} active movie(s)...")

    for movie in movies:
        await schedule_movie(movie)

    scheduler.start()
    logger.info("[Scheduler] Scheduler started.")


async def stop_scheduler() -> None:
    """Stop the scheduler cleanly. Called at app shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("[Scheduler] Scheduler stopped.")


def get_last_scan() -> datetime | None:
    return _last_scan


def get_next_scan() -> datetime | None:
    jobs = scheduler.get_jobs()
    if not jobs:
        return None
    next_times = [j.next_run_time for j in jobs if j.next_run_time]
    return min(next_times) if next_times else None
