"""
ShowPulser – Change Detection Engine

Compares two SourceSnapshots and produces a list of ChangeEvents.
This is a pure function with no side effects — easy to unit test.
"""
from __future__ import annotations

from app.models import ChangeEvent, ChangeType, ShowEntry, SourceSnapshot, normalize_theatre_key


def diff_snapshots(
    old: SourceSnapshot | None,
    new: SourceSnapshot,
    known_theatre_keys: set[str] | None = None,
    notify_removals: bool = False,
) -> list[ChangeEvent]:
    """
    Compute all changes between two snapshots.

    Args:
        old: Previously stored snapshot (None if first run).
        new: Freshly fetched snapshot.
        known_theatre_keys: Optional set of canonical theatre keys ever recorded in DB history.
        notify_removals: If True, also emit events for removed shows/theatres.

    Returns:
        List of ChangeEvents (may be empty if nothing changed).
    """
    changes: list[ChangeEvent] = []

    if old is None:
        # First run — don't treat everything as "new", just store the baseline.
        return changes

    old_map = old.theatre_map()
    new_map = new.theatre_map()

    old_names = set(old_map.keys())
    new_names = set(new_map.keys())

    # ── New Theatres ───────────────────────────────────────────────────────────
    for name_key in new_names - old_names:
        entry = new_map[name_key]
        canon_key = normalize_theatre_key(entry.theatre)

        # Check if theatre was EVER seen before in DB history (prevents glitch alerts)
        if known_theatre_keys and canon_key in known_theatre_keys:
            continue

        shows_str = ", ".join(sorted(entry.shows)) if entry.shows else "TBA"
        fmts_str = ", ".join(sorted(entry.formats_set())) if entry.formats else ""
        detail = f"New Theatre Added: {entry.theatre}"
        changes.append(ChangeEvent(
            type=ChangeType.NEW_THEATRE,
            source=new.source,
            theatre=entry.theatre,
            detail=detail,
            before="Not Listed",
            after=shows_str,
            new_items=list(sorted(entry.shows)),
            booking_url=entry.booking_url,
        ))

    # ── Removed Theatres (optional) ────────────────────────────────────────────
    if notify_removals:
        for name_key in old_names - new_names:
            entry = old_map[name_key]
            changes.append(ChangeEvent(
                type="theatre_removed",
                source=new.source,
                theatre=entry.theatre,
                detail=f"{entry.theatre} no longer listed",
            ))

    # ── Per-Theatre Changes ────────────────────────────────────────────────────
    for name_key in new_names & old_names:
        old_entry = old_map[name_key]
        new_entry = new_map[name_key]

        changes.extend(_diff_theatre(old_entry, new_entry, new.source, notify_removals))

    return changes


def _diff_theatre(
    old: ShowEntry,
    new: ShowEntry,
    source: str,
    notify_removals: bool,
) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []

    # ── New show times (using Counter multiset diff to support multiple shows at same time) ──
    from collections import Counter
    old_counts = Counter(old.shows)
    new_counts = Counter(new.shows)
    added_counts = new_counts - old_counts

    if added_counts:
        before_str = ", ".join(sorted(old.shows)) if old.shows else "None"
        after_str = ", ".join(sorted(new.shows)) if new.shows else "None"
        added_list = sorted(list(added_counts.elements()))
        unique_added = sorted(list(set(added_list)))
        for show_time in added_list:
            events.append(ChangeEvent(
                type=ChangeType.NEW_SHOW,
                source=source,
                theatre=new.theatre,
                detail=f"New show at {show_time}",
                before=before_str,
                after=after_str,
                new_items=unique_added,
                booking_url=new.booking_url,
            ))

    # ── Removed show times (optional) ─────────────────────────────────────────
    if notify_removals:
        removed_counts = old_counts - new_counts
        for show_time in sorted(list(removed_counts.elements())):
            events.append(ChangeEvent(
                type=ChangeType.SHOW_REMOVED,
                source=source,
                theatre=new.theatre,
                detail=f"Show removed: {show_time}",
            ))

    # ── New formats ────────────────────────────────────────────────────────────
    added_formats = new.formats_set() - old.formats_set()
    for fmt in sorted(added_formats):
        events.append(ChangeEvent(
            type=ChangeType.NEW_FORMAT,
            source=source,
            theatre=new.theatre,
            detail=f"New format: {fmt}",
            booking_url=new.booking_url,
        ))

    # ── Booking opened ─────────────────────────────────────────────────────────
    if not old.booking_open and new.booking_open:
        events.append(ChangeEvent(
            type=ChangeType.BOOKING_OPEN,
            source=source,
            theatre=new.theatre,
            detail="Booking is now OPEN!",
            booking_url=new.booking_url,
        ))

    return events


def summarise_changes(changes: list[ChangeEvent]) -> str:
    """Return a one-line human-readable summary of a list of changes."""
    if not changes:
        return "No changes detected."

    counts: dict[str, int] = {}
    for c in changes:
        counts[c.type] = counts.get(c.type, 0) + 1

    parts = []
    for ctype, count in counts.items():
        label = ctype.replace("_", " ").title()
        parts.append(f"{count} {label}")

    return " | ".join(parts)
