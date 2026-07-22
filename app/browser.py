import asyncio
import gc
import os
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

# A pool of realistic user-agent strings to rotate
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1280, "height": 720},
    {"width": 1366, "height": 768},
]

# Ultra-low memory launch arguments tuned for 512MB RAM containers (Render / Docker)
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--no-zygote",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-translate",
    "--mute-audio",
    "--hide-scrollbars",
    # Hard limit V8 Engine JS memory to 128 MB max to prevent memory growth
    '--js-flags="--max-old-space-size=128"',
    "--disk-cache-size=1",
    "--media-cache-size=1",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-client-side-phishing-detection",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-ipc-flooding-protection",
    "--disable-hang-monitor",
    "--disable-breakpad",
    "--metrics-recording-only",
    "--password-store=basic",
    "--use-mock-keychain",
]

_SYSTEM_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]

# Recycle browser instance every 15 pages to purge Chromium RAM completely
_MAX_PAGES_BEFORE_RECYCLE = 15


class BrowserPool:
    """Memory-capped Playwright browser pool with auto-recycling for Render 512MB limit."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._executable_path: str | None = None
        self._page_count: int = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return

            logger.info("[BrowserPool] Starting low-memory Chromium browser instance...")
            if not self._playwright:
                self._playwright = await async_playwright().start()

            # Detect executable path if not found yet
            if not self._executable_path:
                try:
                    self._browser = await self._playwright.chromium.launch(
                        headless=True,
                        args=_STEALTH_ARGS,
                    )
                    logger.info("[BrowserPool] Browser ready (Playwright Chromium).")
                    return
                except Exception as e:
                    logger.warning(f"[BrowserPool] Playwright Chromium fallback: {e}")

                for path in _SYSTEM_CHROME_PATHS:
                    if os.path.exists(path):
                        self._executable_path = path
                        break

            launch_kwargs: dict = {"headless": True, "args": _STEALTH_ARGS}
            if self._executable_path:
                launch_kwargs["executable_path"] = self._executable_path

            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._page_count = 0
            logger.info("[BrowserPool] Browser ready.")

    async def recycle_if_needed(self) -> None:
        """Periodically restart Chromium to release accumulated RAM back to system OS."""
        async with self._lock:
            self._page_count += 1
            if self._page_count >= _MAX_PAGES_BEFORE_RECYCLE:
                logger.info(f"[BrowserPool] Auto-recycling Chromium after {self._page_count} pages to free RAM...")
                await self._stop_internal()
                await self._start_internal()

    async def _start_internal(self) -> None:
        if not self._playwright:
            self._playwright = await async_playwright().start()

        launch_kwargs: dict = {"headless": True, "args": _STEALTH_ARGS}
        if self._executable_path:
            launch_kwargs["executable_path"] = self._executable_path

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._page_count = 0

    async def _stop_internal(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        gc.collect()

    async def stop(self) -> None:
        async with self._lock:
            logger.info("[BrowserPool] Stopping browser pool...")
            await self._stop_internal()
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            gc.collect()
            logger.info("[BrowserPool] Browser pool stopped.")

    @asynccontextmanager
    async def new_context(self) -> AsyncGenerator[BrowserContext, None]:
        """Create a new stealth browser context with randomised fingerprint."""
        if not self._browser or not self._browser.is_connected():
            await self.start()

        await self.recycle_if_needed()

        ua = random.choice(_USER_AGENTS)
        viewport = random.choice(_VIEWPORTS)

        context = await self._browser.new_context(
            user_agent=ua,
            viewport=viewport,
            java_script_enabled=True,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Connection": "keep-alive",
            },
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] });
            window.chrome = { runtime: {} };
        """)

        try:
            yield context
        finally:
            try:
                await context.clear_cookies()
                await context.close()
            except Exception:
                pass
            gc.collect()

    @asynccontextmanager
    async def new_page(self) -> AsyncGenerator[Page, None]:
        """Convenience wrapper: create a context + page and close both after use."""
        async with self.new_context() as context:
            page = await context.new_page()

            # Save memory and CPU by blocking images, media, fonts, and tracking scripts
            await page.route("**/*", lambda route:
                route.abort() if route.request.resource_type in ("image", "media", "font") or
                any(track in route.request.url.lower() for track in (
                    "analytics", "facebook", "doubleclick", "google-analytics", "tagmanager",
                    "adservice", "stats", "hotjar", "mixpanel", "sentry", "amplitude"
                ))
                else route.continue_()
            )

            try:
                yield page
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                gc.collect()


# Global singleton – imported by parsers
browser_pool = BrowserPool()
