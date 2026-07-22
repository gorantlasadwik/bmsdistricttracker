"""
ShowPulser Database Layer
Async SQLite via aiosqlite. Handles all persistence: movies, snapshots, notifications.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from app.config import settings
from app.models import MovieConfig, SourceSnapshot


DB_PATH = settings.database_path

_CREATE_MOVIES = """
CREATE TABLE IF NOT EXISTS movies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    city        TEXT DEFAULT '',
    bms_url     TEXT DEFAULT '',
    district_url TEXT DEFAULT '',
    interval    INTEGER DEFAULT 180,
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL
)
"""

_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id    INTEGER NOT NULL,
    source      TEXT NOT NULL,
    json_blob   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
)
"""

_CREATE_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id    INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    message_hash TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
)
"""

_CREATE_SCAN_LOG = """
CREATE TABLE IF NOT EXISTS scan_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id    INTEGER,
    source      TEXT,
    status      TEXT,
    error       TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT
)
"""

_CREATE_KNOWN_THEATRES = """
CREATE TABLE IF NOT EXISTS known_theatres (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id    INTEGER NOT NULL,
    source      TEXT NOT NULL,
    theatre_key TEXT NOT NULL,
    theatre_name TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    UNIQUE(movie_id, source, theatre_key),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
)
"""


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute(_CREATE_MOVIES)
        await db.execute(_CREATE_SNAPSHOTS)
        await db.execute(_CREATE_NOTIFICATIONS)
        await db.execute(_CREATE_SCAN_LOG)
        await db.execute(_CREATE_KNOWN_THEATRES)
        await db.commit()
    logger.info(f"Database initialised at {DB_PATH}")
    await _auto_seed()


async def _auto_seed() -> None:
    """Insert initial movies if database is empty."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM movies") as cursor:
            count = (await cursor.fetchone())[0]

    if count == 0:
        logger.info("[Database] Empty database detected. Auto-seeding default movies.")
        movies = [
            MovieConfig(
                name="Spider-Man: Brand New Day (Regular/3D)",
                city="Chennai",
                bms_url="https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260801",
                district_url="https://www.district.in/movies/spider-man-brand-new-day-movie-tickets-in-chennai-MV194537?frmtid=rrfdpndypd&fromdate=2026-08-01",
                interval=180,
                enabled=True
            ),
            MovieConfig(
                name="Spider-Man: Brand New Day (EPIQ 3D)",
                city="Chennai",
                bms_url="https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day-epiq-3d/buytickets/ET00505581/20260801",
                district_url="",
                interval=180,
                enabled=True
            )
        ]
        for m in movies:
            await add_movie(m)


# ── Movie CRUD ─────────────────────────────────────────────────────────────────

async def add_movie(movie: MovieConfig) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO movies (name, city, bms_url, district_url, interval, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (movie.name, movie.city, movie.bms_url, movie.district_url,
             movie.interval, int(movie.enabled), datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_all_movies() -> list[MovieConfig]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM movies WHERE enabled = 1") as cursor:
            rows = await cursor.fetchall()
    return [_row_to_movie(r) for r in rows]


async def get_movie(movie_id: int) -> MovieConfig | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)) as cursor:
            row = await cursor.fetchone()
    return _row_to_movie(row) if row else None


