"""
ShowPulser – Tests: Change Detection Engine
"""
import pytest
from datetime import datetime

from app.compare import diff_snapshots, summarise_changes
from app.models import ShowEntry, SourceSnapshot


def make_snapshot(theatres: list[dict], source: str = "bookmyshow") -> SourceSnapshot:
    return SourceSnapshot(
        source=source,
        movie_name="Test Movie",
        url="https://example.com",
        theatres=[ShowEntry(**t) for t in theatres],
    )


# ── New theatre detection ──────────────────────────────────────────────────────

def test_new_theatre_detected():
    old = make_snapshot([{"theatre": "PVR Palazzo", "shows": ["09:00"], "formats": [], "language": "English", "booking_open": True}])
    new = make_snapshot([
        {"theatre": "PVR Palazzo", "shows": ["09:00"], "formats": [], "language": "English", "booking_open": True},
        {"theatre": "INOX Forum", "shows": ["12:30"], "formats": [], "language": "English", "booking_open": False},
    ])
    changes = diff_snapshots(old, new)
    new_theatre_events = [c for c in changes if c.type == "new_theatre"]
    assert len(new_theatre_events) == 1
    assert "INOX Forum" in new_theatre_events[0].theatre


def test_no_change_returns_empty():
    snapshot = make_snapshot([{"theatre": "PVR Palazzo", "shows": ["09:00"], "formats": ["IMAX"], "language": "English", "booking_open": True}])
    changes = diff_snapshots(snapshot, snapshot)
    assert changes == []


def test_distance_suffix_ignored():
    """Dynamic distance strings like '99+ km away' should be stripped and not trigger new_theatre."""
    old = make_snapshot([{"theatre": "MovieMax PR Mall, Wall Tax Road, Chennai", "shows": ["09:00"], "formats": [], "language": "", "booking_open": True}])
    new = make_snapshot([{"theatre": "MovieMax PR Mall, Wall Tax Road, Chennai 99+ km away", "shows": ["09:00"], "formats": [], "language": "", "booking_open": True}])
    changes = diff_snapshots(old, new)
    assert changes == []


def test_first_run_returns_empty():
    """First run (old=None) should not trigger notifications."""
    new = make_snapshot([{"theatre": "AGS", "shows": ["09:00"], "formats": [], "language": "Tamil", "booking_open": False}])
    changes = diff_snapshots(None, new)
    assert changes == []


# ── New show time detection ────────────────────────────────────────────────────

def test_new_show_detected():
    old = make_snapshot([{"theatre": "PVR", "shows": ["09:00", "12:30"], "formats": [], "language": "", "booking_open": True}])
    new = make_snapshot([{"theatre": "PVR", "shows": ["09:00", "12:30", "15:45"], "formats": [], "language": "", "booking_open": True}])
    changes = diff_snapshots(old, new)
    show_events = [c for c in changes if c.type == "new_show"]
    assert len(show_events) == 1
    assert "15:45" in show_events[0].detail


def test_multiple_new_shows():
    old = make_snapshot([{"theatre": "PVR", "shows": ["09:00"], "formats": [], "language": "", "booking_open": False}])
    new = make_snapshot([{"theatre": "PVR", "shows": ["09:00", "12:00", "15:00", "18:00"], "formats": [], "language": "", "booking_open": False}])
    changes = diff_snapshots(old, new)
    show_events = [c for c in changes if c.type == "new_show"]
    assert len(show_events) == 3


# ── Format detection ───────────────────────────────────────────────────────────

def test_new_format_detected():
    old = make_snapshot([{"theatre": "PVR", "shows": [], "formats": ["2D"], "language": "", "booking_open": False}])
    new = make_snapshot([{"theatre": "PVR", "shows": [], "formats": ["2D", "IMAX"], "language": "", "booking_open": False}])
    changes = diff_snapshots(old, new)
    fmt_events = [c for c in changes if c.type == "new_format"]
    assert len(fmt_events) == 1
    assert "IMAX" in fmt_events[0].detail


def test_format_case_insensitive():
    """'imax' and 'IMAX' should be treated as the same format."""
    old = make_snapshot([{"theatre": "PVR", "shows": [], "formats": ["imax"], "language": "", "booking_open": False}])
    new = make_snapshot([{"theatre": "PVR", "shows": [], "formats": ["IMAX"], "language": "", "booking_open": False}])
    changes = diff_snapshots(old, new)
    fmt_events = [c for c in changes if c.type == "new_format"]
    assert len(fmt_events) == 0


# ── Booking open detection ─────────────────────────────────────────────────────

def test_booking_open_detected():
    old = make_snapshot([{"theatre": "AGS", "shows": [], "formats": [], "language": "", "booking_open": False}])
    new = make_snapshot([{"theatre": "AGS", "shows": ["10:00"], "formats": [], "language": "", "booking_open": True}])
    changes = diff_snapshots(old, new)
    booking_events = [c for c in changes if c.type == "booking_open"]
    assert len(booking_events) == 1


def test_booking_already_open_no_event():
    old = make_snapshot([{"theatre": "AGS", "shows": [], "formats": [], "language": "", "booking_open": True}])
    new = make_snapshot([{"theatre": "AGS", "shows": ["10:00"], "formats": [], "language": "", "booking_open": True}])
    changes = diff_snapshots(old, new)
    booking_events = [c for c in changes if c.type == "booking_open"]
    assert len(booking_events) == 0


# ── Source independence ────────────────────────────────────────────────────────

def test_source_preserved_in_events():
    old = make_snapshot([], source="district")
    new = make_snapshot([{"theatre": "SPI Cinemas", "shows": [], "formats": [], "language": "", "booking_open": False}], source="district")
    changes = diff_snapshots(old, new)
    assert all(c.source == "district" for c in changes)


# ── Summary ───────────────────────────────────────────────────────────────────

def test_summarise_changes():
    old = make_snapshot([])
    new = make_snapshot([
        {"theatre": "PVR", "shows": ["09:00"], "formats": [], "language": "", "booking_open": False},
        {"theatre": "INOX", "shows": [], "formats": [], "language": "", "booking_open": False},
    ])
    changes = diff_snapshots(old, new)
    summary = summarise_changes(changes)
    assert "New Theatre" in summary or "new_theatre" in summary.lower()


def test_summarise_empty():
    assert summarise_changes([]) == "No changes detected."
