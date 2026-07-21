"""
ShowPulser – BookMyShow Parser
Strategy: parse window.__INITIAL_STATE__ JSON injected into the HTML.

Data path (confirmed from live HTML):
  state["showtimesByEvent"]["showDates"][DATE]["dynamic"]["data"]["showtimeWidgets"]
      → find widget where type=="groupList"
      → widget["data"][0]["data"]  → list of venue-cards
      → each card:
          card["additionalData"]["venueCode"] → venue code
          card["showtimes"]                  → list of {title: "03:20 PM", screenAttr: "SC 1 DOLBY ATMOS"}

  state["showtimesByEvent"]["showDates"][DATE]["primaryStatic"]["data"]["venues"][venueCode]["venueName"]
      → "Rakki Cinemas: OMR, Kelambakkam"

Booking open = the card has ≥1 showtime entry.
If no __INITIAL_STATE__ or parse fails, fall back to DOM scraping.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from app.browser import browser_pool
from app.models import ShowEntry, SourceSnapshot
from app.parsers.base import BaseParser
from app.retry import with_retry


_BMS_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*)", re.DOTALL)
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*(AM|PM)\b", re.I)
_SHOWTIME_BTN_CLASS = "sc-1vhizuf-1"
_FORMAT_KEYWORDS = ["IMAX", "DOLBY", "ATMOS", "4DX", "3D", "LASER", "EPIQ", "4K", "ICE", "MX4D"]


class BookMyShowParser(BaseParser):

    @property
    def source_name(self) -> str:
        return "bookmyshow"

    @with_retry(max_attempts=3, base_delay=3.0, backoff=2.0)
    async def fetch(self, url: str, movie_name: str) -> SourceSnapshot:
        logger.info(f"[BMS] Fetching: {url}")

        async with browser_pool.new_page() as page:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(4)
                await page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception as e:
                logger.debug(f"[BMS] Load warning: {e}")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            html = await page.content()

        # Strategy 1: parse __INITIAL_STATE__ JSON
        snap = self._parse_state_json(html, url, movie_name)
        if snap.theatres:
            return snap

        logger.warning("[BMS] __INITIAL_STATE__ gave no theatres – falling back to DOM")
        return self._parse_dom(html, url, movie_name)

    # ── __INITIAL_STATE__ parser ──────────────────────────────────────────────
    def _parse_state_json(self, html: str, url: str, movie_name: str) -> SourceSnapshot:
        m = _BMS_STATE_RE.search(html)
        if not m:
            logger.debug("[BMS] __INITIAL_STATE__ not found in HTML")
            return SourceSnapshot(source="bookmyshow", movie_name=movie_name, url=url, theatres=[])

        try:
            raw = m.group(1)
            # Find the end of the JSON object using balanced brace counting
            depth = 0
            end = -1
            in_str = False
            escape_next = False
            for i, ch in enumerate(raw):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_str:
                    escape_next = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end == -1:
                raise ValueError("Could not find end of JSON object")
            state = json.loads(raw[:end])

        except Exception as e:
            logger.warning(f"[BMS] Failed to parse __INITIAL_STATE__: {e}")
            return SourceSnapshot(source="bookmyshow", movie_name=movie_name, url=url, theatres=[])

        theatres: list[ShowEntry] = []

        try:
            stbe = state.get("showtimesByEvent", {})
            show_dates = stbe.get("showDates", {})
            if not show_dates:
                return SourceSnapshot(source="bookmyshow", movie_name=movie_name, url=url, theatres=[])

            # Process all available dates
            for date_key, date_data in show_dates.items():
                # Static venue names
                static_venues: dict = (
                    date_data.get("primaryStatic", {})
                    .get("data", {})
                    .get("venues", {})
                )

                # Dynamic showtime widgets
                dynamic_widgets = (
                    date_data.get("dynamic", {})
                    .get("data", {})
                    .get("showtimeWidgets", [])
                )

                # Find groupList widget
                gl_widget = next(
                    (w for w in dynamic_widgets if w.get("type") == "groupList"),
                    None
                )
                if not gl_widget:
                    continue

                # Each item in gl_widget["data"] is a venueGroup
                for group in gl_widget.get("data", []):
                    for card in group.get("data", []):
                        if card.get("type") != "venue-card":
                            continue

                        venue_code = card.get("additionalData", {}).get("venueCode", "")
                        # Venue name from static data
                        name = static_venues.get(venue_code, {}).get("venueName", "").strip()
                        if not name or len(name) < 3:
                            continue

                        # Shows
                        raw_shows = card.get("showtimes", [])
                        shows: list[str] = []
                        formats: set[str] = set()

                        for st in raw_shows:
                            title = st.get("title", "").strip()  # e.g. "03:20 PM"
                            if title:
                                shows.append(title)
                            screen_attr = st.get("screenAttr", "").strip()  # e.g. "SC 1 DOLBY ATMOS"
                            for fmt in _extract_formats(screen_attr):
                                formats.add(fmt)

                        booking_open = bool(shows)

                        # Format hint from URL
                        url_fmt = _format_from_url(url)
                        if url_fmt:
                            formats.add(url_fmt)

                        theatres.append(ShowEntry(
                            theatre=name,
                            shows=sorted(set(shows)),
                            formats=sorted(formats),
                            booking_open=booking_open,
                            booking_url=url if booking_open else None,
                        ))

        except Exception as e:
            logger.warning(f"[BMS] Error walking __INITIAL_STATE__: {e}")

        logger.info(f"[BMS JSON] Parsed {len(theatres)} theatre(s)")
        return SourceSnapshot(source="bookmyshow", movie_name=movie_name, url=url, theatres=theatres)

    # ── DOM fallback ──────────────────────────────────────────────────────────
    def _parse_dom(self, html: str, url: str, movie_name: str) -> SourceSnapshot:
        """
        Fallback DOM parser using sc-1vhizuf-1 showtime buttons.
        Groups buttons by their nearest venue anchor (walk up to find anchor
        with href containing bookmyshow.com/cinemas).
        """
        soup = BeautifulSoup(html, "lxml")
        theatres: list[ShowEntry] = []

        btns = soup.find_all(
            lambda t: t.name and any(_SHOWTIME_BTN_CLASS in c for c in t.get("class", []))
        )
        logger.debug(f"[BMS DOM] Showtime buttons: {len(btns)}")

        # Group by container (nearest common parent that contains a cinema anchor)
        seen: set[int] = set()
        containers: list = []
        for btn in btns:
            el = btn.parent
            for _ in range(15):
                if el is None:
                    break
                anchor = el.find("a", href=re.compile(r"bookmyshow\.com/cinemas/"))
                if anchor and len(anchor.get_text(strip=True)) > 3:
                    eid = id(el)
                    if eid not in seen:
                        seen.add(eid)
                        containers.append(el)
                    break
                el = el.parent

        for ctr in containers:
            anchor = ctr.find("a", href=re.compile(r"bookmyshow\.com/cinemas/"))
            name = anchor.get_text(strip=True) if anchor else ""
            if not name:
                continue

            shows, formats = [], set()
            for btn in ctr.find_all(
                lambda t: t.name and any(_SHOWTIME_BTN_CLASS in c for c in t.get("class", []))
            ):
                text = btn.get_text(separator=" ", strip=True)
                m = _TIME_RE.search(text)
                if m:
                    shows.append(f"{m.group(1)} {m.group(2).upper()}")
                for fmt in _extract_formats(text):
                    formats.add(fmt)

            url_fmt = _format_from_url(url)
            if url_fmt:
                formats.add(url_fmt)

            theatres.append(ShowEntry(
                theatre=name,
                shows=sorted(set(shows)),
                formats=sorted(formats),
                booking_open=bool(shows),
                booking_url=url if shows else None,
            ))

        logger.info(f"[BMS DOM] Parsed {len(theatres)} theatre(s)")
        return SourceSnapshot(source="bookmyshow", movie_name=movie_name, url=url, theatres=theatres)


def _extract_formats(text: str) -> list[str]:
    t = text.upper()
    out = []
    if "IMAX" in t:
        out.append("IMAX")
    elif "4DX" in t:
        out.append("4DX")
    elif "EPIQ" in t:
        out.append("EPIQ")
    elif "DOLBY" in t or "ATMOS" in t:
        out.append("DOLBY ATMOS")
    elif "LASER" in t:
        out.append("LASER")
    if "3D" in t:
        out.append("3D")
    if "4K" in t:
        out.append("4K")
    return out


def _format_from_url(url: str) -> str | None:
    u = url.lower()
    if "epiq" in u:
        return "EPIQ 3D"
    if "imax" in u:
        return "IMAX"
    if "4dx" in u:
        return "4DX"
    return None
