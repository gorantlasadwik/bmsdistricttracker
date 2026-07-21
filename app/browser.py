"""
ShowPulser Browser Pool
Singleton Playwright browser instance shared across all parsers.
Handles stealth configuration, context creation, and graceful cleanup.
"""
from __future__ import annotations

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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]

# Stealth launch arguments that mask automation signals
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
]


class BrowserPool:
    """Singleton Playwright browser manager."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        logger.info("Starting Playwright browser pool...")
        self._playwright = await async_playwright().start()

        # Try Playwright's own Chromium first; fall back to system Chrome
        import os
        _SYSTEM_CHROME_PATHS = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]

        executable_path = None
        try:
            # Test if Playwright's bundled Chromium exists
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=_STEALTH_ARGS,
            )
            logger.info("Browser pool ready (Playwright Chromium).")
            return
        except Exception as e:
            logger.warning(f"Playwright Chromium not found ({e}). Trying system Chrome...")

        # Fallback: find system Chrome
        for path in _SYSTEM_CHROME_PATHS:
            if os.path.exists(path):
                executable_path = path
                break

        if not executable_path:
            raise RuntimeError(
                "No browser found. Run `playwright install chromium` or install Google Chrome."
            )

        self._browser = await self._playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=_STEALTH_ARGS,
        )
        logger.info(f"Browser pool ready (system Chrome: {executable_path}).")


    async def stop(self) -> None:
        logger.info("Shutting down browser pool...")
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser pool stopped.")

    @asynccontextmanager
    async def new_context(self) -> AsyncGenerator[BrowserContext, None]:
        """Create a new stealth browser context with randomised fingerprint."""
        if not self._browser:
            raise RuntimeError("BrowserPool not started. Call start() first.")

        ua = random.choice(_USER_AGENTS)
        viewport = random.choice(_VIEWPORTS)

        context = await self._browser.new_context(
            user_agent=ua,
            viewport=viewport,
            java_script_enabled=True,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )

        # Patch navigator.webdriver to undefined
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-IN', 'en', 'hi'],
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            window.chrome = { runtime: {} };
        """)

        try:
            yield context
        finally:
            await context.close()

    @asynccontextmanager
    async def new_page(self) -> AsyncGenerator[Page, None]:
        """Convenience wrapper: create a context + page and close both after use."""
        async with self.new_context() as context:
            page = await context.new_page()
            try:
                yield page
            finally:
                await page.close()


# Global singleton – imported by parsers
browser_pool = BrowserPool()
