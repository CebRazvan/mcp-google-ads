"""OAuth 2.0 Authorization Server provider — in-memory, single-user."""
import secrets
import time

from mcp.server.auth.provider import (
    OAuthAuthorizationServerProvider, AuthorizationParams,
    AuthorizationCode, AccessToken, RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .storage import InMemoryStore, PendingLogin


LOGIN_SESSION_TTL = 5 * 60            # 5 minutes
AUTH_CODE_TTL = 60                    # RFC 6749 §4.1.2
ACCESS_TOKEN_TTL = 60 * 60            # 1 hour
REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60 # 30 days


class InMemoryOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Plays both OAuthAuthorizationServerProvider (for /authorize, /token,
    /register, /revoke handlers) and TokenVerifier (for BearerAuthBackend,
    which gates /mcp requests). FastMCP calls verify_token() on the latter,
    load_access_token() on the former — both are implemented and return
    the same data."""

    def __init__(self, store: InMemoryStore, issuer_url: str):
        self.store = store
        self.issuer_url = issuer_url.rstrip("/")

    # --- OAuthAuthorizationServerProvider ---

    async def get_client(self, client_id):
        return await self.store.get_client(client_id)

    async def register_client(self, client_info):
        await self.store.put_client(client_info)

    async def authorize(self, client, params: AuthorizationParams):
        session_id = secrets.token_urlsafe(32)
        pending = PendingLogin(
            session_id=session_id,
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            code_challenge=params.code_challenge,
            scopes=list(params.scopes or []),
            state=params.state,
            created_at=time.monotonic(),
        )
        await self.store.put_login_session(session_id, pending, LOGIN_SESSION_TTL)
        return f"{self.issuer_url}/oauth/login?session={session_id}"

    async def load_authorization_code(self, client, authorization_code):
        code = await self.store.get_auth_code(authorization_code)
        if code is not None and code.client_id == client.client_id:
            return code
        return None

    async def exchange_authorization_code(self, client, authorization_code):
        await self.store.delete_auth_code(authorization_code.code)
        return await self._issue_token_pair(client, list(authorization_code.scopes))

    async def load_refresh_token(self, client, refresh_token):
        rt = await self.store.get_refresh_token(refresh_token)
        if rt is not None and rt.client_id == client.client_id:
            return rt
        return None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        await self.store.delete_refresh_token(refresh_token.token)
        return await self._issue_token_pair(
            client, list(scopes or refresh_token.scopes))

    async def load_access_token(self, token: str):
        return await self.store.get_access_token(token)

    async def revoke_token(self, token):
        if isinstance(token, AccessToken):
            await self.store.delete_access_token(token.token)
        else:
            await self.store.delete_refresh_token(token.token)

    # --- TokenVerifier (called by BearerAuthBackend on every /mcp request) ---

    async def verify_token(self, token: str):
        return await self.store.get_access_token(token)

    # --- helper ---

    async def _issue_token_pair(self, client, scopes: list[str]) -> OAuthToken:
        access_str = secrets.token_urlsafe(32)
        refresh_str = secrets.token_urlsafe(32)
        now = int(time.time())

        access = AccessToken(
            token=access_str, client_id=client.client_id, scopes=scopes,
            expires_at=now + ACCESS_TOKEN_TTL,
        )
        refresh = RefreshToken(
            token=refresh_str, client_id=client.client_id, scopes=scopes,
        )

        await self.store.put_access_token(access_str, access, ACCESS_TOKEN_TTL)
        await self.store.put_refresh_token(refresh_str, refresh, REFRESH_TOKEN_TTL)

        return OAuthToken(
            access_token=access_str,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh_str,
            scope=" ".join(scopes) if scopes else None,
        )
