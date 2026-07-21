"""
ShowPulser Parsers – Base
Abstract base class that all source parsers must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import SourceSnapshot


class BaseParser(ABC):
    """
    Each source (BookMyShow, District, etc.) has its own parser subclass.
    All parsers output the same normalised SourceSnapshot.
    """

    @abstractmethod
    async def fetch(self, url: str, movie_name: str) -> SourceSnapshot:
        """
        Fetch and parse the given URL.

        Args:
            url: Full URL of the movie page on this source.
            movie_name: Human-readable movie name (for snapshot metadata).

        Returns:
            Normalised SourceSnapshot.

        Raises:
            Exception: On repeated fetch failure (after retries).
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the source identifier: 'bookmyshow' or 'district'."""
        ...
