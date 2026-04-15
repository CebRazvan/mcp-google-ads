# In-process OAuth 2.0 Authorization Server for the Google Ads MCP

**Status:** Approved
**Date:** 2026-04-15
**Target:** https://gads.lucramresponsabil.com/mcp
**Deployment:** Dokploy + Traefik (same VPS, same container image shape as the existing Dockerize deployment)

## Goal

Replace the static-bearer-token auth on the Google Ads MCP with a full OAuth 2.0 Authorization Server (AS) flow, so that Claude.ai web's "Add custom connector" dialog can connect successfully. The server becomes both an Authorization Server and a Resource Server for itself, using FastMCP's built-in auth machinery plus a small in-process provider backed by an in-memory store and a minimal HTML login form.

## Non-goals

- Multi-user support. Single admin account, credentials from env vars.
- Persistent OAuth state. Everything in memory; container restart = user re-logs in.
- External IdP integration (Google, GitHub, Cloudflare Access). Considered and rejected in favor of a self-contained implementation.
- Account lockout, brute-force rate limiting, password reset. Traefik rate-limit middleware handles the network layer if needed; password rotation is an env-var edit.
- Administrative UI for managing clients or tokens.
- Scope-based authorization. All authenticated requests get access to the full tool set.

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Authentication strategy | Internal HTML login form, env-var credentials | Zero external deps; fits "personal MCP on private VPS" shape; no third-party failure surface |
| Persistence | In-memory only | Single-user; redeploys are rare; drop-in SQLite is a later concern |
| FastMCP integration | In-process Authorization Server mode via `OAuthAuthorizationServerProvider` protocol | The SDK auto-wires `/authorize`, `/token`, `/register`, `/revoke`, and `/.well-known/oauth-authorization-server` when the provider is set |
| Dynamic client registration | Enabled, no gating | Claude.ai uses DCR to avoid pre-registered client credentials |
| Refresh token rotation | Enabled | OAuth Security BCP §4.12 recommendation; MCP SDK docstring mandates it |
| Access token TTL | 1 hour | Standard; bounded damage if leaked |
| Refresh token TTL | 30 days | Keeps Claude's long-running connection working across daily use |
| Auth code TTL | 60 seconds | RFC 6749 §4.1.2 best practice |
| Login session TTL | 5 minutes | Long enough to finish a login screen, short enough to self-clean |
| CSRF protection | Double-submit cookie | Stateless, standard, no session storage on the server beyond the pending login |
| Password comparison | `hmac.compare_digest` for all credential checks | Constant-time; avoids the timing-attack concern that came up on the bearer-token middleware |
| HTML templates | Inline strings in `oauth/templates.py` | No Jinja/Django dependency for one login form and one error page |
| Code organization | New `oauth/` package with 4 small files | Each file has one responsibility; easier reasoning than one 600-line module |
| `BearerAuthMiddleware` | Removed | FastMCP's built-in `RequireAuthMiddleware` takes over validation via `provider.load_access_token` |
| `MCP_AUTH_TOKEN` env var | Removed | Bearer flow is gone |

## Scope

One implementation plan, one feature branch, one Dokploy deploy. The design covers:

- A new `oauth/` package (4 files + `__init__.py`)
- Modifications to `entrypoint.py` (delete `BearerAuthMiddleware`, wire OAuth)
- New `tests/test_oauth.py` (unit + integration)
- Modifications to `tests/test_entrypoint.py` (remove `BearerAuthMiddlewareTests`)
- New env vars in Dokploy: `MCP_ADMIN_USER`, `MCP_ADMIN_PASSWORD`
- No Dockerfile, `.dockerignore`, `requirements.txt`, or `google_ads_server.py` changes

## Data flow

