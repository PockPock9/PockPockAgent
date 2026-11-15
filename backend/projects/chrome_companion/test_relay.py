import asyncio
import os
import unittest

from fastapi import HTTPException

from projects.chrome_companion.api import router
from projects.chrome_companion.relay import (
    MAX_RELAY_MESSAGE_BYTES,
    ChromeCompanionRelay,
    ChromeRelayError,
)
from projects.internal_auth import require_internal_token


EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"
RUN_ID = "1" * 32


class ChromeCompanionRelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.relay = ChromeCompanionRelay()
        self.pairing = await self.relay.connect(
            EXTENSION_ID,
            17,
            "https://Example.com:443/",
        )

    async def test_connect_normalizes_origin_and_rejects_another_tab(self):
        self.assertEqual(self.pairing["origin"], "https://example.com")
        with self.assertRaisesRegex(ChromeRelayError, "already paired"):
            await self.relay.connect(EXTENSION_ID, 18, "https://example.com")

    async def test_request_is_delivered_and_response_is_bound_to_the_pairing(self):
        pending = asyncio.create_task(self.relay.request(RUN_ID, "ping", {}))
        command = await self.relay.next_command(self.pairing["pairing_id"])
        self.assertEqual(command["tab_id"], 17)
        self.assertEqual(command["origin"], "https://example.com")
        self.assertEqual(command["run_id"], RUN_ID)

        with self.assertRaisesRegex(ChromeRelayError, "does not match"):
            await self.relay.complete(
                self.pairing["pairing_id"],
                command["request_id"],
                18,
                "https://example.com",
                {"ok": True},
            )

        accepted = await self.relay.complete(
            self.pairing["pairing_id"],
            command["request_id"],
            17,
            "https://example.com",
            {"ok": True},
        )
        self.assertTrue(accepted)
        self.assertEqual(await pending, {"ok": True})

    async def test_pairing_is_owned_by_one_run_until_released(self):
        pending = asyncio.create_task(self.relay.request(RUN_ID, "ping", {}, timeout=1))
        command = await self.relay.next_command(self.pairing["pairing_id"])
        other_run = "2" * 32
        competing = asyncio.create_task(self.relay.request(other_run, "ping", {}, timeout=1))
        await asyncio.sleep(0)

        await self.relay.complete(
            self.pairing["pairing_id"],
            command["request_id"],
            17,
            "https://example.com",
            {"ok": True},
        )
        await pending
        with self.assertRaisesRegex(ChromeRelayError, "another active run"):
            await competing
        self.assertTrue(await self.relay.release_run(RUN_ID))

    async def test_disconnect_fails_pending_request_and_removes_pairing(self):
        pending = asyncio.create_task(self.relay.request(RUN_ID, "ping", {}))
        await self.relay.next_command(self.pairing["pairing_id"])
        self.assertTrue(await self.relay.disconnect(self.pairing["pairing_id"]))
        with self.assertRaisesRegex(ChromeRelayError, "disconnected"):
            await pending
        with self.assertRaisesRegex(ChromeRelayError, "No matching"):
            await self.relay.next_command(self.pairing["pairing_id"])

    async def test_timeout_removes_undelivered_request(self):
        with self.assertRaisesRegex(ChromeRelayError, "did not respond"):
            await self.relay.request(RUN_ID, "ping", {}, timeout=0.01)
        self.assertIsNone(await self.relay.next_command(self.pairing["pairing_id"]))

    async def test_invalid_origin_and_unsupported_operation_are_rejected(self):
        with self.assertRaises(ChromeRelayError):
            await self.relay.connect(EXTENSION_ID, 1, "https://user:pass@example.com/path")
        with self.assertRaisesRegex(ChromeRelayError, "not supported"):
            await self.relay.request(RUN_ID, "execute_script", {})

    async def test_request_and_response_sizes_are_bounded(self):
        oversized = {"text": "x" * MAX_RELAY_MESSAGE_BYTES}
        with self.assertRaisesRegex(ChromeRelayError, "size limit"):
            await self.relay.request(RUN_ID, "ping", oversized)

        pending = asyncio.create_task(self.relay.request(RUN_ID, "ping", {}))
        command = await self.relay.next_command(self.pairing["pairing_id"])
        with self.assertRaisesRegex(ChromeRelayError, "size limit"):
            await self.relay.complete(
                self.pairing["pairing_id"],
                command["request_id"],
                17,
                "https://example.com",
                oversized,
            )
        await self.relay.disconnect(self.pairing["pairing_id"])
        with self.assertRaisesRegex(ChromeRelayError, "disconnected"):
            await pending


class ChromeCompanionApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_routes_require_the_service_token(self):
        previous = os.environ.get("POCKPOCK_INTERNAL_TOKEN")
        os.environ["POCKPOCK_INTERNAL_TOKEN"] = "unit-test-token"
        try:
            self.assertTrue(router.dependencies)
            with self.assertRaises(HTTPException) as raised:
                await require_internal_token(None)
            self.assertEqual(raised.exception.status_code, 401)
        finally:
            if previous is None:
                os.environ.pop("POCKPOCK_INTERNAL_TOKEN", None)
            else:
                os.environ["POCKPOCK_INTERNAL_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
