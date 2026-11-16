"""Unit tests for integration management. All live probes are stubbed; no network."""

from __future__ import annotations

import unittest

from projects.integrations.api import ConnectPayload, create_router
from projects.integrations.catalog import (
    CATALOG,
    CATEGORIES,
    GROUPS,
    KIND_EXTERNAL,
    KIND_INTERNAL,
)
from projects.integrations.service import (
    STATUS_CONNECTED,
    STATUS_DISABLED,
    STATUS_NEEDS_SETUP,
    STATUS_NOT_CONNECTED,
    GitHubTokenRejected,
    IntegrationError,
    IntegrationService,
    MemoryAccountStore,
    MemoryEnabledStore,
)


def make_service(**overrides):
    """A service whose probes are controllable stubs."""
    state = {
        "ollama_tags": {"models": [{"name": "llama3"}, {"name": "qwen2"}]},
        "openclaw": {"available": True, "ready": True, "detail": "Ready."},
        "nemoclaw": {"available": True, "ready": False, "detail": "Sandbox is stopped."},
        "extensions": {
            "skills": [{"slug": "a"}],
            "builtin_skills": [{"key": "b"}],
            "mcp": [{"name": "s1"}],
            "openclaw_ready": True,
            "detail": "",
        },
        "research": "disabled",
        "cloud": ["nim/meta/llama-3.3-70b-instruct"],
        "browser": {"ok": True, "service": "browser-automation"},
        "started": False,
    }

    async def ollama_tags():
        return state["ollama_tags"]

    async def openclaw_status():
        return state["openclaw"]

    async def nemoclaw_status():
        return state["nemoclaw"]

    def extensions_list():
        return state["extensions"]

    def research_provider():
        return state["research"]

    def set_research_provider(value):
        state["research"] = value

    def cloud_models():
        return list(state["cloud"])

    async def ollama_start():
        state["started"] = True
        return {"connected": True, "started": True, "models": 2}

    async def browser_health():
        return state["browser"]

    def github_probe(token):
        if token == "good-token":
            return "octo-user"
        if token == "bad-token":
            raise GitHubTokenRejected("That token was rejected by GitHub.")
        raise ConnectionError("network down")

    kwargs = {
        "ollama_tags": ollama_tags,
        "openclaw_status": openclaw_status,
        "nemoclaw_status": nemoclaw_status,
        "extensions_list": extensions_list,
        "research_provider": research_provider,
        "set_research_provider": set_research_provider,
        "cloud_models": cloud_models,
        "enabled_store": MemoryEnabledStore(),
        "account_store": MemoryAccountStore(),
        "github_probe": github_probe,
        "ollama_start": ollama_start,
        "browser_health": browser_health,
    }
    kwargs.update(overrides)
    service = IntegrationService(**kwargs)
    return service, state


