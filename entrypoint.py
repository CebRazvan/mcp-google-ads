"""HTTP wrapper for cohnen/mcp-google-ads with OAuth 2.0 Authorization Server.

The server plays two roles: it's both a Resource Server (the /mcp endpoint,
gated by RequireAuthMiddleware) and an Authorization Server (the /authorize,
/token, /register, /revoke, /.well-known/* routes, plus our custom /oauth/login
form). FastMCP wires all of this together when `mcp._auth_server_provider` and
`mcp._token_verifier` are set before streamable_http_app() is called.

Note: `mcp._auth_server_provider` and `mcp._token_verifier` are SDK-internal
attributes (underscore-prefixed). FastMCP reads them publicly in its
streamable_http_app() method but does not expose a public setter because
the canonical path is to pass them to FastMCP(auth_server_provider=...,
token_verifier=...) at construction. Since google_ads_server.py creates
its FastMCP instance at module-import time without these parameters, we
set them after the fact. This is why the Dockerfile pins mcp>=1.27,<2 —
if the internal attribute names change, the pin catches it immediately.
"""
import os
import sys
import tempfile


def materialize_credentials() -> None:
    """If GOOGLE_ADS_CREDENTIALS_JSON is set, write it to a temp file
    and point GOOGLE_ADS_CREDENTIALS_PATH at it. Exit 1 if neither is set."""
    creds_json = os.environ.get("GOOGLE_ADS_CREDENTIALS_JSON")
    if creds_json:
        fd, path = tempfile.mkstemp(prefix="gads-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write(creds_json)
        os.environ["GOOGLE_ADS_CREDENTIALS_PATH"] = path
        return
    if not os.environ.get("GOOGLE_ADS_CREDENTIALS_PATH"):
        sys.stderr.write(
            "ERROR: set GOOGLE_ADS_CREDENTIALS_JSON (preferred) "
            "or GOOGLE_ADS_CREDENTIALS_PATH\n"
        )
        sys.exit(1)


def build_app():
    """Configure FastMCP as AS + RS, wire the in-memory OAuth provider,
    attach login form routes, and return the Starlette ASGI app."""
    from mcp.server.auth.settings import (
        AuthSettings, ClientRegistrationOptions, RevocationOptions,
    )
    from mcp.server.transport_security import TransportSecuritySettings
    from google_ads_server import mcp

    from oauth import InMemoryStore, InMemoryOAuthProvider, register_login_routes

    allowed_host = os.environ.get("MCP_ALLOWED_HOST", "gads.lucramresponsabil.com")
    issuer_url = f"https://{allowed_host}"

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8080"))
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[allowed_host, f"{allowed_host}:*"],
        allowed_origins=[issuer_url],
    )

    store = InMemoryStore()
    provider = InMemoryOAuthProvider(store, issuer_url=issuer_url)

    mcp.settings.auth = AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=issuer_url,
        client_registration_options=ClientRegistrationOptions(enabled=True),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=None,
    )
    # SDK-internal attributes — see module docstring.
    mcp._auth_server_provider = provider
    mcp._token_verifier = provider

    register_login_routes(mcp, provider)

    return mcp.streamable_http_app()


def main():
    for var in ("MCP_ADMIN_USER", "MCP_ADMIN_PASSWORD"):
        if not os.environ.get(var):
            sys.stderr.write(f"ERROR: {var} is required\n")
            sys.exit(1)

    materialize_credentials()

    import uvicorn
    app = build_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