async def delete_movie(movie_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
        await db.commit()
        return cursor.rowcount > 0


def _row_to_movie(row: Any) -> MovieConfig:
    return MovieConfig(
        id=row["id"],
        name=row["name"],
        city=row["city"],
        bms_url=row["bms_url"],
        district_url=row["district_url"],
        interval=row["interval"],
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ── Snapshot CRUD ──────────────────────────────────────────────────────────────

async def save_snapshot(movie_id: int, snapshot: SourceSnapshot) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO snapshots (movie_id, source, json_blob, timestamp) VALUES (?, ?, ?, ?)",
            (movie_id, snapshot.source, snapshot.model_dump_json(), snapshot.timestamp.isoformat()),
        )
        # Keep only last 10 snapshots per movie+source
        await db.execute(
            """DELETE FROM snapshots WHERE id NOT IN (
                SELECT id FROM snapshots WHERE movie_id=? AND source=?
                ORDER BY timestamp DESC LIMIT 10
            ) AND movie_id=? AND source=?""",
            (movie_id, snapshot.source, movie_id, snapshot.source),
        )
        await db.commit()


async def get_last_snapshot(movie_id: int, source: str) -> SourceSnapshot | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT json_blob FROM snapshots WHERE movie_id=? AND source=? ORDER BY timestamp DESC LIMIT 1",
            (movie_id, source),
        ) as cursor:
            row = await cursor.fetchone()
    if row:
        return SourceSnapshot.model_validate_json(row[0])
    return None


async def get_known_theatre_keys(movie_id: int, source: str) -> set[str]:
    """Return set of all canonical theatre keys ever recorded for a movie and source."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT theatre_key FROM known_theatres WHERE movie_id=? AND source=?",
            (movie_id, source),
        ) as cursor:
            rows = await cursor.fetchall()
    return {r[0] for r in rows}


async def update_known_theatres(movie_id: int, source: str, theatres: list[ShowEntry]) -> None:
    """Upsert list of parsed theatres into known_theatres table."""
    if not theatres:
        return

    from app.models import normalize_theatre_key
    now_iso = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        for t in theatres:
            key = normalize_theatre_key(t.theatre)
            if not key:
                continue
            await db.execute(
                """INSERT INTO known_theatres (movie_id, source, theatre_key, theatre_name, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(movie_id, source, theatre_key) DO UPDATE SET
                       last_seen = excluded.last_seen,
                       theatre_name = excluded.theatre_name""",
                (movie_id, source, key, t.theatre, now_iso, now_iso),
            )
        await db.commit()


# ── Notification dedup ─────────────────────────────────────────────────────────

def _make_hash(movie_id: int, change_type: str, detail: str) -> str:
    payload = f"{movie_id}:{change_type}:{detail}"
    return hashlib.sha256(payload.encode()).hexdigest()


async def was_notified(movie_id: int, change_type: str, detail: str) -> bool:
    """Return True if this exact change was already notified (within last 24h)."""
    h = _make_hash(movie_id, change_type, detail)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM notifications WHERE movie_id=? AND message_hash=? "
            "AND sent_at > datetime('now', '-24 hours')",
            (movie_id, h),
        ) as cursor:
            row = await cursor.fetchone()
    return row is not None


async def record_notification(movie_id: int, change_type: str, detail: str) -> None:
    h = _make_hash(movie_id, change_type, detail)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO notifications (movie_id, change_type, message_hash, sent_at) VALUES (?, ?, ?, ?)",
            (movie_id, change_type, h, datetime.utcnow().isoformat()),
        )
        await db.commit()


# ── Stats ──────────────────────────────────────────────────────────────────────

async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM movies WHERE enabled=1") as c:
            active_movies = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM notifications") as c:
            total_notifications = (await c.fetchone())[0]
        async with db.execute(
            "SELECT MAX(timestamp) FROM snapshots"
        ) as c:
            last_scan_row = await c.fetchone()
            last_scan = last_scan_row[0] if last_scan_row else None
    return {
        "active_movies": active_movies,
        "total_notifications": total_notifications,
        "last_scan": last_scan,
    }


async def get_movie_history(movie_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT change_type, sent_at FROM notifications WHERE movie_id=? "
            "ORDER BY sent_at DESC LIMIT ?",
            (movie_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ── Scan Log ───────────────────────────────────────────────────────────────────

async def log_scan_start(movie_id: int | None, source: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO scan_log (movie_id, source, status, started_at) VALUES (?, ?, ?, ?)",
            (movie_id, source, "running", datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def log_scan_end(log_id: int, status: str, error: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE scan_log SET status=?, error=?, finished_at=? WHERE id=?",
            (status, error, datetime.utcnow().isoformat(), log_id),
        )
        await db.commit()
