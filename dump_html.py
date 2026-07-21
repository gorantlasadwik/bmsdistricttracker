"""
HTML dump script – saves the fully rendered HTML of each URL to disk.
This lets us inspect what the browser actually sees and fix selectors.

Run: python dump_html.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

TESTS = [
    {
        "name": "bms_english_3d",
        "url": "https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260730",
    },
    {
        "name": "district",
        "url": (
            "https://www.district.in/movies/spider-man-brand-new-day-movie-tickets-in-"
            "chennai-MV194537?frmtid=rrfdpndypd&fromdate=2026-08-01"
        ),
    },
]

OUT_DIR = Path("debug_html")
OUT_DIR.mkdir(exist_ok=True)


async def run():
    from app.browser import browser_pool

    await browser_pool.start()

    try:
        async with browser_pool.new_page() as page:
            for test in TESTS:
                print(f"\nFetching: {test['name']}")
                print(f"  URL: {test['url'][:70]}...")

                try:
                    await page.goto(test["url"], wait_until="domcontentloaded", timeout=30_000)

                    # Wait longer for JS to render
                    import asyncio as _a
                    await _a.sleep(5)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15_000)
                    except Exception:
                        pass
                    await _a.sleep(2)

                    # Scroll to trigger lazy loading
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await _a.sleep(2)
                    await page.evaluate("window.scrollTo(0, 0)")
                    await _a.sleep(1)

                    html = await page.content()
                    out_path = OUT_DIR / f"{test['name']}.html"
                    out_path.write_text(html, encoding="utf-8")

                    # Quick scan of what's in the HTML
                    keywords = [
                        "sc-1qdowf4-1",  # BMS venue class
                        "sc-1vhizuf-1",  # BMS showtime button
                        "MovieSessionsListing",  # District venue class
                        "timeblock",  # District time container
                        "Rakki",  # Known theatre name from screenshot
                        "MovieMax",  # Known theatre name from screenshot
                        "AM", "PM",
                        "IMAX", "DOLBY", "3D",
                        "Book Tickets", "book tickets",
                        "Coming Soon",
                        "No shows",
                        "location", "chennai",
                    ]

                    print(f"  Saved {len(html)} bytes to {out_path}")
                    print(f"  Keyword scan:")
                    for kw in keywords:
                        count = html.count(kw)
                        if count > 0:
                            print(f"    [{count:3d}x] {kw!r}")

                except Exception as e:
                    print(f"  FAILED: {e}")

    finally:
        await browser_pool.stop()

    print(f"\nHTML files saved to: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(run())