```
Claude.ai                                               MCP server (our container)
─────────                                               ──────────────────────────
1. POST /mcp (no auth)                          ───▶    FastMCP
   ◀─── 401 + WWW-Authenticate: Bearer                  └─ resource metadata URL
          resource_metadata="…/.well-known/…"

2. GET  /.well-known/oauth-protected-resource   ───▶    FastMCP auto-route
   ◀─── { "authorization_servers": [<issuer>] }

3. GET  /.well-known/oauth-authorization-server ───▶    FastMCP MetadataHandler
   ◀─── { authorization_endpoint,
          token_endpoint,
          registration_endpoint, … }

4. POST /register  (Dynamic Client Registration) ───▶   FastMCP RegistrationHandler
   ◀─── { client_id, client_secret }                    └─ provider.register_client

5. Browser → GET /authorize?client_id=…         ───▶    FastMCP AuthorizationHandler
                                                         └─ provider.authorize
                                                            returns /oauth/login?session=…
   ◀─── 302 Location: /oauth/login?session=XYZ

6. Browser → GET /oauth/login?session=XYZ       ───▶    oauth.login.get_login
   ◀─── 200 HTML login form (+CSRF cookie)

7. User submits → POST /oauth/login             ───▶    oauth.login.post_login
                                                         └─ verify CSRF + credentials
                                                         └─ create AuthorizationCode
   ◀─── 302 Location: <Claude redirect_uri>?code=…&state=…

8. Claude → POST /token                         ───▶    FastMCP TokenHandler
             grant_type=authorization_code               └─ provider.exchange_auth_code
   ◀─── { access_token, refresh_token, expires_in }

9. Claude → POST /mcp                           ───▶    FastMCP RequireAuthMiddleware
             Authorization: Bearer <access>             └─ provider.load_access_token
   ◀─── 200 + MCP protocol response                     └─ google-ads-server tool handlers

10. Later: Claude → POST /token                 ───▶    FastMCP TokenHandler
              grant_type=refresh_token                   └─ provider.exchange_refresh_token
    ◀─── { new access_token, new refresh_token }        (old refresh token invalidated)
```

Steps 1–4 happen once per Claude connector setup. Step 5–7 is the user-visible login screen — shown once per Claude session (refresh tokens are long-lived). Steps 8–9 repeat on every MCP request. Step 10 happens roughly once per hour.

## File structure

```
mcp-google-ads/
├── entrypoint.py          ← MODIFY (remove BearerAuthMiddleware, wire OAuth)
├── oauth/                 ← NEW package
│   ├── __init__.py        ← re-exports InMemoryOAuthProvider, build_login_routes
│   ├── storage.py         ← InMemoryStore + PendingLogin dataclass
│   ├── provider.py        ← InMemoryOAuthProvider
│   ├── login.py           ← GET/POST /oauth/login routes
│   └── templates.py       ← HTML_LOGIN_FORM + HTML_ERROR (inline)
├── tests/
│   ├── test_entrypoint.py  ← MODIFY (remove BearerAuthMiddlewareTests)
│   └── test_oauth.py       ← NEW — unit + integration tests
├── Dockerfile             ← NO CHANGE
├── .dockerignore          ← NO CHANGE
└── requirements.txt       ← NO CHANGE (no new runtime deps)
```

Design notes:
- Four small files in `oauth/`, one responsibility each. Storage knows dicts and TTLs. Provider knows OAuth protocol. Login knows HTTP forms and sessions. Templates are HTML strings.
- No Jinja / template engine dependency. Two inline HTML strings.
- `.dockerignore` already excludes `tests/` → unit tests don't ship in the image.
- `starlette` is already installed; `itsdangerous` (for cookie signing, if needed) comes with Starlette.

## Component designs

### `oauth/storage.py` — in-memory store

`InMemoryStore` holds five dicts, each with a TTL, keyed by string IDs. Eviction is lazy on read — no background task. All operations go through a single `asyncio.Lock` for async safety (single lock, no deadlock risk).

Buckets:
- `_clients` — dynamically-registered OAuth clients (TTL=0, live until container restart)
- `_login_sessions` — pending login flows (5-minute TTL)
- `_auth_codes` — single-use authorization codes (60-second TTL)
- `_access_tokens` — bearer tokens (1-hour TTL)
- `_refresh_tokens` — refresh tokens (30-day TTL)

