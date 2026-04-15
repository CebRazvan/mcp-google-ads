# Dockerize mcp-google-ads for Dokploy + Traefik deployment

**Status:** Approved
**Date:** 2026-04-15
**Target domain:** `gads.lucramresponsabil.com`
**Deployment target:** VPS running Dokploy with Traefik, building from fork `CebRazvan/mcp-google-ads`.

## Goal

Wrap the upstream `cohnen/mcp-google-ads` stdio MCP server in a container that speaks HTTP(S), so Claude can reach it as a remote MCP server at `https://gads.lucramresponsabil.com/mcp`. No upstream code changes; all new files live alongside the existing server module.

## Non-goals

- Refactoring `google_ads_server.py`.
- Supporting multiple concurrent Google Ads accounts in one container.
- OAuth-based end-user auth on the HTTP endpoint (a shared bearer token is sufficient for the single-user case).
- SSE transport support (`streamable-http` only).
- Node.js / Supergateway fallback — not needed because FastMCP speaks HTTP natively.

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Credentials delivery | Env var `GOOGLE_ADS_CREDENTIALS_JSON`, materialized to `/tmp/gads-*.json` at startup | No host filesystem setup; secrets live in Dokploy's store; rotation is one-panel edit |
| HTTP auth | Bearer token middleware in the app, checked against `MCP_AUTH_TOKEN` env var | Idiomatic for remote MCP; survives URL leaks better than BasicAuth; native Claude client support |
| MCP transport | `streamable-http` | Current MCP spec (2025-03-26+); single endpoint; future-proof |
| MCP SDK version | Pin `mcp>=1.10` in the Dockerfile (not `requirements.txt`) | `streamable-http` was added after 1.3; verified working on 1.27.0. Pin in Dockerfile preserves clean rebases against upstream |
| Code source | `COPY . /app` (not `git clone` inside the image) | This working tree *is* the fork; `COPY` lets us iterate and builds from current state |
| Base image | `python:3.12-slim` | Small, matches upstream's Python constraint |
| Non-root user | No | Container only writes to `/tmp`; not worth the complexity for this scope |
| Traefik labels | Prefer Dokploy's auto-generation via the domain UI; provide manual-label fallback as a reference | Dokploy's UI is the supported path; labels exist for edge cases |

## File inventory

New files only — no edits to existing files.

```
mcp-google-ads/
├── Dockerfile          ← NEW
├── entrypoint.py       ← NEW
├── .dockerignore       ← NEW
├── docs/superpowers/specs/
│   └── 2026-04-15-dockerize-mcp-dokploy-design.md   ← THIS FILE
└── (everything else unchanged)
```

## Component designs

### 1. `Dockerfile`

Single-stage, `python:3.12-slim`-based. Layer ordering keeps upstream dep installs cached across code-only changes.

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

RUN pip install "mcp>=1.10" uvicorn starlette

COPY . .

EXPOSE 8080

