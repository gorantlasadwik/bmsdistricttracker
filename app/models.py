"""
ShowPulser Data Models
All core Pydantic models used across parsers, compare engine, and notifiers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ShowEntry(BaseModel):
    """Normalised representation of a single theatre's show listing."""

    theatre: str
    shows: list[str] = Field(default_factory=list)
    """List of show times, e.g. ['09:00', '12:30', '15:45']"""

    formats: list[str] = Field(default_factory=list)
    """Formats available, e.g. ['IMAX', '3D', '4DX']"""

    language: str = ""
    """Primary language of the listing, e.g. 'English', 'Tamil'"""

    booking_open: bool = False
    """True if 'Book Tickets' is available; False if 'Coming Soon' / 'Remind Me'"""

    booking_url: str | None = None
    """Direct booking link if available"""

    def shows_set(self) -> set[str]:
        return set(self.shows)

    def formats_set(self) -> set[str]:
        return {f.upper() for f in self.formats}


class SourceSnapshot(BaseModel):
    """Complete parsed snapshot from one source (BMS or District) at a point in time."""

    source: Literal["bookmyshow", "district"]
    movie_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    url: str = ""
    theatres: list[ShowEntry] = Field(default_factory=list)

    def theatre_map(self) -> dict[str, ShowEntry]:
        """Return a dict keyed by theatre name for fast lookup."""
        return {t.theatre.strip().lower(): t for t in self.theatres}


class ChangeType(str):
    NEW_THEATRE = "new_theatre"
    NEW_SHOW = "new_show"
    NEW_FORMAT = "new_format"
    BOOKING_OPEN = "booking_open"
    SHOW_REMOVED = "show_removed"
    FORMAT_REMOVED = "format_removed"


class ChangeEvent(BaseModel):
    """Represents a single detected change between two snapshots."""

    type: str
    """One of: new_theatre, new_show, new_format, booking_open, show_removed, format_removed"""

    source: Literal["bookmyshow", "district"]
    theatre: str
    detail: str
    """Human-readable description of what changed"""

    booking_url: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MovieConfig(BaseModel):
    """A movie being actively monitored."""

    id: int | None = None
    name: str
    city: str = ""
    bms_url: str = ""
    district_url: str = ""
    interval: int = 180
    """Scan interval in seconds (±30s jitter applied by scheduler)"""

    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MovieCreate(BaseModel):
    """Request body for POST /movies."""

    name: str
    city: str = ""
    bms_url: str = ""
    district_url: str = ""
    interval: int = 180


class ScanStatus(BaseModel):
    """Status returned by GET /status."""

    running: bool
    uptime_seconds: float
    active_movies: int
    last_scan: datetime | None
    next_scan: datetime | None
    total_notifications_sent: int
