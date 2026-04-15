"""HTTP wrapper for cohnen/mcp-google-ads.

Wraps the upstream FastMCP server with:
- credentials-from-env-var materialization
- bearer-token auth middleware
- DNS-rebinding allowlist for the production host
- uvicorn-driven streamable-http serving
"""
import os
import sys
import tempfile

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


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


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that requires `Authorization: Bearer <token>`.

    Returns a 401 JSON response for anything else.
    """

    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request, call_next):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header[7:] != self.token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_app():
    """Configure the FastMCP instance and return a Starlette ASGI app
    with bearer auth middleware attached.

    Must be called AFTER materialize_credentials(), because importing
    google_ads_server reads GOOGLE_ADS_CREDENTIALS_PATH at module load.
    """
    from mcp.server.transport_security import TransportSecuritySettings
    from google_ads_server import mcp

    port = int(os.environ.get("PORT", "8080"))
    allowed_host = os.environ.get("MCP_ALLOWED_HOST", "gads.lucramresponsabil.com")
    token = os.environ["MCP_AUTH_TOKEN"]  # main() already verified non-empty

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[allowed_host, f"{allowed_host}:*"],
        allowed_origins=[f"https://{allowed_host}"],
    )

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware, token=token)
    return app


def main():
    if not os.environ.get("MCP_AUTH_TOKEN"):
        sys.stderr.write("ERROR: MCP_AUTH_TOKEN is required\n")
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
