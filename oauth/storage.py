"""In-memory OAuth storage. Async-safe via a single asyncio.Lock."""
import asyncio
import time
from dataclasses import dataclass
from typing import Any

from mcp.shared.auth import OAuthClientInformationFull
from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken


@dataclass
class _Entry:
    value: Any
    expires_at: float  # monotonic seconds; 0 = never expires

    def expired(self, now: float) -> bool:
        return self.expires_at != 0 and now >= self.expires_at


@dataclass
class PendingLogin:
    session_id: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str]
    state: str | None
    created_at: float


class InMemoryStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._clients: dict[str, _Entry] = {}
        self._login_sessions: dict[str, _Entry] = {}
        self._auth_codes: dict[str, _Entry] = {}
        self._access_tokens: dict[str, _Entry] = {}
        self._refresh_tokens: dict[str, _Entry] = {}

    async def _put(self, bucket: dict, key: str, value: Any, ttl_seconds: float) -> None:
        async with self._lock:
            expires = time.monotonic() + ttl_seconds if ttl_seconds > 0 else 0
            bucket[key] = _Entry(value=value, expires_at=expires)

    async def _get(self, bucket: dict, key: str) -> Any | None:
        async with self._lock:
            entry = bucket.get(key)
            if entry is None:
                return None
            if entry.expired(time.monotonic()):
                del bucket[key]
                return None
            return entry.value

    async def _delete(self, bucket: dict, key: str) -> None:
        async with self._lock:
            bucket.pop(key, None)

    # Clients never expire (ttl=0)
    async def put_client(self, client: OAuthClientInformationFull) -> None:
        await self._put(self._clients, client.client_id, client, ttl_seconds=0)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await self._get(self._clients, client_id)

    # Login sessions
    async def put_login_session(self, session_id: str, pending: PendingLogin,
                                ttl_seconds: float) -> None:
        await self._put(self._login_sessions, session_id, pending, ttl_seconds)

    async def get_login_session(self, session_id: str) -> PendingLogin | None:
        return await self._get(self._login_sessions, session_id)

    async def delete_login_session(self, session_id: str) -> None:
        await self._delete(self._login_sessions, session_id)

    # Authorization codes
    async def put_auth_code(self, code: str, auth_code: AuthorizationCode,
                            ttl_seconds: float) -> None:
        await self._put(self._auth_codes, code, auth_code, ttl_seconds)

    async def get_auth_code(self, code: str) -> AuthorizationCode | None:
        return await self._get(self._auth_codes, code)

    async def delete_auth_code(self, code: str) -> None:
        await self._delete(self._auth_codes, code)

    # Access tokens
    async def put_access_token(self, token: str, access: AccessToken,
                               ttl_seconds: float) -> None:
        await self._put(self._access_tokens, token, access, ttl_seconds)

    async def get_access_token(self, token: str) -> AccessToken | None:
        return await self._get(self._access_tokens, token)

    async def delete_access_token(self, token: str) -> None:
        await self._delete(self._access_tokens, token)

    # Refresh tokens
    async def put_refresh_token(self, token: str, refresh: RefreshToken,
                                ttl_seconds: float) -> None:
        await self._put(self._refresh_tokens, token, refresh, ttl_seconds)

    async def get_refresh_token(self, token: str) -> RefreshToken | None:
        return await self._get(self._refresh_tokens, token)

    async def delete_refresh_token(self, token: str) -> None:
        await self._delete(self._refresh_tokens, token)
