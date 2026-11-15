import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException

from projects.browser_automation.app import BrowserRuntime, read_evidence
from projects.browser_automation.engines import (
    LightpandaCDPEngine,
    PlaywrightChromiumEngine,
    create_browser_engine,
    validate_lightpanda_cdp_url,
)


class BrowserEngineTests(unittest.IsolatedAsyncioTestCase):
    def test_playwright_is_the_default_engine(self):
        with patch.dict(os.environ, {}, clear=True):
            runtime = BrowserRuntime()

        self.assertEqual(runtime.status()["engine"], "playwright")
        self.assertFalse(runtime.status()["ok"])
        self.assertIsInstance(create_browser_engine("playwright"), PlaywrightChromiumEngine)
        self.assertIsInstance(create_browser_engine("lightpanda"), LightpandaCDPEngine)

    def test_lightpanda_endpoint_is_loopback_only(self):
        self.assertEqual(validate_lightpanda_cdp_url("http://127.0.0.1:9222"), "http://127.0.0.1:9222")
        self.assertEqual(validate_lightpanda_cdp_url("http://[::1]:9222/"), "http://[::1]:9222")
        for endpoint in (
            "http://example.com:9222",
            "http://192.168.1.2:9222",
            "https://127.0.0.1:9222",
            "http://user:pass@127.0.0.1:9222",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_lightpanda_cdp_url(endpoint)

    def test_unknown_engine_is_rejected_without_fallback(self):
        with self.assertRaisesRegex(ValueError, "Unsupported browser engine 'unknown'"):
            create_browser_engine("unknown")

    async def test_lightpanda_engine_connects_and_disconnects_without_closing_server(self):
        browser = SimpleNamespace()
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser)),
            stop=AsyncMock(),
        )
        manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
        engine = LightpandaCDPEngine("http://127.0.0.1:9222")

        with (
            patch("projects.browser_automation.engines._verify_lightpanda_endpoint"),
            patch("projects.browser_automation.engines.async_playwright", return_value=manager),
        ):
            await engine.start()
            self.assertTrue(engine.ready)
            self.assertIs(await engine.launch_browser(), browser)
            await engine.close_browser(browser)
            await engine.stop()

        playwright.chromium.connect_over_cdp.assert_awaited_once_with(
            "http://127.0.0.1:9222",
            timeout=5_000,
        )
        playwright.stop.assert_awaited_once()
        self.assertFalse(engine.ready)

    async def test_lightpanda_engine_fails_closed_when_endpoint_is_unavailable(self):
        manager = SimpleNamespace(start=AsyncMock())
        engine = LightpandaCDPEngine("http://127.0.0.1:9222")

        with (
            patch(
                "projects.browser_automation.engines._verify_lightpanda_endpoint",
                side_effect=RuntimeError("Could not verify the local Lightpanda CDP endpoint"),
            ),
            patch("projects.browser_automation.engines.async_playwright", return_value=manager),
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not verify"):
                await engine.start()

        manager.start.assert_not_awaited()
        self.assertFalse(engine.ready)

    async def test_lightpanda_runtime_rejects_a_second_active_context(self):
        browser = SimpleNamespace(
            new_context=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())),
        )
        engine = SimpleNamespace(
            name="lightpanda",
            max_contexts=1,
            screenshot_format="png",
            ready=True,
            start=AsyncMock(),
            launch_browser=AsyncMock(return_value=browser),
            close_browser=AsyncMock(),
            stop=AsyncMock(),
        )
        runtime = BrowserRuntime(engine_name="lightpanda")

        with patch("projects.browser_automation.app.create_browser_engine", return_value=engine):
            await runtime.start()
            await runtime.create_run(uuid4().hex)
            with self.assertRaises(HTTPException) as raised:
                await runtime.create_run(uuid4().hex)
            self.assertEqual(raised.exception.status_code, 503)
            self.assertIn("at most 1 active browser context", raised.exception.detail)
            await runtime.close()

        self.assertEqual(runtime.status()["active_contexts"], 0)

    async def test_lightpanda_rejects_visible_desktop_contexts(self):
        engine = SimpleNamespace(
            name="lightpanda",
            max_contexts=1,
            screenshot_format="png",
            ready=True,
            launch_browser=AsyncMock(),
        )
        runtime = BrowserRuntime(engine_name="lightpanda")
        runtime._engine = engine

        with self.assertRaises(HTTPException) as raised:
            await runtime.create_run(uuid4().hex, visible=True)

        self.assertIn("visible desktop browser requires", raised.exception.detail.lower())
        engine.launch_browser.assert_not_awaited()

    async def test_lightpanda_screenshots_use_png(self):
        page = SimpleNamespace(screenshot=AsyncMock(return_value=b"png"))
        runtime = BrowserRuntime(engine_name="lightpanda")
        runtime._engine = SimpleNamespace(screenshot_format="png")

        self.assertEqual(await runtime.capture_screenshot(page), b"png")
        page.screenshot.assert_awaited_once_with(type="png", full_page=False, timeout=10_000)

    async def test_evidence_content_type_matches_engine_screenshot_format(self):
        run_id = uuid4().hex
        evidence_id = uuid4().hex
        for screenshot_format, content_type in (("png", "image/png"), ("jpeg", "image/jpeg")):
            fake_runtime = SimpleNamespace(
                _runs={run_id: SimpleNamespace(evidence={evidence_id: b"image"})},
                _engine=SimpleNamespace(screenshot_format=screenshot_format),
            )
            with patch("projects.browser_automation.app.runtime", fake_runtime):
                response = await read_evidence(run_id, evidence_id)
            self.assertEqual(response.media_type, content_type)

    async def test_runtime_keeps_run_context_lifecycle_behind_engine(self):
        context = SimpleNamespace(close=AsyncMock())
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context))
        engine = SimpleNamespace(
            name="test-engine",
            max_contexts=None,
            screenshot_format="jpeg",
            ready=True,
            start=AsyncMock(),
            launch_browser=AsyncMock(return_value=browser),
            close_browser=AsyncMock(),
            stop=AsyncMock(),
        )
        runtime = BrowserRuntime(engine_name="playwright")

        with patch("projects.browser_automation.app.create_browser_engine", return_value=engine):
            await runtime.start()
            run_id = uuid4().hex
            result = await runtime.create_run(run_id)
            self.assertTrue(result["created"])
            self.assertEqual(runtime.status()["active_contexts"], 1)
            self.assertTrue(await runtime.close_run(run_id))
            await runtime.close()

        browser.new_context.assert_awaited_once_with(
            accept_downloads=False,
            service_workers="block",
            permissions=[],
        )
        context.close.assert_awaited_once()
        engine.close_browser.assert_awaited_once_with(browser)
        engine.stop.assert_awaited_once()

    async def test_runtime_passes_visible_mode_to_the_engine(self):
        context = SimpleNamespace(close=AsyncMock())
        browser = SimpleNamespace(
            new_context=AsyncMock(return_value=context),
            on=Mock(),
        )
        engine = SimpleNamespace(
            name="playwright-chromium",
            max_contexts=None,
            screenshot_format="jpeg",
            ready=True,
            start=AsyncMock(),
            launch_browser=AsyncMock(return_value=browser),
            close_browser=AsyncMock(),
            stop=AsyncMock(),
        )
        runtime = BrowserRuntime(engine_name="playwright")

        with patch("projects.browser_automation.app.create_browser_engine", return_value=engine):
            await runtime.start()
            run_id = uuid4().hex
            await runtime.create_run(run_id, visible=True)
            self.assertTrue(runtime._runs[run_id].visible)
            with self.assertRaises(HTTPException) as raised:
                await runtime.create_run(uuid4().hex, visible=True)
            self.assertIn("visible browser window is already open", raised.exception.detail.lower())
            with self.assertRaises(HTTPException) as raised:
                await runtime.create_run(run_id, visible=False)
            self.assertEqual(raised.exception.status_code, 409)
            browser.on.call_args.args[1](browser)
            await asyncio.sleep(0)
            self.assertEqual(runtime.status()["active_contexts"], 0)
            await runtime.close()

        engine.launch_browser.assert_awaited_once_with(visible=True)
        browser.on.assert_called_once()

    async def test_playwright_engine_launch_and_shutdown(self):
        browser = SimpleNamespace(close=AsyncMock())
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)),
            stop=AsyncMock(),
        )
        manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
        engine = PlaywrightChromiumEngine()

        with patch("projects.browser_automation.engines.async_playwright", return_value=manager):
            await engine.start()
            self.assertTrue(engine.ready)
            self.assertIs(await engine.launch_browser(), browser)
            await engine.close_browser(browser)
            await engine.stop()

        playwright.chromium.launch.assert_awaited_once_with(
            headless=True,
            args=["--disable-extensions", "--disable-sync", "--no-first-run"],
        )
        browser.close.assert_awaited_once()
        playwright.stop.assert_awaited_once()
        self.assertFalse(engine.ready)

    async def test_playwright_engine_can_launch_a_visible_window(self):
        browser = SimpleNamespace(close=AsyncMock())
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)),
            stop=AsyncMock(),
        )
        manager = SimpleNamespace(start=AsyncMock(return_value=playwright))
        engine = PlaywrightChromiumEngine()

        with patch("projects.browser_automation.engines.async_playwright", return_value=manager):
            await engine.start()
            await engine.launch_browser(visible=True)
            await engine.stop()

        playwright.chromium.launch.assert_awaited_once_with(
            headless=False,
            args=["--disable-extensions", "--disable-sync", "--no-first-run"],
        )


if __name__ == "__main__":
    unittest.main()