class CatalogTests(unittest.TestCase):
    def test_catalog_has_twenty_three_entries_with_required_fields(self):
        self.assertEqual(len(CATALOG), 23)
        ids = [item.id for item in CATALOG]
        self.assertEqual(len(set(ids)), 23)
        self.assertEqual(
            ids,
            ["ollama", "openclaw", "nemoclaw", "cloud", "research", "browser", "skills", "mcp",
             "github", "gmail", "outlook_mail", "outlook_calendar", "google_calendar",
             "slack", "notion", "google_drive", "google_docs", "google_sheets",
             "instagram", "facebook", "threads", "spotify", "messenger"],
        )
        external = [item for item in CATALOG if item.kind == KIND_EXTERNAL]
        internal = [item for item in CATALOG if item.kind == KIND_INTERNAL]
        self.assertEqual(len(external), 15)
        self.assertEqual(len(internal), 8)
        for item in CATALOG:
            self.assertIn(item.category, CATEGORIES)
            self.assertTrue(item.name)
            self.assertTrue(item.description)
            self.assertTrue(item.capabilities)
            self.assertTrue(all(isinstance(cap, str) and cap for cap in item.capabilities))
            self.assertTrue(item.setup_hint)
            self.assertTrue(item.manage_hint)
            entry = item.to_dict()
            self.assertEqual(
                set(entry),
                {"id", "name", "category", "description", "capabilities", "setup_hint", "manage_hint",
                 "kind", "auth", "scopes", "connect_steps", "featured", "group", "icon"},
            )
            self.assertEqual(entry["icon"], item.id)
        for item in internal:
            self.assertEqual(item.kind, KIND_INTERNAL)
            self.assertEqual(item.auth, "local")
            self.assertEqual(item.scopes, ())
            self.assertEqual(item.connect_steps, ())
            self.assertFalse(item.featured)
            self.assertEqual(item.group, "")
        for item in external:
            self.assertEqual(item.kind, KIND_EXTERNAL)
            self.assertIn(item.auth, ("oauth", "api_token"))
            self.assertTrue(item.scopes)
            self.assertTrue(all(isinstance(scope, str) and scope for scope in item.scopes))
            self.assertTrue(item.connect_steps)
            self.assertTrue(all(isinstance(step, str) and step for step in item.connect_steps))
            self.assertIn(item.group, GROUPS)

    def test_featured_is_the_three_most_used(self):
        featured = {item.id for item in CATALOG if item.featured}
        self.assertEqual(featured, {"github", "gmail", "google_calendar"})

    def test_external_groups_cover_layout_groups(self):
        groups = {item.group for item in CATALOG if item.kind == KIND_EXTERNAL}
        self.assertEqual(groups, {"Productivity", "Developer", "Communication", "Social"})
        by_group = {
            "Developer": {"github"},
            "Communication": {"gmail", "outlook_mail", "slack", "messenger"},
            "Productivity": {
                "outlook_calendar", "google_calendar", "notion",
                "google_drive", "google_docs", "google_sheets",
            },
            "Social": {"instagram", "facebook", "threads", "spotify"},
        }
        for group, expected in by_group.items():
            actual = {item.id for item in CATALOG if item.group == group}
            self.assertEqual(actual, expected, group)

    def test_github_entry_declares_token_scopes_and_steps(self):
        github = next(item for item in CATALOG if item.id == "github")
        self.assertEqual(github.auth, "api_token")
        self.assertIn("Read repositories, issues, and pull requests", github.scopes)
        self.assertIn("Write issues and pull requests", github.scopes)
        self.assertTrue(any("fine-grained" in step for step in github.connect_steps))
        self.assertTrue(any("this PC only" in step for step in github.connect_steps))


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_maps_ollama_up_and_down(self):
        service, state = make_service()
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(len(entries), 23)
        self.assertEqual(entries["ollama"]["status"], STATUS_CONNECTED)
        self.assertEqual(entries["ollama"]["counts"], {"models": 2})
        self.assertTrue(entries["ollama"]["enabled"])

        state["ollama_tags"] = None
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["ollama"]["status"], STATUS_NOT_CONNECTED)
        self.assertEqual(entries["ollama"]["counts"], {})

    async def test_list_maps_research_disabled_and_enabled(self):
        service, state = make_service()
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["research"]["status"], STATUS_NOT_CONNECTED)
        state["research"] = "named_host_fetcher"
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["research"]["status"], STATUS_CONNECTED)

    async def test_list_maps_bridge_statuses(self):
        service, state = make_service()
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["openclaw"]["status"], STATUS_CONNECTED)
        self.assertEqual(entries["nemoclaw"]["status"], STATUS_NEEDS_SETUP)
        self.assertIn("Sandbox is stopped", entries["nemoclaw"]["detail"])
        state["openclaw"] = {"available": False, "ready": False, "detail": "OpenClaw integration is turned off."}
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["openclaw"]["status"], STATUS_NOT_CONNECTED)

    async def test_list_maps_extensions_ready_and_not(self):
        service, state = make_service()
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["skills"]["status"], STATUS_CONNECTED)
        self.assertEqual(entries["skills"]["counts"], {"skills": 2, "mcp_servers": 1})
        self.assertEqual(entries["mcp"]["status"], STATUS_CONNECTED)
        state["extensions"] = {**state["extensions"], "openclaw_ready": False, "detail": "OpenClaw is not ready."}
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["skills"]["status"], STATUS_NEEDS_SETUP)
        self.assertEqual(entries["mcp"]["status"], STATUS_NEEDS_SETUP)
        self.assertIn("not ready", entries["skills"]["detail"])

    async def test_list_maps_cloud_and_browser(self):
        service, state = make_service()
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["cloud"]["status"], STATUS_CONNECTED)
        self.assertEqual(entries["cloud"]["counts"], {"models": 1})
        self.assertEqual(entries["browser"]["status"], STATUS_CONNECTED)
        state["cloud"] = []
        state["browser"] = None
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(entries["cloud"]["status"], STATUS_NOT_CONNECTED)
        self.assertEqual(entries["browser"]["status"], STATUS_NEEDS_SETUP)

    async def test_browser_without_health_callable_needs_setup(self):
        service, _ = make_service(browser_health=None)
        entry = await service.get("browser")
        self.assertEqual(entry["status"], STATUS_NEEDS_SETUP)
        self.assertIn("not configured", entry["detail"])

    async def test_disabled_integration_reports_disabled_without_probing(self):
        service, state = make_service()
        await service.set_enabled("ollama", False)
        entry = await service.get("ollama")
        self.assertEqual(entry["status"], STATUS_DISABLED)
        self.assertFalse(entry["enabled"])
        state["ollama_tags"] = None  # probe result must not leak through
        entry = await service.get("ollama")
        self.assertEqual(entry["status"], STATUS_DISABLED)

    async def test_failing_probe_degrades_instead_of_raising(self):
        async def broken_tags():
            raise RuntimeError("boom")

        service, _ = make_service(ollama_tags=broken_tags)
        entries = await service.list_integrations()
        self.assertEqual(len(entries), 23)
        ollama = next(entry for entry in entries if entry["id"] == "ollama")
        self.assertEqual(ollama["status"], STATUS_NOT_CONNECTED)


class GetTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_unknown_raises_404(self):
        service, _ = make_service()
        with self.assertRaises(IntegrationError) as caught:
            await service.get("nope")
        self.assertEqual(caught.exception.status_code, 404)

    async def test_get_known_returns_entry(self):
        service, _ = make_service()
        entry = await service.get("cloud")
        self.assertEqual(entry["id"], "cloud")
        self.assertEqual(entry["status"], STATUS_CONNECTED)


class ToggleTests(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_allowed_id_persists(self):
        service, _ = make_service()
        entry = await service.set_enabled("cloud", False)
        self.assertEqual(entry["status"], STATUS_DISABLED)
        self.assertFalse(entry["enabled"])
        entry = await service.get("cloud")
        self.assertEqual(entry["status"], STATUS_DISABLED)
        entry = await service.set_enabled("cloud", True)
        self.assertEqual(entry["status"], STATUS_CONNECTED)

    async def test_toggle_each_toggleable_id(self):
        service, _ = make_service()
        for integration_id in ("ollama", "openclaw", "nemoclaw", "cloud", "research", "browser"):
            entry = await service.set_enabled(integration_id, False)
            self.assertFalse(entry["enabled"], integration_id)
            await service.set_enabled(integration_id, True)

    async def test_toggle_skills_and_mcp_is_conflict(self):
        service, _ = make_service()
        for integration_id in ("skills", "mcp"):
            with self.assertRaises(IntegrationError) as caught:
                await service.set_enabled(integration_id, False)
            self.assertEqual(caught.exception.status_code, 409, integration_id)
            self.assertIn("page", str(caught.exception))

    async def test_toggle_unknown_is_404(self):
        service, _ = make_service()
        with self.assertRaises(IntegrationError) as caught:
            await service.set_enabled("nope", True)
        self.assertEqual(caught.exception.status_code, 404)


class ConnectDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_research_sets_provider(self):
        service, state = make_service()
        entry = await service.connect("research")
        self.assertEqual(state["research"], "named_host_fetcher")
        self.assertEqual(entry["status"], STATUS_CONNECTED)
        self.assertIn("named-host fetcher", entry["note"])

    async def test_disconnect_research_disables_provider(self):
        service, state = make_service()
        state["research"] = "named_host_fetcher"
        entry = await service.disconnect("research")
        self.assertEqual(state["research"], "disabled")
        self.assertEqual(entry["status"], STATUS_NOT_CONNECTED)

    async def test_connect_ollama_calls_starter(self):
        service, state = make_service()
        entry = await service.connect("ollama")
        self.assertTrue(state["started"])
        self.assertTrue(entry["started"])
        self.assertEqual(entry["status"], STATUS_CONNECTED)
        self.assertIn("started", entry["note"])

    async def test_connect_cloud_reprobes(self):
        service, state = make_service()
        entry = await service.connect("cloud")
        self.assertEqual(entry["status"], STATUS_CONNECTED)
        self.assertIn("Cloud page", entry["note"])
        state["cloud"] = []
        entry = await service.connect("cloud")
        self.assertEqual(entry["status"], STATUS_NOT_CONNECTED)

    async def test_connect_managed_elsewhere_reprobes_only(self):
        service, _ = make_service()
        for integration_id in ("openclaw", "nemoclaw", "browser", "skills", "mcp"):
            entry = await service.connect(integration_id)
            self.assertIn("note", entry, integration_id)
            self.assertIn("page", entry["note"], integration_id)

    async def test_connect_disabled_is_conflict(self):
        service, _ = make_service()
        await service.set_enabled("research", False)
        with self.assertRaises(IntegrationError) as caught:
            await service.connect("research")
        self.assertEqual(caught.exception.status_code, 409)

    async def test_disconnect_cloud_disables(self):
        service, _ = make_service()
        entry = await service.disconnect("cloud")
        self.assertEqual(entry["status"], STATUS_DISABLED)
        self.assertFalse(entry["enabled"])

    async def test_disconnect_managed_elsewhere_is_conflict(self):
        service, _ = make_service()
        for integration_id in ("ollama", "openclaw", "nemoclaw", "browser", "skills", "mcp"):
            with self.assertRaises(IntegrationError) as caught:
                await service.disconnect(integration_id)
            self.assertEqual(caught.exception.status_code, 409, integration_id)

    async def test_connect_and_disconnect_unknown_is_404(self):
        service, _ = make_service()
        for method in (service.connect, service.disconnect):
            with self.assertRaises(IntegrationError) as caught:
                await method("nope")
            self.assertEqual(caught.exception.status_code, 404)


class ExternalConnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_entries_start_not_connected_without_account(self):
        service, _ = make_service()
        entries = {entry["id"]: entry for entry in await service.list_integrations()}
        self.assertEqual(len(entries), 23)
        for integration_id in ("github", "gmail", "spotify", "messenger", "google_docs"):
            entry = entries[integration_id]
            self.assertEqual(entry["status"], STATUS_NOT_CONNECTED, integration_id)
            self.assertIsNone(entry["account"])
            self.assertIsNone(entry["auth_method"])
            self.assertFalse(entry["verified"])
            self.assertNotIn("credential", entry)

    async def test_internal_entries_have_null_account_fields(self):
        service, _ = make_service()
        entry = await service.get("ollama")
        self.assertIsNone(entry["account"])
        self.assertIsNone(entry["auth_method"])
        self.assertFalse(entry["verified"])

    async def test_github_connect_with_good_token_verifies(self):
        service, _ = make_service()
        entry = await service.connect("github", credential="good-token")
        self.assertEqual(entry["status"], STATUS_CONNECTED)
        self.assertEqual(entry["account"], "octo-user")
        self.assertEqual(entry["auth_method"], "api_token")
        self.assertTrue(entry["verified"])
        self.assertIn("verified with GitHub", entry["note"])
        self.assertNotIn("credential", entry)
        self.assertNotIn("good-token", str(entry))
        entry = await service.get("github")
        self.assertEqual(entry["account"], "octo-user")
        self.assertTrue(entry["verified"])

    async def test_github_connect_with_rejected_token_is_conflict_and_stores_nothing(self):
        service, _ = make_service()
        with self.assertRaises(IntegrationError) as caught:
            await service.connect("github", credential="bad-token")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("rejected by GitHub", str(caught.exception))
        entry = await service.get("github")
        self.assertEqual(entry["status"], STATUS_NOT_CONNECTED)
        self.assertIsNone(entry["account"])

    async def test_github_connect_network_failure_is_503_and_stores_nothing(self):
        service, _ = make_service()
        with self.assertRaises(IntegrationError) as caught:
            await service.connect("github", credential="offline-token")
        self.assertEqual(caught.exception.status_code, 503)
        entry = await service.get("github")
        self.assertIsNone(entry["account"])

    async def test_github_connect_without_token_names_setup_steps(self):
        service, _ = make_service()
        with self.assertRaises(IntegrationError) as caught:
            await service.connect("github")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("fine-grained", str(caught.exception))

    async def test_other_external_connect_needs_account_then_records_unverified(self):
        service, _ = make_service()
        with self.assertRaises(IntegrationError) as caught:
            await service.connect("gmail")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("Sign in with your Google account", str(caught.exception))
        entry = await service.connect("gmail", account="kan@example.com", auth_method="oauth")
        self.assertEqual(entry["status"], STATUS_CONNECTED)
        self.assertEqual(entry["account"], "kan@example.com")
        self.assertEqual(entry["auth_method"], "oauth")
        self.assertFalse(entry["verified"])
        self.assertIn("Not verified against Gmail in this build", entry["note"])
        self.assertNotIn("credential", entry)

    async def test_other_external_connect_each_new_connector(self):
        service, _ = make_service()
        for integration_id in (
            "google_docs", "google_sheets", "instagram", "facebook",
            "threads", "spotify", "messenger",
        ):
            entry = await service.connect(integration_id, account="user", auth_method="oauth")
            self.assertEqual(entry["status"], STATUS_CONNECTED, integration_id)
            self.assertFalse(entry["verified"], integration_id)

    async def test_disconnect_external_clears_state(self):
        service, _ = make_service()
        await service.connect("github", credential="good-token")
        entry = await service.disconnect("github")
        self.assertEqual(entry["status"], STATUS_NOT_CONNECTED)
        self.assertIsNone(entry["account"])
        self.assertIsNone(entry["auth_method"])
        self.assertFalse(entry["verified"])
        self.assertIn("Disconnected from GitHub", entry["note"])

    async def test_disconnect_disabled_is_conflict(self):
        service, _ = make_service()
        await service.set_enabled("cloud", False)
        with self.assertRaises(IntegrationError) as caught:
            await service.disconnect("cloud")
        self.assertEqual(caught.exception.status_code, 409)
        await service.set_enabled("gmail", False)
        with self.assertRaises(IntegrationError) as caught:
            await service.disconnect("gmail")
        self.assertEqual(caught.exception.status_code, 409)

    async def test_toggle_external(self):
        service, _ = make_service()
        entry = await service.set_enabled("github", False)
        self.assertEqual(entry["status"], STATUS_DISABLED)
        entry = await service.set_enabled("github", True)
        self.assertEqual(entry["status"], STATUS_NOT_CONNECTED)

    async def test_connect_unknown_is_404(self):
        service, _ = make_service()
        with self.assertRaises(IntegrationError) as caught:
            await service.connect("nope", account="x", auth_method="oauth")
        self.assertEqual(caught.exception.status_code, 404)

    async def test_credential_never_appears_in_any_list_entry(self):
        service, _ = make_service()
        await service.connect("github", credential="good-token")
        for entry in await service.list_integrations():
            self.assertNotIn("credential", entry)
            self.assertNotIn("good-token", str(entry))


class RouterTests(unittest.TestCase):
    def test_router_has_expected_routes_and_local_only_dependency(self):
        service, _ = make_service()

        def require_local(request):
            return None

        router = create_router(service, require_local)
        self.assertEqual(router.prefix, "/api/integrations")
        routes = {(route.path, next(iter(route.methods))) for route in router.routes}
        self.assertEqual(
            routes,
            {
                ("/api/integrations", "GET"),
                ("/api/integrations/{integration_id}", "GET"),
                ("/api/integrations/{integration_id}/toggle", "POST"),
                ("/api/integrations/{integration_id}/connect", "POST"),
                ("/api/integrations/{integration_id}/disconnect", "POST"),
            },
        )
        self.assertTrue(router.dependencies)

    def test_list_endpoint_returns_wrapped_integrations(self):
        # The desktop page reads `data.integrations`; a bare list would leave
        # it on the loading spinner forever.
        import asyncio

        service, _ = make_service()

        def require_local(request):
            return None

        router = create_router(service, require_local)
        list_route = next(route for route in router.routes if route.path == "/api/integrations")
        body = asyncio.run(list_route.endpoint())
        self.assertIsInstance(body, dict)
        self.assertEqual(len(body["integrations"]), 23)
        self.assertEqual({item["id"] for item in body["integrations"]}, {item.id for item in CATALOG})

    def test_connect_endpoint_passes_payload_to_service(self):
        import asyncio

        service, _ = make_service()

        def require_local(request):
            return None

        router = create_router(service, require_local)
        connect_route = next(
            route for route in router.routes
            if route.path == "/api/integrations/{integration_id}/connect"
        )
        body = asyncio.run(connect_route.endpoint("github", ConnectPayload(credential="good-token")))
        self.assertEqual(body["account"], "octo-user")
        self.assertTrue(body["verified"])
        self.assertNotIn("credential", body)
        # An empty body still works for internal connectors.
        body = asyncio.run(connect_route.endpoint("cloud", None))
        self.assertEqual(body["id"], "cloud")


if __name__ == "__main__":
    unittest.main()
