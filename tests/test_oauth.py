"""Unit and integration tests for the oauth package."""
import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from oauth.storage import InMemoryStore, PendingLogin  # noqa: E402


def run(coro):
    """Drive an async coroutine in a sync unittest method."""
    return asyncio.new_event_loop().run_until_complete(coro)


class InMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryStore()

    def test_put_and_get_access_token_roundtrip(self):
        from mcp.server.auth.provider import AccessToken
        tok = AccessToken(token="abc", client_id="c1", scopes=[], expires_at=None)

        async def scenario():
            await self.store.put_access_token("abc", tok, ttl_seconds=60)
            return await self.store.get_access_token("abc")

        result = run(scenario())
        self.assertIsNotNone(result)
        self.assertEqual(result.token, "abc")

    def test_get_returns_none_for_unknown_key(self):
        async def scenario():
            return await self.store.get_access_token("nope")
        self.assertIsNone(run(scenario()))

    def test_ttl_eviction_removes_expired_entries(self):
        from mcp.server.auth.provider import AccessToken
        tok = AccessToken(token="abc", client_id="c1", scopes=[], expires_at=None)

        async def scenario():
            await self.store.put_access_token("abc", tok, ttl_seconds=0.05)
            await asyncio.sleep(0.15)
            return await self.store.get_access_token("abc")

        self.assertIsNone(run(scenario()))

    def test_ttl_zero_means_never_expires(self):
        from mcp.shared.auth import OAuthClientInformationFull
        client = OAuthClientInformationFull(
            client_id="cid", client_secret="secret",
            redirect_uris=["https://example.com/cb"],
        )

        async def scenario():
            await self.store.put_client(client)
            await asyncio.sleep(0.05)
            return await self.store.get_client("cid")

        result = run(scenario())
        self.assertIsNotNone(result)
        self.assertEqual(result.client_id, "cid")

    def test_delete_is_idempotent(self):
        async def scenario():
            await self.store.delete_auth_code("nope")  # no error
            await self.store.delete_auth_code("nope")  # still no error
            return True
        self.assertTrue(run(scenario()))

    def test_pending_login_roundtrip(self):
        async def scenario():
            pending = PendingLogin(
                session_id="s1", client_id="c1",
                redirect_uri="https://claude.ai/cb",
                code_challenge="abc", scopes=[], state="xyz",
                created_at=time.monotonic(),
            )
            await self.store.put_login_session("s1", pending, ttl_seconds=60)
            got = await self.store.get_login_session("s1")
            return got

        result = run(scenario())
        self.assertEqual(result.session_id, "s1")
        self.assertEqual(result.state, "xyz")


if __name__ == "__main__":
    unittest.main()
