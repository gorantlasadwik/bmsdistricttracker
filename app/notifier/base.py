"""
ShowPulser Notifiers – Base
Abstract base class for all notification channels.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import ChangeEvent


class BaseNotifier(ABC):
    """All notifiers implement this interface."""

    @abstractmethod
    async def send(
        self,
        movie_name: str,
        changes: list[ChangeEvent],
        source_url: str = "",
    ) -> bool:
        """
        Send a notification for the given list of changes.

        Returns:
            True if sent successfully, False otherwise.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier for this notifier (e.g. 'telegram')."""
        ...

    def _format_source_label(self, source: str, url: str = "") -> str:
        label = {
            "bookmyshow": "BookMyShow",
            "district": "District",
        }.get(source, source.title())
        date_str = self._extract_date(url)
        if date_str:
            return f"{label} ({date_str})"
        return label

    def _extract_date(self, url: str) -> str:
        if not url:
            return ""
        import re
        m1 = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", url)
        if m1:
            year, month, day = m1.groups()
            try:
                from datetime import date
                dt = date(int(year), int(month), int(day))
                return dt.strftime("%d %b %Y")
            except Exception:
                return f"{int(day)} {month}"

        m2 = re.search(r"/(\d{4})(\d{2})(\d{2})(?:[?/]|$)", url)
        if m2:
            year, month, day = m2.groups()
            try:
                from datetime import date
                dt = date(int(year), int(month), int(day))
                return dt.strftime("%d %b %Y")
            except Exception:
                return f"{int(day)} {month}"
        return ""

    def _group_changes_by_theatre(
        self, changes: list[ChangeEvent]
    ) -> dict[str, list[ChangeEvent]]:
        """Group a flat list of changes by theatre name."""
        grouped: dict[str, list[ChangeEvent]] = {}
        for c in changes:
            grouped.setdefault(c.theatre, []).append(c)
        return grouped