Supporting dataclass `PendingLogin`:
- `session_id: str`
- `client_id: str`
- `redirect_uri: str`
- `code_challenge: str` — PKCE; captured from `AuthorizationParams`, passed through to `AuthorizationCode`
- `scopes: list[str]`
- `state: str | None` — round-tripped back to Claude on the final redirect
- `created_at: float`

Uses `time.monotonic()` not `time.time()` — immune to wall-clock jumps.

### `oauth/provider.py` — OAuth Authorization Server

`InMemoryOAuthProvider` implements `mcp.server.auth.provider.OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]`. Each method is 5–20 lines and delegates state to `InMemoryStore`.

Methods (all required by the protocol):

| Method | Responsibility |
|---|---|
| `get_client(client_id)` | Look up a DCR-registered client |
| `register_client(client_info)` | Accept any client metadata, store it |
| `authorize(client, params)` | Create a `PendingLogin`, return `/oauth/login?session=…` URL |
| `load_authorization_code(client, code)` | Return the code if valid and owned by the client |
| `exchange_authorization_code(client, code)` | Delete the code (single-use), issue an access+refresh pair |
| `load_refresh_token(client, token)` | Return the refresh token if valid and owned |
| `exchange_refresh_token(client, token, scopes)` | Rotate: delete old refresh, issue new pair |
| `load_access_token(token)` | Called by `RequireAuthMiddleware` on every MCP request |
| `revoke_token(token)` | Delete from the appropriate bucket |

Internal helper `_issue_token_pair(client, scopes)` is called by both `exchange_authorization_code` and `exchange_refresh_token`. It generates `secrets.token_urlsafe(32)` for each token, records them, and returns an `OAuthToken` with `token_type="bearer"`.

PKCE note — see "Compatibility checks" below.

### `oauth/login.py` — login form

Two Starlette routes built by a factory `build_login_routes(provider)`. The factory reads `MCP_ADMIN_USER` and `MCP_ADMIN_PASSWORD` from the environment at startup (fail-fast via `os.environ[...]` which raises `KeyError` if unset).

**`GET /oauth/login?session=<id>`:**
- Look up the pending session. Unknown / expired → HTML 400 with "start over from Claude".
- Generate a fresh `secrets.token_urlsafe(32)` as the CSRF token.
- Render `HTML_LOGIN_FORM` with the CSRF token in a hidden field.
- Set the CSRF token as an HTTP-only, `Secure`, `SameSite=Lax` cookie with a 10-minute max-age.

**`POST /oauth/login`:**
- Parse form fields: `session`, `csrf`, `username`, `password`.
- Compare `csrf` form field to the `oauth_csrf` cookie via `hmac.compare_digest`. Mismatch → 400.
- Look up pending session. Unknown / expired → 400.
- Compare `username` and `password` to env-var values via `hmac.compare_digest`. Failure → re-render the form with a fresh CSRF and an error message, HTTP 401. **Pending session is NOT consumed on failure** — the user can retry in the same flow.
- On success: delete the pending session (consumed), generate an `AuthorizationCode` with the PKCE `code_challenge` from the session, store it, and 302-redirect to the Claude `redirect_uri` with `code=` and `state=` query params (via `construct_redirect_uri` from the MCP SDK).

CSRF uses double-submit cookie: cookie + hidden form field must match. Standard, stateless, no extra session storage.

All secrets-comparison operations use `hmac.compare_digest` for constant-time behavior.

### `oauth/templates.py` — inline HTML

Two strings:

- `HTML_LOGIN_FORM` — dark-theme login page with a card, username + password inputs, a hidden `session` field, a hidden `csrf` field, and a submit button. Inline `<style>`, no JS, no external CSS. Substituted fields: `{session}`, `{csrf}`, `{error}`. All three are server-generated; no user input is interpolated.
- `HTML_ERROR` — minimal error page for the "session expired" / "CSRF failed" cases. One substituted field `{message}` which is always a constant string from our own code.

