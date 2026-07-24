"""
ShowPulser Database Layer
Supports both local SQLite (via aiosqlite) AND external PostgreSQL / Cloud DB (via asyncpg).
Handles all persistence: movies, snapshots, notifications, known_theatres.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from app.config import settings
from app.models import MovieConfig, ShowEntry, SourceSnapshot

try:
    import asyncpg
except ImportError:
    asyncpg = None


DB_URL = settings.database_url or os.environ.get("DATABASE_URL", "")
DB_PATH = settings.database_path


def _is_postgres() -> bool:
    url = DB_URL or os.environ.get("DATABASE_URL", "")
    return bool(url and (url.startswith("postgres://") or url.startswith("postgresql://")))


def _get_pg_url() -> str:
    url = DB_URL or os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


async def _get_pg_conn():
    if not asyncpg:
        raise ImportError("asyncpg package is required for PostgreSQL database connections.")
    return await asyncpg.connect(_get_pg_url())


# ── PostgreSQL DDL ─────────────────────────────────────────────────────────────

_PG_CREATE_MOVIES = """
CREATE TABLE IF NOT EXISTS movies (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    city        TEXT DEFAULT '',
    bms_url     TEXT DEFAULT '',
    district_url TEXT DEFAULT '',
    interval    INTEGER DEFAULT 180,
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL
);
"""

_PG_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          SERIAL PRIMARY KEY,
    movie_id    INTEGER NOT NULL,
    source      TEXT NOT NULL,
    json_blob   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
"""

_PG_CREATE_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id          SERIAL PRIMARY KEY,
    movie_id    INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    message_hash TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
"""

_PG_CREATE_SCAN_LOG = """
CREATE TABLE IF NOT EXISTS scan_log (
    id          SERIAL PRIMARY KEY,
    movie_id    INTEGER,
    source      TEXT,
    status      TEXT,
    error       TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT
);
"""

_PG_CREATE_KNOWN_THEATRES = """
CREATE TABLE IF NOT EXISTS known_theatres (
    id          SERIAL PRIMARY KEY,
    movie_id    INTEGER NOT NULL,
    source      TEXT NOT NULL,
    theatre_key TEXT NOT NULL,
    theatre_name TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    UNIQUE(movie_id, source, theatre_key),
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
"""

# ── SQLite DDL ─────────────────────────────────────────────────────────────────

_SQLITE_CREATE_MOVIES = """
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

_SQLITE_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id    INTEGER NOT NULL,
    source      TEXT NOT NULL,
    json_blob   TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
)
"""

_SQLITE_CREATE_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_id    INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    message_hash TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
)
"""

_SQLITE_CREATE_SCAN_LOG = """
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

_SQLITE_CREATE_KNOWN_THEATRES = """
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
    if _is_postgres():
        logger.info("[Database] Initialising PostgreSQL Cloud Database...")
        conn = await _get_pg_conn()
        try:
            await conn.execute(_PG_CREATE_MOVIES)
            await conn.execute(_PG_CREATE_SNAPSHOTS)
            await conn.execute(_PG_CREATE_NOTIFICATIONS)
            await conn.execute(_PG_CREATE_SCAN_LOG)
            await conn.execute(_PG_CREATE_KNOWN_THEATRES)
        finally:
            await conn.close()
        logger.info("[Database] PostgreSQL Cloud Database initialised ✓")
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute(_SQLITE_CREATE_MOVIES)
            await db.execute(_SQLITE_CREATE_SNAPSHOTS)
            await db.execute(_SQLITE_CREATE_NOTIFICATIONS)
            await db.execute(_SQLITE_CREATE_SCAN_LOG)
            await db.execute(_SQLITE_CREATE_KNOWN_THEATRES)
            await db.commit()
        logger.info(f"[Database] Local SQLite database initialised at {DB_PATH}")

    await _auto_seed()


