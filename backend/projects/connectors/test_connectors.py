import asyncio
import json
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
import uvicorn

from projects.agent_extensions import mcp_probe
from projects.connectors import CATALOG, TOOLS, ConnectorError, ConnectorService
from projects.connectors import clients, openclaw
from projects.connectors.api import create_connectors_router
from projects.connectors.service import clean_credentials

GITHUB_TOKEN = "github_pat_secret_value"
TELEGRAM_TOKEN = "123456789:AAExampleExampleExampleExampleExample"


class FakeHttp:
    """Answers by (method, url suffix) and records what was sent."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def __call__(self, method, url, *, headers=None, params=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "params": dict(params or {}), "json": json})
        for (route_method, suffix), answer in self.routes.items():
            if route_method == method and url.endswith(suffix):
                return answer(self.calls[-1]) if callable(answer) else answer
        return 404, {"message": "Not Found"}


def run(coroutine):
    return asyncio.run(coroutine)


class CatalogTest(unittest.TestCase):
    def test_only_external_apps_and_every_tool_has_a_handler(self):
        ids = [connector.id for connector in CATALOG]
        self.assertEqual(ids, ["github", "email", "telegram", "slack", "discord", "notion"])
        for internal in ("ollama", "openclaw", "cloud", "skills", "mcp"):
            self.assertNotIn(internal, ids)
        self.assertEqual(set(TOOLS), set(clients.HANDLERS))
        self.assertEqual(set(ids), set(clients.VERIFY))
        for connector in CATALOG:
            self.assertTrue(connector.steps and connector.key_url.startswith("https://"), connector.id)
            self.assertTrue(any(item.secret for item in connector.fields), connector.id)
            for tool in connector.tools:
                self.assertTrue(tool.name.startswith(f"{connector.id}_"), tool.name)
                self.assertTrue(set(tool.required) <= set(tool.properties), tool.name)
        # Sending, posting and creating are marked as changing the outside world.
        writes = sorted(name for name, (_, tool) in TOOLS.items() if tool.write)
        self.assertEqual(writes, ["discord_send_message", "email_send", "github_comment", "github_create_issue", "notion_create_page", "slack_post_message", "telegram_send_message"])

    def test_listing_never_contains_a_credential(self):
        service = ConnectorService()
        service.replace([{"id": "github", "account": "octo", "credentials": {"token": GITHUB_TOKEN}}], tool_token="t" * 32)
        listing = json.dumps(service.listing())
        self.assertNotIn(GITHUB_TOKEN, listing)
        github = next(item for item in service.listing() if item["id"] == "github")
        self.assertEqual((github["connected"], github["account"]), (True, "octo"))
        self.assertTrue(all(not item["connected"] for item in service.listing() if item["id"] != "github"))


class CredentialsTest(unittest.TestCase):
    def test_fields_are_checked_and_extra_values_dropped(self):
        github = CATALOG[0]
        self.assertEqual(clean_credentials(github, {"token": f" {GITHUB_TOKEN} ", "other": "x"}), {"token": GITHUB_TOKEN})
        for bad in ({}, {"token": ""}, {"token": "has space"}, {"token": "x" * 401}, {"token": "line\nbreak"}):
            with self.assertRaises(ConnectorError):
                clean_credentials(github, bad)
        email = CATALOG[1]
        cleaned = clean_credentials(email, {"provider": "gmail", "address": "a@example.com", "password": "abcd efgh ijkl mnop", "imap_host": "ignored.example.com"})
        self.assertEqual(cleaned, {"provider": "gmail", "address": "a@example.com", "password": "abcdefghijklmnop"})
        with self.assertRaises(ConnectorError):
            clean_credentials(email, {"provider": "hotmail", "address": "a@example.com", "password": "x"})
        with self.assertRaises(ConnectorError):
            clean_credentials(email, {"provider": "custom", "address": "a@example.com", "password": "x"})

    def test_custom_mail_servers_must_be_host_names(self):
        self.assertEqual(clients.email_servers({"provider": "gmail"}), ("imap.gmail.com", "smtp.gmail.com"))
        self.assertEqual(clients.email_servers({"provider": "custom", "imap_host": "IMAP.Example.com", "smtp_host": "smtp.example.com"}), ("imap.example.com", "smtp.example.com"))
        for bad in ("127.0.0.1", "localhost", "imap.example.com:993", "http://imap.example.com", "a b.example.com", ""):
            with self.assertRaises(ConnectorError, msg=bad):
                clients.email_servers({"provider": "custom", "imap_host": bad, "smtp_host": "smtp.example.com"})


class VerifyAndToolsTest(unittest.TestCase):
    def test_github_verify_and_tools(self):
        http = FakeHttp({
            ("GET", "/user"): lambda call: (200, {"login": "octo"}) if call["headers"]["Authorization"] == f"Bearer {GITHUB_TOKEN}" else (401, {"message": "Bad credentials"}),
            ("GET", "/user/repos"): (200, [{"full_name": "octo/app", "private": True, "default_branch": "main"}]),
            ("GET", "/repos/octo/app/issues/7"): (200, {"number": 7, "title": "Bug", "state": "open", "body": "It breaks", "comments": 1, "user": {"login": "amy"}, "labels": [{"name": "bug"}]}),
            ("GET", "/repos/octo/app/issues/7/comments"): (200, [{"user": {"login": "bo"}, "body": "Same here"}]),
            ("POST", "/repos/octo/app/issues"): lambda call: (201, {"number": 8, "title": call["json"]["title"], "state": "open", "html_url": "https://github.com/octo/app/issues/8"}),
            ("GET", "/repos/octo/app/contents/README.md"): (200, {"type": "file", "path": "README.md", "size": 5, "content": "SGVsbG8="}),
        })
        service = ConnectorService(http)
        verified = run(service.verify("github", {"token": GITHUB_TOKEN}))
        self.assertEqual(verified["account"], "octo")
        with self.assertRaises(ConnectorError) as caught:
            run(service.verify("github", {"token": "ghp_wrong"}))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertNotIn("ghp_wrong", str(caught.exception))
        with self.assertRaises(ConnectorError):
            run(service.verify("dropbox", {"token": "x"}))

        with self.assertRaises(ConnectorError) as caught:
            run(service.call("github_list_repos", {}))
        self.assertEqual(caught.exception.code, "not_connected")
        service.replace([{"id": "github", "account": "octo", "credentials": verified["credentials"]}], tool_token="t" * 32)
        self.assertEqual(run(service.call("github_list_repos", {}))["repositories"][0]["name"], "octo/app")
        issue = run(service.call("github_get_issue", {"repo": "octo/app", "number": 7}))
        self.assertEqual((issue["title"], issue["labels"], issue["comments"][0]["body"]), ("Bug", ["bug"], "Same here"))
        created = run(service.call("github_create_issue", {"repo": "octo/app", "title": "New", "body": "Text"}))
        self.assertEqual((created["created"], created["number"]), (True, 8))
        self.assertEqual(run(service.call("github_get_file", {"repo": "octo/app", "path": "README.md"}))["text"], "Hello")
        for bad in ({"repo": "octo/app/../other", "number": 1}, {"repo": "no-slash", "number": 1}, {"repo": "octo/app"}):
            with self.assertRaises(ConnectorError, msg=str(bad)):
                run(service.call("github_get_issue", bad))
        with self.assertRaises(ConnectorError):
            run(service.call("github_get_file", {"repo": "octo/app", "path": "../../secrets"}))
        with self.assertRaises(ConnectorError) as caught:
            run(service.call("github_list_repos", {"limit": 5, "evil": True}))
        self.assertEqual(caught.exception.code, "bad_input")
        with self.assertRaises(ConnectorError):
            run(service.call("no_such_tool", {}))
        # Every request went to GitHub's own API.
        self.assertTrue(all(call["url"].startswith("https://api.github.com/") for call in http.calls))

    def test_telegram_slack_discord_notion(self):
        http = FakeHttp({
            ("POST", "/getMe"): (200, {"ok": True, "result": {"username": "my_bot"}}),
            ("POST", "/getUpdates"): (200, {"ok": True, "result": [{"message": {"chat": {"id": 42, "first_name": "Amy"}, "from": {"username": "amy"}, "date": 1, "text": "hi bot"}}]}),
            ("POST", "/sendMessage"): lambda call: (200, {"ok": True, "result": {"message_id": 9, "chat": {"id": call["json"]["chat_id"]}}}),
            ("GET", "/auth.test"): lambda call: (200, {"ok": True, "user": "bot", "team": "Acme"}) if call["headers"]["Authorization"] == "Bearer xoxb-good" else (200, {"ok": False, "error": "invalid_auth"}),
            ("POST", "/chat.postMessage"): (200, {"ok": False, "error": "not_in_channel"}),
            ("GET", "/users/@me"): (200, {"username": "pockbot"}),
            ("POST", "/channels/123456789012345678/messages"): lambda call: (200, {"id": "1", "sent": call["json"]}),
            ("GET", "/users/me"): (200, {"name": "PockPock", "bot": {"workspace_name": "Home"}}),
            ("POST", "/search"): (200, {"results": [{"object": "page", "id": "11111111-2222-3333-4444-555555555555", "url": "https://notion.so/x", "properties": {"Name": {"type": "title", "title": [{"plain_text": "Plan"}]}}}]}),
        })
        service = ConnectorService(http)
        self.assertEqual(run(service.verify("telegram", {"token": TELEGRAM_TOKEN}))["account"], "@my_bot")
        with self.assertRaises(ConnectorError) as caught:
            run(service.verify("telegram", {"token": "not-a-token"}))
        self.assertIn("BotFather", str(caught.exception))
        self.assertEqual(run(service.verify("slack", {"token": "xoxb-good"}))["account"], "bot in Acme")
        with self.assertRaises(ConnectorError) as caught:
            run(service.verify("slack", {"token": "xoxb-bad"}))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(run(service.verify("discord", {"token": "discord-token"}))["account"], "pockbot")
        self.assertEqual(run(service.verify("notion", {"token": "ntn_secret"}))["account"], "PockPock in Home")

        service.replace([
            {"id": "telegram", "account": "@my_bot", "credentials": {"token": TELEGRAM_TOKEN}},
            {"id": "slack", "account": "bot", "credentials": {"token": "xoxb-good"}},
            {"id": "discord", "account": "pockbot", "credentials": {"token": "discord-token"}},
            {"id": "notion", "account": "PockPock", "credentials": {"token": "ntn_secret"}},
        ], tool_token="t" * 32)
        messages = run(service.call("telegram_get_messages", {}))["messages"]
        self.assertEqual((messages[0]["chat_id"], messages[0]["text"]), (42, "hi bot"))
        self.assertEqual(run(service.call("telegram_send_message", {"chat_id": "42", "text": "hello"}))["chat_id"], 42)
        with self.assertRaises(ConnectorError) as caught:
            run(service.call("slack_post_message", {"channel": "C1", "text": "hi"}))
        self.assertIn("invite the bot", str(caught.exception))
        sent = run(service.call("discord_send_message", {"channel_id": "123456789012345678", "text": "@everyone hi"}))
        self.assertTrue(sent["sent"])
        discord_call = next(call for call in http.calls if call["url"].endswith("/messages"))
        self.assertEqual(discord_call["json"]["allowed_mentions"], {"parse": []}, "a bot message cannot ping everyone")
        with self.assertRaises(ConnectorError):
            run(service.call("discord_send_message", {"channel_id": "../guilds", "text": "x"}))
        self.assertEqual(run(service.call("notion_search", {"query": "plan"}))["results"][0]["title"], "Plan")
        with self.assertRaises(ConnectorError):
            run(service.call("notion_read_page", {"page_id": "not-an-id"}))
        # An error never repeats a credential, even though Telegram's is part of the address.
        failing = ConnectorService(FakeHttp({}))
        failing.replace([{"id": "telegram", "account": "", "credentials": {"token": TELEGRAM_TOKEN}}])
        with self.assertRaises(ConnectorError) as caught:
            run(failing.call("telegram_get_messages", {}))
        self.assertNotIn(TELEGRAM_TOKEN, str(caught.exception))

    def test_email_send_validates_recipients_and_strips_header_breaks(self):
        sent = []
        with patch.object(clients, "_email_send_sync", lambda creds, to, subject, body: sent.append((to, subject, body)) or {"sent": True, "to": to}):
            service = ConnectorService()
            service.replace([{"id": "email", "account": "a@example.com", "credentials": {"provider": "gmail", "address": "a@example.com", "password": "abcdefghijklmnop"}}])
            result = run(service.call("email_send", {"to": "Bo <bo@example.com>, cy@example.com", "subject": "Hi\r\nBcc: evil@example.com", "body": "Text"}))
            self.assertEqual(result["to"], ["bo@example.com", "cy@example.com"])
            self.assertEqual(sent[0][1], "Hi Bcc: evil@example.com")
            for bad in ("not an address", "", "a@b.com, nope"):
                with self.assertRaises(ConnectorError, msg=bad):
                    run(service.call("email_send", {"to": bad, "subject": "s", "body": "b"}))
            with self.assertRaises(ConnectorError):
                run(service.call("email_read", {"id": "1 OR ALL"}))

    def test_mail_sign_in_failures_are_explained(self):
        import imaplib
        self.assertIn("app password", str(clients._mail_error(imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials"))))
        self.assertEqual(clients._mail_error(socket.gaierror()).code, "unreachable")


class OpenClawRegistrationTest(unittest.TestCase):
    def test_server_is_added_updated_and_removed_only_when_needed(self):
        servers: dict = {}
        ops = []

        def gateway(request):
            ops.append(request["op"])
            if request["op"] == "mcp_list":
                return {"servers": dict(servers)}
            if request["op"] == "mcp_set":
                servers[request["name"]] = request["server"]
            if request["op"] == "mcp_remove":
                servers.pop(request["name"], None)
            return {}

        self.assertEqual(openclaw.sync(gateway, connected=False, port=8766, tool_token=""), "unchanged")
        self.assertEqual(openclaw.sync(gateway, connected=True, port=8766, tool_token="tok"), "set")
        entry = servers["pockpock-connectors"]
        self.assertEqual((entry["url"], entry["transport"], entry["headers"]), ("http://127.0.0.1:8766/mcp/connectors", "streamable-http", {"Authorization": "Bearer tok"}))
        self.assertEqual(openclaw.sync(gateway, connected=True, port=8766, tool_token="tok"), "unchanged")
        self.assertEqual(openclaw.sync(gateway, connected=True, port=8766, tool_token="new"), "set")
        self.assertEqual(openclaw.sync(gateway, connected=False, port=8766, tool_token="new"), "removed")
        self.assertEqual(servers, {})
        self.assertEqual(ops.count("mcp_set"), 2)


class ApiTest(unittest.IsolatedAsyncioTestCase):
    """The routes over a real socket, with the repository's own MCP client as the tool caller."""

    async def asyncSetUp(self):
        self.http = FakeHttp({
            ("GET", "/user"): lambda call: (200, {"login": "octo"}) if call["headers"]["Authorization"] == f"Bearer {GITHUB_TOKEN}" else (401, {"message": "Bad credentials"}),
            ("GET", "/user/repos"): (200, [{"full_name": "octo/app"}]),
        })
        self.service = ConnectorService(self.http)
        self.changes = []
        app = FastAPI()
        app.include_router(create_connectors_router(self.service, on_change=lambda service: self.changes.append(service.connected_ids())))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            await asyncio.sleep(0.05)
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = patch.dict(os.environ, {"POCKPOCK_INTERNAL_TOKEN": "internal-token-value"})
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        self.server.should_exit = True
        deadline = time.time() + 5
        while self.thread.is_alive() and time.time() < deadline:
            await asyncio.sleep(0.05)

    async def test_verify_push_and_tools_over_mcp(self):
        import aiohttp
        internal = {"X-PockPock-Internal-Token": "internal-token-value"}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.url}/api/connectors/verify", json={"id": "github", "credentials": {"token": GITHUB_TOKEN}}) as response:
                self.assertEqual(response.status, 401, "verify needs the internal token")
            async with session.post(f"{self.url}/api/connectors/verify", json={"id": "github", "credentials": {"token": "ghp_wrong"}}, headers=internal) as response:
                self.assertEqual(response.status, 409)
                self.assertNotIn("ghp_wrong", await response.text())
            async with session.post(f"{self.url}/api/connectors/verify", json={"id": "github", "credentials": {"token": GITHUB_TOKEN}}, headers=internal) as response:
                self.assertEqual((await response.json())["account"], "octo")
            async with session.get(f"{self.url}/api/connectors") as response:
                self.assertTrue(all(not item["connected"] for item in (await response.json())["connectors"]), "verifying stores nothing")

            config = {"connected": [{"id": "github", "account": "octo", "credentials": {"token": GITHUB_TOKEN}}], "tool_token": "tool-token-0123456789abcdef"}
            async with session.put(f"{self.url}/api/connectors/config", json=config) as response:
                self.assertEqual(response.status, 401)
            async with session.put(f"{self.url}/api/connectors/config", json={**config, "connected": [{"id": "nope", "credentials": {}}]}, headers=internal) as response:
                self.assertEqual(response.status, 422)
            async with session.put(f"{self.url}/api/connectors/config", json=config, headers=internal) as response:
                self.assertEqual((await response.json())["tools"], 7)
            self.assertEqual(self.changes, [["github"]])
            async with session.get(f"{self.url}/api/connectors") as response:
                text = await response.text()
                self.assertNotIn(GITHUB_TOKEN, text)
                self.assertIn('"account":"octo"', text.replace(" ", ""))

            mcp = f"{self.url}/mcp/connectors"
            call = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "github_list_repos", "arguments": {}}}
            async with session.post(mcp, json=call) as response:
                self.assertEqual(response.status, 401, "tools need the local token")
            async with session.post(mcp, json=call, headers={"Authorization": "Bearer wrong"}) as response:
                self.assertEqual(response.status, 401)
            auth = {"Authorization": "Bearer tool-token-0123456789abcdef"}
            async with session.post(mcp, json=call, headers=auth) as response:
                result = (await response.json())["result"]
                self.assertEqual((result["isError"], result["structuredContent"]["repositories"][0]["name"]), (False, "octo/app"))
            async with session.post(mcp, json={**call, "params": {"name": "slack_list_channels"}}, headers=auth) as response:
                result = (await response.json())["result"]
                self.assertTrue(result["isError"])
                self.assertIn("Slack is not connected", result["content"][0]["text"])
            async with session.post(mcp, json={**call, "params": {"name": "rm_rf"}}, headers=auth) as response:
                self.assertEqual((await response.json())["error"]["code"], -32602)
            async with session.post(mcp, json={"jsonrpc": "2.0", "id": 6, "method": "resources/list"}, headers=auth) as response:
                self.assertEqual((await response.json())["error"]["code"], -32601)
            async with session.get(mcp, headers=auth) as response:
                self.assertEqual(response.status, 405)

        # The MCP client that PockPock uses to test third-party servers accepts this one.
        tools = await asyncio.to_thread(mcp_probe.probe_http, mcp, auth)
        self.assertEqual(sorted(tool["name"] for tool in tools), sorted(tool.name for tool in CATALOG[0].tools))


if __name__ == "__main__":
    unittest.main()
