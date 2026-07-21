"""
Quick fetch test – no notifications, no database, no scheduler.
Just: open URL -> parse -> print results.

Run:  python fetch_test.py
"""
import asyncio
import sys
from pathlib import Path

# Force UTF-8 output on Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))

# ── Real URLs ──────────────────────────────────────────────────────────────────
TESTS = [
    {
        "source": "BMS (English 3D)",
        "parser": "bms",
        "url": "https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260730",
    },
    {
        "source": "BMS (EPIQ 3D)",
        "parser": "bms",
        "url": "https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day-epiq-3d/buytickets/ET00505581/20260801",
    },
    {
        "source": "District",
        "parser": "district",
        "url": (
            "https://www.district.in/movies/spider-man-brand-new-day-movie-tickets-in-"
            "chennai-MV194537?frmtid=rrfdpndypd&fromdate=2026-08-01"
        ),
    },
]

MOVIE_NAME = "Spider-Man: Brand New Day"


def print_result(source_label: str, snapshot) -> None:
    print(f"\n{'─'*60}")
    print(f"  [OK] {source_label}")
    print(f"  Theatres found : {len(snapshot.theatres)}")
    if not snapshot.theatres:
        print("  [!] No theatres – parser may need tuning for this page")
        return
    for t in snapshot.theatres:
        status = "[OPEN]" if t.booking_open else "[NOT OPEN]"
        print(f"\n    Theatre : {t.theatre}")
        print(f"    Status  : {status}")
        print(f"    Shows   : {', '.join(t.shows) if t.shows else '(none yet)'}")
        print(f"    Formats : {', '.join(t.formats) if t.formats else '(none)'}")
        if t.booking_url:
            print(f"    Link    : {t.booking_url[:70]}")


async def run():
    from app.browser import browser_pool
    from app.parsers.bms import BookMyShowParser
    from app.parsers.district import DistrictParser

    bms  = BookMyShowParser()
    dist = DistrictParser()

    print("ShowPulser - Live Fetch Test")
    print("=" * 60)
    print(f"Movie : {MOVIE_NAME}")
    print(f"Tests : {len(TESTS)} URLs")

    await browser_pool.start()

    try:
        for test in TESTS:
            print(f"\n[FETCH] {test['source']}")
            print(f"  URL: {test['url'][:75]}...")
            try:
                parser   = bms if test["parser"] == "bms" else dist
                snapshot = await parser.fetch(test["url"], MOVIE_NAME)
                print_result(test["source"], snapshot)
            except Exception as e:
                print(f"\n  [FAIL] {e}")
    finally:
        await browser_pool.stop()

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(run())