async def _auto_seed() -> None:
    """Insert initial movies if database is empty."""
    movies_count = 0
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            movies_count = await conn.fetchval("SELECT COUNT(*) FROM movies")
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM movies") as cursor:
                movies_count = (await cursor.fetchone())[0]

    if movies_count == 0:
        logger.info("[Database] Empty database detected. Auto-seeding default movies.")
        movies = [
            MovieConfig(
                name="Spider-Man: Brand New Day (Regular/3D)",
                city="Chennai",
                bms_url="https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260801?etCodes=*&language=english&refEventCode=ET00502600",
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
    created_at_iso = datetime.utcnow().isoformat()
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            movie_id = await conn.fetchval(
                "INSERT INTO movies (name, city, bms_url, district_url, interval, enabled, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                movie.name, movie.city, movie.bms_url, movie.district_url,
                movie.interval, int(movie.enabled), created_at_iso
            )
            return movie_id
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO movies (name, city, bms_url, district_url, interval, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (movie.name, movie.city, movie.bms_url, movie.district_url,
                 movie.interval, int(movie.enabled), created_at_iso),
            )
            await db.commit()
            return cursor.lastrowid


async def get_all_movies() -> list[MovieConfig]:
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            rows = await conn.fetch("SELECT * FROM movies WHERE enabled = 1")
            return [_row_to_movie(dict(r)) for r in rows]
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM movies WHERE enabled = 1") as cursor:
                rows = await cursor.fetchall()
        return [_row_to_movie(dict(r)) for r in rows]


async def get_movie(movie_id: int) -> MovieConfig | None:
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            row = await conn.fetchrow("SELECT * FROM movies WHERE id = $1", movie_id)
            return _row_to_movie(dict(row)) if row else None
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)) as cursor:
                row = await cursor.fetchone()
        return _row_to_movie(dict(row)) if row else None


async def delete_movie(movie_id: int) -> bool:
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            res = await conn.execute("DELETE FROM movies WHERE id = $1", movie_id)
            return "DELETE 0" not in res
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
            await db.commit()
            return cursor.rowcount > 0


def _row_to_movie(row: dict) -> MovieConfig:
    created_at_val = row["created_at"]
    if isinstance(created_at_val, str):
        created_at_dt = datetime.fromisoformat(created_at_val)
    else:
        created_at_dt = created_at_val

    return MovieConfig(
        id=row["id"],
        name=row["name"],
        city=row["city"],
        bms_url=row["bms_url"],
        district_url=row["district_url"],
        interval=row["interval"],
        enabled=bool(row["enabled"]),
        created_at=created_at_dt,
    )


# ── Snapshot CRUD ──────────────────────────────────────────────────────────────

async def save_snapshot(movie_id: int, snapshot: SourceSnapshot) -> None:
    ts_iso = snapshot.timestamp.isoformat()
    blob = snapshot.model_dump_json()

    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            await conn.execute(
                "INSERT INTO snapshots (movie_id, source, json_blob, timestamp) VALUES ($1, $2, $3, $4)",
                movie_id, snapshot.source, blob, ts_iso
            )
            # Retain last 10 snapshots
            await conn.execute(
                """DELETE FROM snapshots WHERE id NOT IN (
                    SELECT id FROM snapshots WHERE movie_id=$1 AND source=$2
                    ORDER BY timestamp DESC LIMIT 10
                ) AND movie_id=$3 AND source=$4""",
                movie_id, snapshot.source, movie_id, snapshot.source
            )
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO snapshots (movie_id, source, json_blob, timestamp) VALUES (?, ?, ?, ?)",
                (movie_id, snapshot.source, blob, ts_iso),
            )
            await db.execute(
                """DELETE FROM snapshots WHERE id NOT IN (
                    SELECT id FROM snapshots WHERE movie_id=? AND source=?
                    ORDER BY timestamp DESC LIMIT 10
                ) AND movie_id=? AND source=?""",
                (movie_id, snapshot.source, movie_id, snapshot.source),
            )
            await db.commit()


