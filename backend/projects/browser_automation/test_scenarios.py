import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from projects.browser_automation.app import (
    MAX_NAVIGATIONS_PER_RUN,
    MAX_NETWORK_REQUESTS_PER_RUN,
    BrowserActionRequest,
    BrowserRuntime,
    checkpoint_matches,
    resolve_public_host as resolve_public_host_impl,
    validate_public_url,
)


class _ScenarioLocator:
    def __init__(self, count=1, attributes=None):
        self._count = count
        self.attributes = attributes or {}
        self.fill_calls = []
        self.select_calls = []
        self.click_calls = []

    async def count(self):
        return self._count

    async def get_attribute(self, name):
        return self.attributes.get(name)

    async def fill(self, value, timeout):
        self.fill_calls.append((value, timeout))

    async def select_option(self, label, timeout):
        self.select_calls.append((label, timeout))

    async def click(self, timeout):
        self.click_calls.append(timeout)


class _ScenarioFrame:
    def __init__(self):
        self.locators = {}

    def get_by_role(self, role, name, exact):
        return self.locators.get((role, name), _ScenarioLocator(count=0))


class _ScenarioBody:
    def __init__(self, page):
        self.page = page

    async def inner_text(self, timeout):
        return self.page.body_text


class _ScenarioPage:
    def __init__(self):
        self.url = "about:blank"
        self.title_text = "Scenario Fixture"
        self.body_text = "Fixture content"
        self.redirect_url = None
        self.goto_response = SimpleNamespace(status=200)
        self.frames = [_ScenarioFrame()]
        self.mouse = SimpleNamespace(wheel=AsyncMock())
        self.screenshot = AsyncMock(return_value=b"\xff\xd8fixture")
        self.goto = AsyncMock(side_effect=self._goto)

    async def _goto(self, url, wait_until, timeout):
        self.url = self.redirect_url or url
        return self.goto_response

    async def title(self):
        return self.title_text

    def locator(self, selector):
        if selector != "body":
            raise AssertionError(f"Unexpected selector: {selector}")
        return _ScenarioBody(self)


class _ScenarioContext:
    def __init__(self, page):
        self.page = page
        self.new_page = AsyncMock(return_value=page)
        self.close = AsyncMock()
        self.route_pattern = None
        self.route_handler = None

    async def route(self, pattern, handler):
        self.route_pattern = pattern
        self.route_handler = handler


class BrowserAutomationScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.page = _ScenarioPage()
        self.context = _ScenarioContext(self.page)
        self.browser = SimpleNamespace(
            new_context=AsyncMock(return_value=self.context),
            close=AsyncMock(),
        )
        self.engine = SimpleNamespace(
            name="scenario-engine",
            max_contexts=None,
            screenshot_format="jpeg",
            ready=True,
            start=AsyncMock(),
            launch_browser=AsyncMock(return_value=self.browser),
            close_browser=AsyncMock(),
            stop=AsyncMock(),
        )
        self.runtime = BrowserRuntime(engine_name="scenario-engine")
        self.engine_factory_patch = patch(
            "projects.browser_automation.app.create_browser_engine",
            return_value=self.engine,
        )
        self.host_resolution_patch = patch(
            "projects.browser_automation.app.resolve_public_host",
            new=AsyncMock(return_value=None),
        )
        self.engine_factory_patch.start()
        self.host_resolution_patch.start()
        await self.runtime.start()
        self.run_id = uuid4().hex

    async def asyncTearDown(self):
        await self.runtime.close()
        self.host_resolution_patch.stop()
        self.engine_factory_patch.stop()

    async def open_run(self):
        await self.runtime.create_run(self.run_id)

    async def observe(self):
        await self.open_run()
        return await self.runtime.navigate(self.run_id, "https://example.com")

    async def invoke_route(self, method, url):
        route = SimpleNamespace(
            request=SimpleNamespace(method=method, url=url),
            abort=AsyncMock(),
            continue_=AsyncMock(),
        )
        await self.context.route_handler(route)
        return route

    def test_scenario_01_public_http_and_https_urls_are_normalized(self):
        self.assertEqual(validate_public_url("HTTPS://Example.COM/path"), "example.com")
        self.assertEqual(validate_public_url("http://Example.COM"), "example.com")

    def test_scenario_02_unsupported_url_schemes_are_rejected(self):
        for url in ("file:///tmp/test", "ftp://example.com/file", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(HTTPException) as raised:
                validate_public_url(url)
            self.assertEqual(raised.exception.status_code, 422)

    def test_scenario_03_credentials_in_urls_are_rejected(self):
        with self.assertRaisesRegex(HTTPException, "credentials are not allowed"):
            validate_public_url("https://user:secret@example.com/")

    def test_scenario_04_nonstandard_ports_are_rejected(self):
        for url in ("http://example.com:8080/", "https://example.com:8443/"):
            with self.subTest(url=url), self.assertRaises(HTTPException) as raised:
                validate_public_url(url)
            self.assertEqual(raised.exception.status_code, 422)

    async def test_scenario_05_private_ip_destinations_are_blocked(self):
        for host in ("127.0.0.1", "10.0.0.1", "::1"):
            with self.subTest(host=host), self.assertRaises(HTTPException) as raised:
                await resolve_public_host_impl(host)
            self.assertEqual(raised.exception.status_code, 403)

    async def test_scenario_06_dns_resolution_errors_fail_closed(self):
        with (
            patch(
                "projects.browser_automation.app.asyncio.to_thread",
                new=AsyncMock(side_effect=OSError("DNS unavailable")),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await resolve_public_host_impl("unresolvable.invalid")
        self.assertEqual(raised.exception.status_code, 422)

    async def test_scenario_07_malformed_run_ids_are_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            await self.runtime.create_run("not-a-run-id")
        self.assertEqual(raised.exception.status_code, 422)
        self.browser.new_context.assert_not_awaited()

    async def test_scenario_08_context_creation_requires_a_ready_runtime(self):
        runtime = BrowserRuntime(engine_name="playwright")
        with self.assertRaises(HTTPException) as raised:
            await runtime.create_run(uuid4().hex)
        self.assertEqual(raised.exception.status_code, 503)

    async def test_scenario_09_fresh_context_disables_downloads_workers_and_permissions(self):
        await self.open_run()
        self.browser.new_context.assert_awaited_once_with(
            accept_downloads=False,
            service_workers="block",
            permissions=[],
        )

    async def test_scenario_10_duplicate_context_requests_are_idempotent(self):
        created = await self.runtime.create_run(self.run_id)
        duplicate = await self.runtime.create_run(self.run_id)
        self.assertTrue(created["created"])
        self.assertFalse(duplicate["created"])
        self.browser.new_context.assert_awaited_once()

    async def test_scenario_11_lightpanda_context_capacity_is_enforced(self):
        self.engine.max_contexts = 1
        await self.open_run()
        with self.assertRaises(HTTPException) as raised:
            await self.runtime.create_run(uuid4().hex)
        self.assertEqual(raised.exception.status_code, 503)

    async def test_scenario_12_closing_a_run_removes_context_and_evidence(self):
        await self.open_run()
        run = self.runtime._runs[self.run_id]
        run.evidence = {"evidence-id": b"fixture"}
        evidence = run.evidence
        self.assertTrue(await self.runtime.close_run(self.run_id))
        self.assertEqual(evidence, {})
        self.context.close.assert_awaited_once()
        self.engine.close_browser.assert_awaited_once_with(self.browser)
        self.assertEqual(self.runtime.status()["active_contexts"], 0)

    async def test_scenario_13_public_navigation_returns_bounded_observation_and_checkpoint(self):
        await self.open_run()
        self.page.body_text = "x" * 70_000
        observation = await self.runtime.navigate(self.run_id, "https://example.com")
        self.assertEqual(observation["title"], "Scenario Fixture")
        self.assertEqual(observation["final_url"], "https://example.com")
        self.assertEqual(len(observation["visible_text"]), 64_000)
        self.assertEqual(observation["screenshot_bytes"], len(b"\xff\xd8fixture"))
        self.assertRegex(observation["screenshot_ref"], rf"^/evidence/{self.run_id}/[a-f0-9]{{32}}$")
        self.assertTrue(checkpoint_matches({"title_contains": "scenario", "text_contains": "xxx"}, observation))
        self.assertFalse(checkpoint_matches({"title_contains": "unexpected"}, observation))

    async def test_scenario_14_http_errors_and_oversized_screenshots_are_rejected(self):
        await self.open_run()
        self.page.goto_response = SimpleNamespace(status=503)
        with self.assertRaises(HTTPException) as raised:
            await self.runtime.navigate(self.run_id, "https://example.com")
        self.assertEqual(raised.exception.status_code, 502)

        self.page.goto_response = SimpleNamespace(status=200)
        self.page.screenshot = AsyncMock(return_value=b"x" * 2_000_001)
        with self.assertRaisesRegex(HTTPException, "screenshot exceeded"):
            await self.runtime.navigate(self.run_id, "https://example.com")

    async def test_scenario_15_cross_host_redirects_are_rejected(self):
        await self.open_run()
        self.page.redirect_url = "https://outside.example/"
        with self.assertRaises(HTTPException) as raised:
            await self.runtime.navigate(self.run_id, "https://example.com")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("Cross-host redirects", raised.exception.detail)

    async def test_scenario_16_navigation_budget_is_enforced(self):
        await self.open_run()
        self.runtime._runs[self.run_id].navigation_count = MAX_NAVIGATIONS_PER_RUN
        with self.assertRaises(HTTPException) as raised:
            await self.runtime.navigate(self.run_id, "https://example.com")
        self.assertEqual(raised.exception.status_code, 429)
        self.page.goto.assert_not_awaited()

    async def test_scenario_17_same_host_get_requests_are_allowed(self):
        await self.observe()
        self.assertEqual(self.context.route_pattern, "**/*")
        route = await self.invoke_route("GET", "https://example.com/image.png")
        route.continue_.assert_awaited_once()
        route.abort.assert_not_awaited()

    async def test_scenario_18_post_and_cross_host_requests_are_blocked(self):
        await self.observe()
        post_route = await self.invoke_route("POST", "https://example.com/form")
        post_route.abort.assert_awaited_once_with("blockedbyclient")
        self.assertIn("GET and HEAD", self.runtime._runs[self.run_id].blocked_reason)

        cross_host_route = await self.invoke_route("GET", "https://outside.example/resource")
        cross_host_route.abort.assert_awaited_once_with("blockedbyclient")
        self.assertIn("Cross-host", self.runtime._runs[self.run_id].blocked_reason)

    async def test_scenario_19_network_request_budget_is_enforced(self):
        await self.observe()
        self.runtime._runs[self.run_id].network_request_count = MAX_NETWORK_REQUESTS_PER_RUN
        route = await self.invoke_route("GET", "https://example.com/next")
        route.abort.assert_awaited_once_with("blockedbyclient")
        self.assertIn("network-request safety limit", self.runtime._runs[self.run_id].blocked_reason)

    async def test_scenario_20_typed_actions_are_accessible_and_state_bound(self):
        observation = await self.observe()
        frame = self.page.frames[0]
        search = _ScenarioLocator(attributes={"type": "search"})
        department = _ScenarioLocator()
        continue_link = _ScenarioLocator(attributes={"href": "/next"})
        password = _ScenarioLocator(attributes={"type": "password"})
        external_link = _ScenarioLocator(attributes={"href": "https://outside.example/"})
        frame.locators.update({
            ("searchbox", "Search"): search,
            ("combobox", "Department"): department,
            ("link", "Continue"): continue_link,
            ("textbox", "Password"): password,
            ("link", "External"): external_link,
        })

        with self.assertRaises(HTTPException) as stale:
            await self.runtime.act(BrowserActionRequest(
                run_id=self.run_id,
                observation_id="0" * 32,
                action="scroll",
                direction="down",
            ))
        self.assertEqual(stale.exception.status_code, 409)

        typed = await self.runtime.act(BrowserActionRequest(
            run_id=self.run_id,
            observation_id=observation["observation_id"],
            action="type",
            role="searchbox",
            name="Search",
            value="private test value",
        ))
        self.assertNotIn("private test value", repr(typed))
        self.assertEqual(search.fill_calls, [("private test value", 5_000)])

        selected = await self.runtime.act(BrowserActionRequest(
            run_id=self.run_id,
            observation_id=typed["observation_id"],
            action="select",
            role="combobox",
            name="Department",
            value="Research",
        ))
        self.assertEqual(department.select_calls, [("Research", 5_000)])

        clicked = await self.runtime.act(BrowserActionRequest(
            run_id=self.run_id,
            observation_id=selected["observation_id"],
            action="click",
            role="link",
            name="Continue",
        ))
        self.assertEqual(continue_link.click_calls, [5_000])

        scrolled = await self.runtime.act(BrowserActionRequest(
            run_id=self.run_id,
            observation_id=clicked["observation_id"],
            action="scroll",
            direction="down",
        ))
        self.page.mouse.wheel.assert_awaited_once_with(0, 500)

        with self.assertRaises(HTTPException) as protected:
            await self.runtime.act(BrowserActionRequest(
                run_id=self.run_id,
                observation_id=scrolled["observation_id"],
                action="type",
                role="textbox",
                name="Password",
                value="not-a-real-password",
            ))
        self.assertEqual(protected.exception.status_code, 403)

        observation = await self.runtime.navigate(self.run_id, "https://example.com")
        with self.assertRaises(HTTPException) as cross_host:
            await self.runtime.act(BrowserActionRequest(
                run_id=self.run_id,
                observation_id=observation["observation_id"],
                action="click",
                role="link",
                name="External",
            ))
        self.assertEqual(cross_host.exception.status_code, 403)
        external_link.click_calls.clear()
        self.assertFalse(external_link.click_calls)


if __name__ == "__main__":
    unittest.main()