CMD ["python", "/app/entrypoint.py"]
```

Rationale:
- `COPY requirements.txt` alone first → Docker layer cache reuses deps when only application code changes.
- `mcp>=1.2` pinned in a separate layer so upstream `requirements.txt` changes don't invalidate it.
- No `git` package, no Node.js, no Supergateway.

### 2. `entrypoint.py`

Four responsibilities:

1. **Materialize credentials** — if `GOOGLE_ADS_CREDENTIALS_JSON` is set, write it to a `tempfile.mkstemp()` file and point `GOOGLE_ADS_CREDENTIALS_PATH` at that file *before* importing `google_ads_server`. This matters because the upstream module reads `GOOGLE_ADS_CREDENTIALS_PATH` at import time.
2. **Configure transport security** — FastMCP's DNS rebinding protection rejects any non-localhost Host header by default. Production traffic from Traefik has `Host: gads.lucramresponsabil.com`, so `mcp.settings.transport_security.allowed_hosts` must include the public domain.
3. **Bearer-token middleware** — a Starlette `BaseHTTPMiddleware` wired via `app.add_middleware(BearerAuthMiddleware, token=...)` on the Starlette app returned by `mcp.streamable_http_app()`. Rejects any request without `Authorization: Bearer <MCP_AUTH_TOKEN>` with 401.
4. **Serve via uvicorn** — take the Starlette app from `mcp.streamable_http_app()`, attach our middleware, run under `uvicorn` on `0.0.0.0:$PORT`. (We don't call `mcp.run()` — we need direct access to the ASGI app to inject middleware, and the mcp SDK has no public hook for app-level custom middleware.)

```python
"""HTTP wrapper for cohnen/mcp-google-ads."""
import os
import sys
import tempfile

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def materialize_credentials() -> None:
    """If GOOGLE_ADS_CREDENTIALS_JSON is set, write it to a temp file
    and point GOOGLE_ADS_CREDENTIALS_PATH at it. Exit if neither is set."""
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
    """Requires `Authorization: Bearer <token>`. Returns 401 otherwise."""
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
    with bearer auth middleware attached."""
    from mcp.server.transport_security import TransportSecuritySettings
    from google_ads_server import mcp

    allowed_host = os.environ.get("MCP_ALLOWED_HOST", "gads.lucramresponsabil.com")
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", "8080"))
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[allowed_host, f"{allowed_host}:*"],
        allowed_origins=[f"https://{allowed_host}"],
    )

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware, token=AUTH_TOKEN)
    return app


def main():
    materialize_credentials()
    import uvicorn
    app = build_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_level="info",
    )


AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
if __name__ == "__main__":
    if not AUTH_TOKEN:
        sys.stderr.write("ERROR: MCP_AUTH_TOKEN is required\n")
        sys.exit(1)
    main()
```

### SDK compatibility — verified

The approach above was verified end-to-end against `mcp==1.27.0` during planning. Probed and confirmed:

1. **`mcp.streamable_http_app()`** returns a Starlette app; `add_middleware(...)` on it correctly injects bearer auth as the outermost layer. No auth → 401, wrong token → 401, correct token → MCP protocol response. Initialize round-trip returns 200.
2. **`mcp.settings.host` / `mcp.settings.port`** are real Pydantic fields that FastMCP reads from. We don't need `mcp.run()`; we bypass it and drive `uvicorn.run()` directly with the Starlette app.
3. **Transport security must be configured for the production host** or FastMCP returns 421 for every request (DNS rebinding protection is on by default with a localhost-only allowlist). Setting `allowed_hosts` to include `gads.lucramresponsabil.com` resolves this.

The `mcp>=1.10` pin comfortably covers all three APIs (they were added earlier than 1.10).

### 3. `.dockerignore`

```
.git
.gitignore
.venv
venv
__pycache__
*.pyc
*.pyo
.pytest_cache
.mypy_cache
.idea
.vscode
docs/
pulls/
*.md
*.svg
*.jpeg
*.png
test_*.py
format_customer_id_test.py
.env
.env.*
credentials*.json
```

Keeps the image lean and, more importantly, guarantees no secret files can accidentally get baked in.

## Deployment config

### Environment variables (set in Dokploy UI)

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_ADS_CREDENTIALS_JSON` | yes* | Full OAuth or service-account JSON, pasted as one value |
| `GOOGLE_ADS_CREDENTIALS_PATH` | * | Alternative to the JSON var — path to a mounted file. Only one of the two is required. |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | yes | Google Ads developer token |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | yes | MCC customer ID (digits only) |
| `GOOGLE_ADS_AUTH_TYPE` | yes | `oauth` or `service_account` |
| `MCP_AUTH_TOKEN` | yes | Bearer token Claude must send. Generate with `openssl rand -hex 32`. |
| `MCP_ALLOWED_HOST` | no | Public hostname for DNS rebinding protection. Defaults to `gads.lucramresponsabil.com`. |
| `PORT` | no | Defaults to `8080` (Dockerfile ENV) |

`*` = exactly one of `GOOGLE_ADS_CREDENTIALS_JSON` or `GOOGLE_ADS_CREDENTIALS_PATH` must be set.

### Traefik routing

**Preferred:** configure the domain + port in Dokploy's domain UI; it generates the labels automatically. Port `8080`, HTTPS with `letsencrypt`, HTTP → HTTPS redirect enabled.

**Manual-label fallback** (only if the auto-generated labels are wrong for any reason):

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.docker.network=dokploy-network"
  - "traefik.http.routers.gads-mcp.rule=Host(`gads.lucramresponsabil.com`)"
  - "traefik.http.routers.gads-mcp.entrypoints=websecure"
  - "traefik.http.routers.gads-mcp.tls=true"
  - "traefik.http.routers.gads-mcp.tls.certresolver=letsencrypt"
  - "traefik.http.routers.gads-mcp.service=gads-mcp"
  - "traefik.http.routers.gads-mcp-http.rule=Host(`gads.lucramresponsabil.com`)"
  - "traefik.http.routers.gads-mcp-http.entrypoints=web"
  - "traefik.http.routers.gads-mcp-http.middlewares=gads-mcp-redirect"
  - "traefik.http.middlewares.gads-mcp-redirect.redirectscheme.scheme=https"
  - "traefik.http.middlewares.gads-mcp-redirect.redirectscheme.permanent=true"
  - "traefik.http.services.gads-mcp.loadbalancer.server.port=8080"
```

No Traefik-level auth: the app handles it via the bearer middleware.

## Data flow

```
Claude client
  │  HTTPS POST https://gads.lucramresponsabil.com/mcp
  │  Authorization: Bearer <MCP_AUTH_TOKEN>
  ▼
Traefik  ──(letsencrypt TLS termination)──►  container:8080
  │
  ▼
BearerAuthMiddleware  ──(401 if token mismatch)──►  Claude
  │  (token ok)
  ▼
FastMCP streamable-http handler
  │
  ▼
google_ads_server.py tools  ──►  Google Ads API
                                 (creds read from /tmp/gads-*.json)
```

## Testing strategy

Implementation plan will verify:

1. **Image builds** — `docker build -t gads-mcp .` completes without error.
2. **Container starts with required env vars** — set a fake `MCP_AUTH_TOKEN` and `GOOGLE_ADS_CREDENTIALS_JSON='{}'`; container should start and listen on `:8080`.
3. **Container rejects missing env vars** — starting without `MCP_AUTH_TOKEN` exits with a clear error.
4. **401 on missing/wrong token** — `curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/mcp` without auth returns `401`; wrong bearer returns `401`.
5. **200-path reachable with correct token** — `curl -H "Authorization: Bearer <token>"` to `/mcp` gets past the middleware (MCP protocol response, not 401).
6. **Dokploy deploy dry-run** — ensure the domain/port config produces valid Traefik labels; verify `https://gads.lucramresponsabil.com/mcp` reaches the container after deploy.

End-to-end Google Ads API calls are *not* part of the Docker work — they depend on real credentials and are a downstream concern.

## Rollback plan

If the deploy breaks: revert the Dokploy deployment to the previous image tag (Dokploy keeps deploy history). The source rollback is `git revert` on the commit that adds `Dockerfile`/`entrypoint.py`/`.dockerignore`. No upstream files were modified, so there's nothing else to undo.
