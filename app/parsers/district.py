"""
ShowPulser – District Parser
Selectors confirmed via live HTML dump inspection.

Actual DOM structure (from debug_html/district.html):

  <ul class="MovieSessionsListing-module-scss-module__4rcn9q__sessionsListing">
    <li class="MovieSessionsListing-module-scss-module__4rcn9q__movieSessions
                MovieSessionsListing-module-scss-module__4rcn9q__cdpSessions">

      <div class="...col1">
        <div class="...details">
          MovieMax PR Mall, Wall Tax Road, Chennai
          <span>Allows cancellation</span>
        </div>
      </div>

      <ul class="...col2">
        <li class="...timeblock">
          <div class="...time">
            <span>10:30 AM</span>
          </div>
          <div class="...timeblock__sessionInfo">
            <span class="...timeblock__frmt">4K LASER DOLBY 7.1</span>
          </div>
          <span class="...timeblock__dim">3D</span>
        </li>
        ... more timeblocks ...
      </ul>
    </li>
  </ul>

Parsing strategy:
  1. Find all li.movieSessions
  2. Venue name = li > div.col1 > div.details text (strip "Allows cancellation" etc.)
  3. Showtimes = li > ul.col2 > li.timeblock (text = "10:30 AM | 4K LASER ... | 3D")
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from loguru import logger

from app.browser import browser_pool
from app.models import ShowEntry, SourceSnapshot
from app.parsers.base import BaseParser
from app.retry import with_retry


_DISTRICT_API_PATTERNS = [
    re.compile(r"district\.in/api", re.I),
    re.compile(r"api\.district\.in", re.I),
    re.compile(r"zomato\.com.*event", re.I),
]

# Confirmed CSS module class fragments (prefix before __hash__)
_MOVIE_SESSIONS_CLS = "movieSessions"  # li containing one venue
_COL1_CLS          = "col1"           # div: venue info column
_DETAILS_CLS       = "details"        # div: venue name text container
_COL2_CLS          = "col2"           # ul: showtime list
_TIMEBLOCK_CLS     = "timeblock"      # li: one show slot

_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*(AM|PM)\b", re.I)

# Noise text that appears inside venue name container
_NOISE_RE = re.compile(
    r"(allows?\s+cancellation|non-cancellable|non cancellable|\d+[\d\.\+]*\s*km(?:\s*away)?"
    r"|filling\s+fast|almost\s+full|available)",
    re.I
)


class DistrictParser(BaseParser):

    @property
    def source_name(self) -> str:
        return "district"

    @with_retry(max_attempts=3, base_delay=3.0, backoff=2.0)
    async def fetch(self, url: str, movie_name: str) -> SourceSnapshot:
        logger.info(f"[District] Fetching: {url}")
        intercepted: list[dict] = []

        async def on_response(resp) -> None:
            if any(p.search(resp.url) for p in _DISTRICT_API_PATTERNS):
                try:
                    if "json" in resp.headers.get("content-type", ""):
                        body = await resp.json()
                        intercepted.append({"url": resp.url, "data": body})
                except Exception:
                    pass

        async with browser_pool.new_page() as page:
            page.on("response", on_response)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await asyncio.sleep(4)
                await page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception as e:
                logger.debug(f"[District] Load warning: {e}")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            html = await page.content()

        if intercepted:
            snap = self._parse_xhr(intercepted, url, movie_name)
            if snap.theatres:
                return snap

        return self._parse_dom(html, url, movie_name)

    # ── XHR ──────────────────────────────────────────────────────────────────
    def _parse_xhr(self, responses, url, movie_name) -> SourceSnapshot:
        theatres = []
        for item in responses:
            theatres.extend(self._extract_xhr(item.get("data", {})))
        seen, unique = set(), []
        for t in theatres:
            k = t.theatre.lower().strip()
            if k not in seen:
                seen.add(k)
                unique.append(t)
        return SourceSnapshot(source="district", movie_name=movie_name, url=url, theatres=unique)

    def _extract_xhr(self, data: Any) -> list[ShowEntry]:
        out = []
        if isinstance(data, list):
            for x in data:
                out.extend(self._extract_xhr(x))
            return out
        if not isinstance(data, dict):
            return out
        venue_keys = {"venueName", "venue", "cinemaName", "theatreName", "eventVenue"}
        if any(k in data for k in venue_keys):
            e = self._xhr_entry(data)
            if e:
                return [e]
        for v in data.values():
            if isinstance(v, (dict, list)):
                out.extend(self._extract_xhr(v))
        return out

    def _xhr_entry(self, node: dict) -> ShowEntry | None:
        venue = node.get("venue", {})
        name = (isinstance(venue, dict) and venue.get("name", "")) or ""
        if not name:
            name = (node.get("venueName") or node.get("cinemaName") or
                    node.get("theatreName") or "").strip()
        if not name:
            return None
        shows = []
        for s in node.get("sessions", node.get("showtimes", node.get("times", []))):
            t = s.get("startTime", "") or s.get("time", "") if isinstance(s, dict) else str(s)
            if t and "T" in t:
                t = t.split("T")[1][:5]
            if t:
                shows.append(t)
        formats = [f.upper() for f in node.get("formats", []) if isinstance(f, str)]
        return ShowEntry(theatre=name, shows=shows, formats=formats,
                         booking_open=bool(shows), booking_url=None)

    # ── DOM (confirmed selectors) ─────────────────────────────────────────────
    def _parse_dom(self, html: str, url: str, movie_name: str) -> SourceSnapshot:
        soup = BeautifulSoup(html, "lxml")
        theatres: list[ShowEntry] = []

        # CSS selector for partial class match — confirmed working with soup.select()
        session_lis = soup.select("li[class*='movieSessions']")
        logger.debug(f"[District DOM] li[class*='movieSessions']: {len(session_lis)}")


        for li in session_lis:
            venue_name = self._get_venue_name(li)
            if not venue_name or len(venue_name) < 4:
                continue

            shows, formats = self._get_shows_formats(li)

            # booking open: times exist and not "Coming Soon"
            li_text = li.get_text(strip=True).lower()
            booking_open = bool(shows) and "coming soon" not in li_text

            # format from URL frmtid param
            url_fmt = _format_from_url(url)
            if url_fmt:
                formats.add(url_fmt)

            theatres.append(ShowEntry(
                theatre=venue_name,
                shows=sorted(set(shows)),
                formats=sorted(formats),
                booking_open=booking_open,
                booking_url=url if booking_open else None,
            ))

        logger.info(f"[District DOM] Parsed {len(theatres)} theatre(s)")
        return SourceSnapshot(source="district", movie_name=movie_name, url=url, theatres=theatres)

    def _get_venue_name(self, li: Tag) -> str:
        # col1 div → details div → text (strip cancellation/distance noise)
        col1 = li.select_one("[class*='col1']")
        if col1:
            details = col1.select_one("[class*='details']")
            if details:
                # Get direct text nodes and non-span children
                parts = []
                for node in details.children:
                    if isinstance(node, str):
                        parts.append(node.strip())
                    elif hasattr(node, "name") and node.name not in ("span", "small"):
                        parts.append(node.get_text(strip=True))
                name = " ".join(p for p in parts if p)
                name = _clean_name(name)
                if name and len(name) > 4:
                    return name
            raw = col1.get_text(separator=" ", strip=True)
            return _clean_name(raw)
        return ""

    def _get_shows_formats(self, li: Tag) -> tuple[list[str], set[str]]:
        shows: list[str] = []
        formats: set[str] = set()

        # col2 ul → li.timeblock items (CSS selector for partial class match)
        col2 = li.select_one("[class*='col2']")
        if col2:
            timeblocks = col2.select("li[class*='timeblock']")
        else:
            timeblocks = li.select("li[class*='timeblock']")

        for tb in timeblocks:
            text = tb.get_text(separator=" ", strip=True)
            m = _TIME_RE.search(text)
            if m:
                shows.append(f"{m.group(1)} {m.group(2).upper()}")
            text_upper = text.upper()
            if "IMAX" in text_upper:
                formats.add("IMAX")
            if "4DX" in text_upper:
                formats.add("4DX")
            if "DOLBY" in text_upper or "ATMOS" in text_upper:
                formats.add("DOLBY ATMOS")
            if "LASER" in text_upper:
                formats.add("LASER")
            if "4K" in text_upper:
                formats.add("4K")
            if "3D" in text_upper:
                formats.add("3D")
            if "2D" in text_upper:
                formats.add("2D")

        return shows, formats


def _clean_name(text: str) -> str:
    text = _NOISE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _format_from_url(url: str) -> str | None:
    u = url.lower()
    if "imax" in u:
        return "IMAX"
    if "4dx" in u:
        return "4DX"
    if "epiq" in u:
        return "EPIQ"
    if "frmtid=rrfdpndypd" in u:
        return "3D"
    return None
