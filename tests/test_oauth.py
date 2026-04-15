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


class InMemoryOAuthProviderTests(unittest.TestCase):
    def setUp(self):
        from oauth.storage import InMemoryStore
        from oauth.provider import InMemoryOAuthProvider
        self.store = InMemoryStore()
        self.provider = InMemoryOAuthProvider(self.store, issuer_url="https://example.com")

    def _make_client(self, client_id="c1"):
        from mcp.shared.auth import OAuthClientInformationFull
        return OAuthClientInformationFull(
            client_id=client_id, client_secret="secret",
            redirect_uris=["https://claude.ai/cb"],
        )

    def _make_auth_params(self, code_challenge="abc", state="xyz"):
        from mcp.server.auth.provider import AuthorizationParams
        from pydantic import AnyUrl
        return AuthorizationParams(
            state=state,
            scopes=[],
            code_challenge=code_challenge,
            redirect_uri=AnyUrl("https://claude.ai/cb"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        )

    def test_register_and_get_client_roundtrip(self):
        async def scenario():
            await self.provider.register_client(self._make_client("c1"))
            return await self.provider.get_client("c1")
        got = run(scenario())
        self.assertIsNotNone(got)
        self.assertEqual(got.client_id, "c1")

    def test_authorize_returns_login_url_with_session_id(self):
        async def scenario():
            client = self._make_client()
            await self.provider.register_client(client)
            return await self.provider.authorize(client, self._make_auth_params())
        url = run(scenario())
        self.assertTrue(url.startswith("https://example.com/oauth/login?session="))

    def test_authorize_persists_pending_login(self):
        async def scenario():
            client = self._make_client()
            await self.provider.register_client(client)
            url = await self.provider.authorize(client, self._make_auth_params(
                code_challenge="challenge123"))
            session_id = url.rsplit("=", 1)[1]
            pending = await self.store.get_login_session(session_id)
            return pending
        pending = run(scenario())
        self.assertIsNotNone(pending)
        self.assertEqual(pending.code_challenge, "challenge123")
        self.assertEqual(pending.state, "xyz")

    def test_exchange_authorization_code_is_single_use(self):
        from mcp.server.auth.provider import AuthorizationCode
        import time as _time

        async def scenario():
            client = self._make_client()
            await self.provider.register_client(client)
            code = AuthorizationCode(
                code="one-time", scopes=[],
                expires_at=int(_time.time()) + 60,
                client_id="c1", code_challenge="abc",
                redirect_uri="https://claude.ai/cb",
                redirect_uri_provided_explicitly=True,
            )
            await self.store.put_auth_code("one-time", code, ttl_seconds=60)

            first = await self.provider.exchange_authorization_code(client, code)
            second_code = await self.store.get_auth_code("one-time")
            return first, second_code

        token_pair, after = run(scenario())
        self.assertIsNotNone(token_pair.access_token)
        self.assertIsNotNone(token_pair.refresh_token)
        self.assertIsNone(after, "auth code must be deleted after exchange")

    def test_refresh_token_rotation_invalidates_old(self):
        from mcp.server.auth.provider import RefreshToken

        async def scenario():
            client = self._make_client()
            await self.provider.register_client(client)
            # Seed a refresh token directly
            old = RefreshToken(token="old-refresh", client_id="c1", scopes=[])
            await self.store.put_refresh_token("old-refresh", old, ttl_seconds=60)

            new_pair = await self.provider.exchange_refresh_token(client, old, [])
            old_after = await self.store.get_refresh_token("old-refresh")
            new_after = await self.store.get_refresh_token(new_pair.refresh_token)
            return new_pair, old_after, new_after

        new_pair, old_after, new_after = run(scenario())
        self.assertIsNone(old_after, "old refresh token must be deleted")
        self.assertIsNotNone(new_after, "new refresh token must be stored")
        self.assertNotEqual(new_pair.refresh_token, "old-refresh")

    def test_load_access_token_returns_stored_token(self):
        from mcp.server.auth.provider import AccessToken

        async def scenario():
            tok = AccessToken(token="a1", client_id="c1", scopes=[], expires_at=None)
            await self.store.put_access_token("a1", tok, ttl_seconds=60)
            return await self.provider.load_access_token("a1")

        got = run(scenario())
        self.assertIsNotNone(got)

    def test_verify_token_is_alias_of_load_access_token(self):
        from mcp.server.auth.provider import AccessToken

        async def scenario():
            tok = AccessToken(token="a1", client_id="c1", scopes=[], expires_at=None)
            await self.store.put_access_token("a1", tok, ttl_seconds=60)
            return await self.provider.verify_token("a1")

        got = run(scenario())
        self.assertIsNotNone(got, "verify_token must return the same result as load_access_token")

    def test_revoke_access_token_removes_from_storage(self):
        from mcp.server.auth.provider import AccessToken

        async def scenario():
            tok = AccessToken(token="a1", client_id="c1", scopes=[], expires_at=None)
            await self.store.put_access_token("a1", tok, ttl_seconds=60)
            await self.provider.revoke_token(tok)
            return await self.store.get_access_token("a1")

        self.assertIsNone(run(scenario()))


if __name__ == "__main__":
    unittest.main()