No HTML-escaping risk: none of the interpolated values come from user input.

### `entrypoint.py` modifications

Delete `BearerAuthMiddleware` entirely. Replace the `build_app()` body with an OAuth-wired version.

New `build_app()`:
1. Compute `issuer_url = f"https://{allowed_host}"` (where `allowed_host` defaults to `gads.lucramresponsabil.com`, overridable via `MCP_ALLOWED_HOST`).
2. Configure `mcp.settings.host`, `mcp.settings.port`, `mcp.settings.transport_security` (same as today).
3. Create `store = InMemoryStore()` and `provider = InMemoryOAuthProvider(store, issuer_url=issuer_url)`.
4. Set `mcp.settings.auth = AuthSettings(issuer_url=issuer_url, resource_server_url=issuer_url, client_registration_options=ClientRegistrationOptions(enabled=True), revocation_options=RevocationOptions(enabled=True), required_scopes=None)`.
5. Set `mcp._auth_server_provider = provider` and `mcp._token_verifier = provider` (same object plays both roles). **See "Compatibility checks" below.**
6. Append login routes to `mcp._custom_starlette_routes`. **See "Compatibility checks" below.**
7. Return `mcp.streamable_http_app()`.

New `main()`:
- Before `materialize_credentials()`: guard on `MCP_ADMIN_USER` and `MCP_ADMIN_PASSWORD` being set. Exit 1 with a clear stderr message if either is missing.
- Delete the `MCP_AUTH_TOKEN` guard.
- Everything else unchanged.

## Compatibility checks (must verify during implementation, not speculative)

Three items depend on the installed mcp SDK's internal API. Each must be verified against the actual installed version at Task 1 of the implementation plan, and resolved in place if the assumption is wrong:

1. **`mcp._auth_server_provider` / `mcp._token_verifier`.** FastMCP's `streamable_http_app()` reads these attributes (confirmed via SDK source dump during brainstorming). They are "private" by Python convention. **Check:** does FastMCP expose a public setter in the installed version? If yes, use it. If no, document the private-attribute dependency in a comment and pin the exact mcp version in the Dockerfile.

2. **`mcp._custom_starlette_routes`.** Same situation — FastMCP extends Starlette with these routes during `streamable_http_app()` construction. **Check:** does a public decorator (`@mcp.custom_route(...)`) or method (`mcp.add_route(...)`) exist? If yes, use it instead.

3. **PKCE `code_challenge` verification.** `AuthorizationCode.code_challenge` is captured and persisted by our provider. **Check:** does FastMCP's `TokenHandler` call a `verify_code_challenge` step automatically during `/token` exchange? Read the SDK source for `TokenHandler.handle`. If yes, no extra work. If no, add explicit PKCE verification in `exchange_authorization_code` (compare the Claude-provided `code_verifier` against the stored `code_challenge` using SHA-256 per RFC 7636 §4.6).

4. **`/oauth/login` path allowlisted from `RequireAuthMiddleware`.** FastMCP's auth middleware must only gate `/mcp`, not arbitrary custom routes, or the login page can't render (it would require auth to log in). **Check:** read `streamable_http_app()` source to confirm the middleware is scoped to the MCP route only. If it's applied globally, we need to either wrap the Starlette routes separately or add a path exemption.

None of these are speculative. They are real compatibility details that will be resolved during the first implementation task, exactly like the `custom_middleware` / `host/port` checks that were resolved during the previous Dockerize plan.

## Environment variables

### New (required)

| Variable | Description | Generate with |
|---|---|---|
| `MCP_ADMIN_USER` | Username for the login form | any non-empty string |
| `MCP_ADMIN_PASSWORD` | Password for the login form | `openssl rand -base64 24` |

### Removed

| Variable | Reason |
|---|---|
| `MCP_AUTH_TOKEN` | Bearer-token auth path is deleted. |

### Unchanged

