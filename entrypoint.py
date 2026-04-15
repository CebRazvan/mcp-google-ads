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
