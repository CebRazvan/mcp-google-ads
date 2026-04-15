# Dockerize mcp-google-ads for Dokploy + Traefik — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a container image of `cohnen/mcp-google-ads` that serves the MCP protocol over HTTP with bearer-token auth, deployable to Dokploy+Traefik at `https://gads.lucramresponsabil.com/mcp`.

**Architecture:** Wrapper-file approach — add `entrypoint.py`, `Dockerfile`, `.dockerignore` alongside the unchanged upstream `google_ads_server.py`. `entrypoint.py` takes FastMCP's Starlette app from `mcp.streamable_http_app()`, bolts a `BearerAuthMiddleware` onto it, configures DNS-rebinding-protection allowlist for the production domain, and runs it under uvicorn. Credentials JSON is passed via env var and materialized to a temp file at startup.

**Tech Stack:** Python 3.12-slim, `mcp>=1.10`, Starlette, uvicorn, Docker, Dokploy, Traefik.

**Spec reference:** `docs/superpowers/specs/2026-04-15-dockerize-mcp-dokploy-design.md`

---

## File structure

| File | Purpose |
|---|---|
| `.dockerignore` | NEW — keeps image lean, prevents secret leakage |
| `entrypoint.py` | NEW — HTTP wrapper with credential materialization, bearer auth, transport-security config |
| `Dockerfile` | NEW — single-stage python:3.12-slim build |
| `tests/test_entrypoint.py` | NEW — unit tests for `materialize_credentials` and `BearerAuthMiddleware` (stdlib `unittest`, no new dev deps) |
| `docs/superpowers/plans/2026-04-15-dockerize-mcp-dokploy.md` | THIS FILE (already written) |