| Variable | Required | Notes |
|---|---|---|
| `GOOGLE_ADS_CREDENTIALS_JSON` | yes | Same as today |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | yes | Same as today |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | yes | Same as today |
| `GOOGLE_ADS_AUTH_TYPE` | yes | `oauth` or `service_account` |
| `MCP_ALLOWED_HOST` | no (default) | Used to compute `issuer_url` now in addition to the rebinding allowlist |
| `PORT` | no (default) | Defaults to 8080 |

## Error handling

What can go wrong and the response:

- **Login session expired** → HTML 400 with "Start over from Claude".
- **CSRF mismatch** → HTML 400.
- **Invalid credentials** → form re-rendered with error, HTTP 401, session preserved.
- **Auth code reuse** → FastMCP's `TokenHandler` returns `invalid_grant` on the second call; we enforce single-use by deleting the code in `exchange_authorization_code`.
- **Refresh token reuse after rotation** → same mechanism: old token deleted on first use, second use fails.
- **Expired access token** → `RequireAuthMiddleware` returns 401 with `WWW-Authenticate: Bearer resource_metadata="…"`; Claude uses its refresh token and retries. Transparent.
- **Missing `MCP_ADMIN_*` at startup** → process exits 1 with stderr message. Same pattern as the current `MCP_AUTH_TOKEN` guard.
- **DNS rebinding block (Host header not in allowlist)** → FastMCP returns 421 before our code runs. Unchanged from today.

What we deliberately don't handle:
- Login form rate limiting. Single-user; handled at Traefik if it ever matters.
- Password reset / account lockout. Rotate by editing the Dokploy env var.
- Multi-user concurrent logins. Single-user design.

## Logging

Minimal, useful, no secrets.

- **Login success:** `logger.info("OAuth login: user=%s client=%s session=%s…", username, client_id, session_id[:8])` — session id is prefix-only.
- **Login failure:** `logger.warning("OAuth login failed: user=%s client=%s reason=%s", username, client_id, "bad_password" | "csrf" | "expired_session")`.
- **Token issued:** `logger.info("OAuth token issued: client=%s grant=%s", client_id, "authorization_code" | "refresh_token")`.
- **Token revoked:** `logger.info("OAuth token revoked: client=%s", client_id)`.

Never logged: raw passwords, raw tokens, auth codes. Identifiers are truncated to 8-char prefixes when they must appear.

A new `oauth` logger at INFO level. Output goes to stdout and is visible in Dokploy's log panel, same as the existing `google_ads_server` logger.

## Testing strategy

### Layer 1: unit tests (`tests/test_oauth.py`)

Using stdlib `unittest`; no new dev dependencies.

**`InMemoryStoreTests`:**
- Store and retrieve by key (happy path for each bucket)
- TTL eviction — use a short TTL (e.g., 0.1 s) and `asyncio.sleep`, or monkey-patch `time.monotonic` via `unittest.mock.patch`
- Delete is idempotent
- Expired entries are removed lazily on read
- The same lock instance is used (no accidental per-bucket locks)

**`InMemoryOAuthProviderTests`:**
- `register_client` → `get_client` round-trip
- `authorize()` returns a URL of the form `<issuer>/oauth/login?session=<random>`
- `exchange_authorization_code` once → succeeds; a second call with the same code → raises / returns None
- `exchange_refresh_token` rotates: old refresh token becomes invalid after use
- `load_access_token` returns None for expired tokens
- `revoke_token` removes from storage (both access and refresh variants)

**`LoginRoutesTests`** — Starlette `TestClient`:
- `GET /oauth/login?session=<valid>` → 200 + HTML contains a CSRF hidden field and the `session` value
- `GET /oauth/login?session=<unknown>` → 400 + HTML_ERROR
- `POST /oauth/login` with correct credentials, correct CSRF → 302 to `redirect_uri` with `code=` and `state=` query params
- `POST /oauth/login` with wrong password → 401 + form re-rendered
- `POST /oauth/login` with CSRF mismatch → 400
- `POST /oauth/login` twice with the same session → first succeeds, second → 400 (session consumed)

