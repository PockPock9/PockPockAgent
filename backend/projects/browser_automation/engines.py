"""Browser engine lifecycle adapters for isolated run contexts."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from typing import Literal, Protocol
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from playwright.async_api import Browser, Playwright, async_playwright


class BrowserEngine(Protocol):
    name: str
    max_contexts: int | None
    screenshot_format: Literal["jpeg", "png"]

    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def launch_browser(self, *, visible: bool = False) -> Browser: ...

    async def close_browser(self, browser: Browser) -> None: ...

    async def stop(self) -> None: ...


class PlaywrightChromiumEngine:
    name = "playwright-chromium"
    max_contexts = None
    screenshot_format: Literal["jpeg", "png"] = "jpeg"

    def __init__(self) -> None:
        self._playwright: Playwright | None = None

    @property
    def ready(self) -> bool:
        return self._playwright is not None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()

    async def launch_browser(self, *, visible: bool = False) -> Browser:
        if self._playwright is None:
            raise RuntimeError("Playwright browser engine is not ready")
        return await self._playwright.chromium.launch(
            headless=not visible,
            args=["--disable-extensions", "--disable-sync", "--no-first-run"],
        )

    async def close_browser(self, browser: Browser) -> None:
        await browser.close()

    async def stop(self) -> None:
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


def validate_lightpanda_cdp_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        parsed.port
    except ValueError as err:
        raise ValueError("Lightpanda CDP URL is invalid") from err
    if (
        parsed.scheme != "http"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Lightpanda CDP URL must be an HTTP loopback origin")
    normalized_host = host.lower().rstrip(".")
    if normalized_host != "localhost":
        try:
            address = ipaddress.ip_address(normalized_host)
        except ValueError as err:
            raise ValueError("Lightpanda CDP URL must use localhost or a loopback IP") from err
        if not address.is_loopback:
            raise ValueError("Lightpanda CDP URL must use localhost or a loopback IP")
    return value.strip().rstrip("/")


class _RejectCDPRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def _verify_lightpanda_endpoint(cdp_url: str) -> None:
    try:
        opener = build_opener(ProxyHandler({}), _RejectCDPRedirects())
        with opener.open(f"{cdp_url}/json/version", timeout=5) as response:
            data = response.read(16_385)
        if len(data) > 16_384:
            raise RuntimeError("The Lightpanda CDP metadata response is too large")
        metadata = json.loads(data)
    except (OSError, ValueError) as err:
        raise RuntimeError("Could not verify the local Lightpanda CDP endpoint") from err
    if not isinstance(metadata, dict) or not str(metadata.get("Browser", "")).startswith("Lightpanda/"):
        raise RuntimeError("The configured CDP endpoint did not identify itself as Lightpanda")
    if not metadata.get("Lightpanda-Version"):
        raise RuntimeError("The configured CDP endpoint did not report a Lightpanda version")


class LightpandaCDPEngine:
    name = "lightpanda"
    max_contexts = 1
    screenshot_format: Literal["jpeg", "png"] = "png"

    def __init__(self, cdp_url: str | None = None) -> None:
        configured_url = cdp_url or os.environ.get(
            "POCKPOCK_LIGHTPANDA_CDP_URL",
            "http://127.0.0.1:9222",
        )
        self._cdp_url = validate_lightpanda_cdp_url(configured_url)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    @property
    def ready(self) -> bool:
        return self._browser is not None

    async def start(self) -> None:
        await asyncio.to_thread(_verify_lightpanda_endpoint, self._cdp_url)
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.connect_over_cdp(self._cdp_url, timeout=5_000)
        except BaseException:
            await playwright.stop()
            raise
        self._playwright = playwright
        self._browser = browser

    async def launch_browser(self, *, visible: bool = False) -> Browser:
        if visible:
            raise RuntimeError("The Lightpanda engine cannot open a visible desktop browser window")
        if self._browser is None:
            raise RuntimeError("Lightpanda browser engine is not ready")
        return self._browser

    async def close_browser(self, browser: Browser) -> None:
        if browser is not self._browser:
            raise RuntimeError("Cannot close a browser not owned by the Lightpanda engine")
        # Run contexts close individually; this connection is shared with the CDP server.

    async def stop(self) -> None:
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            finally:
                self._playwright = None
                self._browser = None


def create_browser_engine(name: str) -> BrowserEngine:
    normalized = name.strip().lower()
    if normalized == "playwright":
        return PlaywrightChromiumEngine()
    if normalized == "lightpanda":
        return LightpandaCDPEngine()
    raise ValueError(f"Unsupported browser engine '{name}'")