Nothing in `google_ads_server.py` or `requirements.txt` is modified. `tests/` is a new top-level directory (existing tests are in repo root — we keep new tests isolated from upstream's `test_*.py` to simplify rebases).

Local dev prerequisites already verified present: `starlette`, `httpx`, `mcp` (any version — tests don't touch mcp). Tests use stdlib `unittest`, so `python -m unittest discover tests` works with no extra installs.

---

## Task 1: Create `.dockerignore`

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Write the file**

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
tests/
.env
.env.*
credentials*.json
```

Note: `tests/` is excluded because tests run at dev time, not in the built image. Existing upstream `test_*.py` files at repo root are also excluded.

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore for Docker build"
```

---

## Task 2: TDD — `materialize_credentials()` function

**Files:**
- Create: `tests/__init__.py` (empty, so `unittest discover` finds the tests package)
- Create: `tests/test_entrypoint.py`
- Create: `entrypoint.py`

- [ ] **Step 1: Create the empty test package file**

```bash
mkdir -p tests
```

Create `tests/__init__.py` as an empty file (use `Write` tool with empty string content).

- [ ] **Step 2: Write the failing tests first**

Create `tests/test_entrypoint.py`:

```python
"""Unit tests for entrypoint.py."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Make the repo root importable so `import entrypoint` works
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import entrypoint  # noqa: E402


class MaterializeCredentialsTests(unittest.TestCase):
    def setUp(self):
        # Clean env so each test is isolated
        self._saved = {
            k: os.environ.pop(k, None)
            for k in ("GOOGLE_ADS_CREDENTIALS_JSON", "GOOGLE_ADS_CREDENTIALS_PATH")
        }

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_writes_json_to_temp_file_and_sets_path(self):
        payload = {"type": "service_account", "client_email": "x@y"}
        os.environ["GOOGLE_ADS_CREDENTIALS_JSON"] = json.dumps(payload)

        entrypoint.materialize_credentials()

        path = os.environ.get("GOOGLE_ADS_CREDENTIALS_PATH")
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            self.assertEqual(json.load(f), payload)

    def test_preserves_existing_path_when_json_not_set(self):
        os.environ["GOOGLE_ADS_CREDENTIALS_PATH"] = "/pre/existing.json"

        entrypoint.materialize_credentials()

        self.assertEqual(
            os.environ["GOOGLE_ADS_CREDENTIALS_PATH"], "/pre/existing.json"
        )

    def test_exits_when_neither_env_var_set(self):
        with self.assertRaises(SystemExit) as cm:
            entrypoint.materialize_credentials()
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail with ImportError**

Run:
```bash
cd C:/Users/Razvan/PycharmProjects/mcp-google-ads && python -m unittest tests.test_entrypoint -v
```

Expected: `ModuleNotFoundError: No module named 'entrypoint'` or similar — the module does not exist yet.

- [ ] **Step 4: Create `entrypoint.py` with the minimal implementation**

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
cd C:/Users/Razvan/PycharmProjects/mcp-google-ads && python -m unittest tests.test_entrypoint -v
```

Expected: 3 tests, all PASS.

- [ ] **Step 6: Commit**

```bash
git add entrypoint.py tests/__init__.py tests/test_entrypoint.py
git commit -m "feat: add credential materialization for entrypoint.py"
```

---

## Task 3: TDD — `BearerAuthMiddleware`

**Files:**
- Modify: `tests/test_entrypoint.py` (add test class)
- Modify: `entrypoint.py` (add class)

- [ ] **Step 1: Append the failing middleware tests**

Append this class to `tests/test_entrypoint.py` (before the `if __name__ == "__main__":` block):

```python
class BearerAuthMiddlewareTests(unittest.TestCase):
    def _build_app(self, token: str):
        """Build a tiny Starlette app wrapped in our middleware."""
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import PlainTextResponse

        async def ok(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", ok)])
        app.add_middleware(entrypoint.BearerAuthMiddleware, token=token)
        return app

    def test_rejects_request_without_authorization_header(self):
        from starlette.testclient import TestClient
        app = self._build_app("secret")
        with TestClient(app) as c:
            r = c.get("/")
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"error": "unauthorized"})

    def test_rejects_request_with_wrong_token(self):
        from starlette.testclient import TestClient
        app = self._build_app("secret")
        with TestClient(app) as c:
            r = c.get("/", headers={"Authorization": "Bearer wrong"})
            self.assertEqual(r.status_code, 401)

    def test_rejects_non_bearer_scheme(self):
        from starlette.testclient import TestClient
        app = self._build_app("secret")
        with TestClient(app) as c:
            r = c.get("/", headers={"Authorization": "Basic secret"})
            self.assertEqual(r.status_code, 401)

    def test_accepts_correct_bearer_token(self):
        from starlette.testclient import TestClient
        app = self._build_app("secret")
        with TestClient(app) as c:
            r = c.get("/", headers={"Authorization": "Bearer secret"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.text, "ok")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd C:/Users/Razvan/PycharmProjects/mcp-google-ads && python -m unittest tests.test_entrypoint -v
```

Expected: `AttributeError: module 'entrypoint' has no attribute 'BearerAuthMiddleware'` for all 4 new tests; the 3 previous tests still pass.

- [ ] **Step 3: Add `BearerAuthMiddleware` to `entrypoint.py`**

Add these imports near the top of `entrypoint.py` (after `import tempfile`):

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
```

Then append this class (below `materialize_credentials`):

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
cd C:/Users/Razvan/PycharmProjects/mcp-google-ads && python -m unittest tests.test_entrypoint -v
```

Expected: 7 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add entrypoint.py tests/test_entrypoint.py
git commit -m "feat: add BearerAuthMiddleware for entrypoint.py"
```

---

## Task 4: Wire up `build_app()` and `main()`

**Files:**
- Modify: `entrypoint.py`

No unit tests for this task — `build_app()` imports `google_ads_server` (which reads live env vars and loads the full Google Ads module), and `main()` starts uvicorn. Both are integration-tested via the Docker smoke test in Task 6.

- [ ] **Step 1: Append `build_app()` and `main()` to `entrypoint.py`**

Add below `BearerAuthMiddleware`:

```python
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
```

- [ ] **Step 2: Re-run unit tests to confirm nothing broke**

Run:
```bash
cd C:/Users/Razvan/PycharmProjects/mcp-google-ads && python -m unittest tests.test_entrypoint -v
```

Expected: 7 tests, all PASS. (The new `build_app` / `main` code is not imported by the tests because they only touch `materialize_credentials` and `BearerAuthMiddleware`.)

- [ ] **Step 3: Commit**

```bash
git add entrypoint.py
git commit -m "feat: add build_app and main wiring to entrypoint.py"
```

---

## Task 5: Create the `Dockerfile`

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install upstream deps first (cached across code-only changes)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Pin modern MCP SDK (streamable-http) + ASGI stack separately so upstream
# requirements.txt bumps don't invalidate this layer
RUN pip install "mcp>=1.10" uvicorn starlette

# Application code (respects .dockerignore)
COPY . .

EXPOSE 8080

CMD ["python", "/app/entrypoint.py"]
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat: add Dockerfile for Dokploy deployment"
```

---

## Task 6: Docker build + integration smoke test

**Files:**
- None to modify; this is verification-only.

- [ ] **Step 1: Build the image**

Run:
```bash
cd C:/Users/Razvan/PycharmProjects/mcp-google-ads && docker build -t gads-mcp:test .
```

Expected: Build succeeds. Final image size should be roughly 200–300 MB. If the build fails on `pip install -r requirements.txt` due to upstream dep issues, investigate before proceeding — do NOT patch `requirements.txt` (that would break the "no upstream edits" invariant). Report the error and ask before changing approach.

- [ ] **Step 2: Smoke test 1 — missing MCP_AUTH_TOKEN exits cleanly**

Run:
```bash
docker run --rm -e GOOGLE_ADS_CREDENTIALS_JSON='{}' -e GOOGLE_ADS_DEVELOPER_TOKEN=x -e GOOGLE_ADS_LOGIN_CUSTOMER_ID=0 gads-mcp:test 2>&1 | head -5
```

Expected: output contains `ERROR: MCP_AUTH_TOKEN is required` and the container exits with non-zero status.

- [ ] **Step 3: Smoke test 2 — start the container with valid env vars**

Run:
```bash
docker run -d --name gads-mcp-smoke \
  -e MCP_AUTH_TOKEN=smoke-test-token \
  -e GOOGLE_ADS_CREDENTIALS_JSON='{"type":"service_account","client_email":"x@y","private_key":"-----BEGIN PRIVATE KEY-----\n-----END PRIVATE KEY-----\n","token_uri":"https://oauth2.googleapis.com/token"}' \
  -e GOOGLE_ADS_DEVELOPER_TOKEN=fake-dev-token \
  -e GOOGLE_ADS_LOGIN_CUSTOMER_ID=1234567890 \
  -e GOOGLE_ADS_AUTH_TYPE=service_account \
  -e MCP_ALLOWED_HOST=localhost \
  -p 18080:8080 \
  gads-mcp:test
```

Wait ~3 seconds for uvicorn to come up, then:

```bash
docker logs gads-mcp-smoke 2>&1 | tail -20
```

Expected: log lines like `Uvicorn running on http://0.0.0.0:8080` and `StreamableHTTP session manager started`. No traceback.

Note: `MCP_ALLOWED_HOST=localhost` is set for the smoke test so the DNS-rebinding check accepts `Host: localhost:18080` from curl. Production uses the default (`gads.lucramresponsabil.com`).

- [ ] **Step 4: Smoke test 3 — `curl` without auth returns 401**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:18080/mcp
```

Expected: `401`.

- [ ] **Step 5: Smoke test 4 — wrong bearer token returns 401**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Authorization: Bearer wrong" \
  http://localhost:18080/mcp
```

Expected: `401`.

- [ ] **Step 6: Smoke test 5 — correct bearer token passes auth and the MCP handshake succeeds**

Run:
```bash
curl -s -o /tmp/mcp-resp.txt -w "%{http_code}\n" -X POST \
  -H "Authorization: Bearer smoke-test-token" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  http://localhost:18080/mcp
cat /tmp/mcp-resp.txt
```

Expected: HTTP `200` and the response body contains an MCP `initialize` result with `serverInfo` naming `google-ads-server`. This proves auth middleware passed, DNS-rebinding check passed (`Host: localhost:18080` is in the allowlist), and FastMCP's session manager handled the request.

If this returns `421` instead of `200`, the allowed_hosts config is wrong — investigate before proceeding.

- [ ] **Step 7: Tear down smoke container**

Run:
```bash
docker rm -f gads-mcp-smoke
```

Expected: `gads-mcp-smoke`.

- [ ] **Step 8: No commit for this task**

This task is verification only; no files were changed.

---

## Task 7: Push to fork

**Files:**
- None; ship step.

- [ ] **Step 1: Review the full diff that will be pushed**

Run:
```bash
cd C:/Users/Razvan/PycharmProjects/mcp-google-ads && git log --oneline origin/main..HEAD
```

Expected: 5–6 commits from Tasks 1–5 plus the two doc/spec commits from the brainstorming phase.

- [ ] **Step 2: Push to the fork**

Run:
```bash
git push origin main
```

Expected: Push succeeds. Dokploy auto-deploy (if wired) will pick it up; otherwise trigger the deploy manually.

---

## Out of scope — do in Dokploy UI after push

These are manual VPS-side steps, not code changes. Do them once after the first successful push:

1. **Create the application** in Dokploy, pointing at the `CebRazvan/mcp-google-ads` fork, branch `main`, build type `Dockerfile`.
2. **Set environment variables** in the Dokploy UI:
    - `MCP_AUTH_TOKEN` — generate with `openssl rand -hex 32`
    - `GOOGLE_ADS_CREDENTIALS_JSON` — paste the full service-account or OAuth JSON
    - `GOOGLE_ADS_DEVELOPER_TOKEN`
    - `GOOGLE_ADS_LOGIN_CUSTOMER_ID`
    - `GOOGLE_ADS_AUTH_TYPE` (`service_account` or `oauth`)
    - Leave `MCP_ALLOWED_HOST` and `PORT` unset — defaults are correct.
3. **Set the domain** to `gads.lucramresponsabil.com`, internal port `8080`, enable HTTPS with `letsencrypt`, enable HTTP→HTTPS redirect. Dokploy will generate the Traefik labels automatically.
4. **Deploy** and watch the logs for `Uvicorn running on http://0.0.0.0:8080`.
5. **Verify from the outside:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://gads.lucramresponsabil.com/mcp -X POST
# Expected: 401

curl -s -X POST https://gads.lucramresponsabil.com/mcp \
  -H "Authorization: Bearer <MCP_AUTH_TOKEN>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"prod-check","version":"0"}}}'
# Expected: 200 with serverInfo.name = "google-ads-server"
```

6. **Connect Claude** to the remote MCP server at `https://gads.lucramresponsabil.com/mcp` with the bearer token from step 2.

If step 5 returns `421 Misdirected Request`, DNS rebinding protection is rejecting the Host header. Verify `MCP_ALLOWED_HOST` matches the exact hostname Traefik forwards (it should default to `gads.lucramresponsabil.com`, which matches the domain).