### Layer 2: integration test (`tests/test_oauth.py::EndToEndFlowTests`)

Drives the entire OAuth dance against a real FastMCP app with the provider wired. One test method per end-to-end path:

**`test_full_authorization_code_flow`:**
1. `POST /mcp` with no auth → 401 + `WWW-Authenticate` header present
2. `GET /.well-known/oauth-protected-resource` → 200
3. `GET /.well-known/oauth-authorization-server` → 200 + metadata contains `authorization_endpoint`, `token_endpoint`, `registration_endpoint`
4. `POST /register` with minimal client body → 201 + `client_id`
5. `GET /authorize?client_id=…&redirect_uri=…&code_challenge=…&state=…` → 302 to `/oauth/login?session=…`
6. `GET /oauth/login?session=…` → 200 + form
7. `POST /oauth/login` with correct creds → 302 with `code=…&state=…`
8. `POST /token` (grant_type=authorization_code) → 200 + access+refresh tokens
9. `POST /mcp` with the access token → 200 (MCP handshake result)

**`test_refresh_token_rotation`:**
Builds on `test_full_authorization_code_flow` state. After getting tokens:
10. `POST /token` (grant_type=refresh_token) → 200 + new pair, both different from the originals
11. `POST /mcp` with the old access token → 401 (rotated out)
12. `POST /mcp` with the new access token → 200

**`test_auth_code_is_single_use`:**
After step 8 (first token exchange), replay the exact same `POST /token` → 400 / `invalid_grant`.

If the integration test passes, Claude.ai will almost certainly work in production.

### Layer 3: Docker smoke tests

Same shape as the previous Dockerize deployment's smoke tests, on the built image:

1. Build succeeds
2. Missing `MCP_ADMIN_PASSWORD` → container exits 1 with a clear error
3. Container starts, uvicorn listening on `0.0.0.0:8080`
4. `curl -v POST /mcp` with no auth → 401 + `WWW-Authenticate` header containing `resource_metadata`
5. `curl GET /.well-known/oauth-protected-resource` → 200
6. `curl GET /.well-known/oauth-authorization-server` → 200
7. `curl GET /oauth/login?session=fake` → 400 (session not found — proves the route is wired and the HTML/CSRF pipeline works)
8. `curl -X POST /register -H "Content-Type: application/json" -d '{"redirect_uris":["https://claude.ai/cb"]}'` → 201 + JSON with `client_id`

The smoke test does NOT drive the full login → token flow. That's unit/integration territory.

### Out of scope

- **Claude.ai actually connecting.** Manual verification after deploy, documented in the plan.
- **Race tests for concurrent logins.** Single-user; async-lock is enough.
- **Testing FastMCP's own handlers.** We trust upstream; we test our provider under them.

## Rollback plan

If the deploy breaks: Dokploy keeps previous image tags; roll back to the last known-good image (the Dockerize branch merge commit `c034518`). Source-level rollback is `git revert` on the merge commit once it lands on main.

If the OAuth provider breaks but the container still serves MCP over the previous bearer-token path... it doesn't, because the bearer middleware is deleted in the same branch. Rollback is mandatory for any OAuth bug that prevents login. Plan for it: keep the previous image tag available in Dokploy's image history and have the rollback URL handy during first deploy.

## Deployment steps after merge

1. Add `MCP_ADMIN_USER` and `MCP_ADMIN_PASSWORD` to Dokploy environment variables.
2. Remove `MCP_AUTH_TOKEN` from Dokploy environment variables.
3. Trigger the deploy (or let auto-deploy run on the main-branch push).
4. Watch logs for `Uvicorn running on http://0.0.0.0:8080`.
5. From Claude.ai → Add custom connector → URL `https://gads.lucramresponsabil.com/mcp` → Add. Claude will 401-discover, hit the login form, prompt for credentials.
6. Sign in with the Dokploy-configured user/password.
7. Verify the connector shows as connected and list the Google Ads tools.