async def get_last_snapshot(movie_id: int, source: str) -> SourceSnapshot | None:
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            row = await conn.fetchrow(
                "SELECT json_blob FROM snapshots WHERE movie_id=$1 AND source=$2 ORDER BY timestamp DESC LIMIT 1",
                movie_id, source
            )
            if row:
                return SourceSnapshot.model_validate_json(row["json_blob"])
            return None
        finally:
            await conn.close()
    else:
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
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            rows = await conn.fetch(
                "SELECT theatre_key FROM known_theatres WHERE movie_id=$1 AND source=$2",
                movie_id, source
            )
            return {r["theatre_key"] for r in rows}
        finally:
            await conn.close()
    else:
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

    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            for t in theatres:
                key = normalize_theatre_key(t.theatre)
                if not key:
                    continue
                await conn.execute(
                    """INSERT INTO known_theatres (movie_id, source, theatre_key, theatre_name, first_seen, last_seen)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT(movie_id, source, theatre_key) DO UPDATE SET
                           last_seen = EXCLUDED.last_seen,
                           theatre_name = EXCLUDED.theatre_name""",
                    movie_id, source, key, t.theatre, now_iso, now_iso
                )
        finally:
            await conn.close()
    else:
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
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()

    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            row = await conn.fetchrow(
                "SELECT 1 FROM notifications WHERE movie_id=$1 AND message_hash=$2 AND sent_at > $3",
                movie_id, h, cutoff
            )
            return row is not None
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM notifications WHERE movie_id=? AND message_hash=? AND sent_at > ?",
                (movie_id, h, cutoff),
            ) as cursor:
                row = await cursor.fetchone()
        return row is not None


async def record_notification(movie_id: int, change_type: str, detail: str) -> None:
    h = _make_hash(movie_id, change_type, detail)
    now_iso = datetime.utcnow().isoformat()

    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            await conn.execute(
                "INSERT INTO notifications (movie_id, change_type, message_hash, sent_at) VALUES ($1, $2, $3, $4)",
                movie_id, change_type, h, now_iso
            )
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO notifications (movie_id, change_type, message_hash, sent_at) VALUES (?, ?, ?, ?)",
                (movie_id, change_type, h, now_iso),
            )
            await db.commit()


# ── Stats ──────────────────────────────────────────────────────────────────────

async def get_stats() -> dict:
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            active_movies = await conn.fetchval("SELECT COUNT(*) FROM movies WHERE enabled=1")
            total_notifications = await conn.fetchval("SELECT COUNT(*) FROM notifications")
            last_scan = await conn.fetchval("SELECT MAX(timestamp) FROM snapshots")
            return {
                "active_movies": active_movies or 0,
                "total_notifications": total_notifications or 0,
                "last_scan": last_scan,
            }
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM movies WHERE enabled=1") as c:
                active_movies = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM notifications") as c:
                total_notifications = (await c.fetchone())[0]
            async with db.execute("SELECT MAX(timestamp) FROM snapshots") as c:
                last_scan_row = await c.fetchone()
                last_scan = last_scan_row[0] if last_scan_row else None
        return {
            "active_movies": active_movies,
            "total_notifications": total_notifications,
            "last_scan": last_scan,
        }


async def get_movie_history(movie_id: int, limit: int = 20) -> list[dict]:
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            rows = await conn.fetch(
                "SELECT change_type, sent_at FROM notifications WHERE movie_id=$1 "
                "ORDER BY sent_at DESC LIMIT $2",
                movie_id, limit
            )
            return [dict(r) for r in rows]
        finally:
            await conn.close()
    else:
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
    now_iso = datetime.utcnow().isoformat()
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            log_id = await conn.fetchval(
                "INSERT INTO scan_log (movie_id, source, status, started_at) VALUES ($1, $2, $3, $4) RETURNING id",
                movie_id, source, "running", now_iso
            )
            return log_id
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO scan_log (movie_id, source, status, started_at) VALUES (?, ?, ?, ?)",
                (movie_id, source, "running", now_iso),
            )
            await db.commit()
            return cursor.lastrowid


async def log_scan_end(log_id: int, status: str, error: str = "") -> None:
    now_iso = datetime.utcnow().isoformat()
    if _is_postgres():
        conn = await _get_pg_conn()
        try:
            await conn.execute(
                "UPDATE scan_log SET status=$1, error=$2, finished_at=$3 WHERE id=$4",
                status, error, now_iso, log_id
            )
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE scan_log SET status=?, error=?, finished_at=? WHERE id=?",
                (status, error, now_iso, log_id),
            )
            await db.commit()
