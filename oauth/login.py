"""Login form routes for the in-process OAuth Authorization Server.

Exposes two functions:

- handle_get_login / handle_post_login: plain async Starlette handlers. They take
  the HTTP request, a provider instance, admin_user and admin_password. These
  are unit-testable without any FastMCP instance.
- build_login_route_list(provider): returns a list of Starlette Route objects,
  for mounting on a bare Starlette app in unit tests.
- register_login_routes(mcp_instance, provider): registers the routes on a
  FastMCP instance via the public @mcp.custom_route decorator. Used by
  entrypoint.py in production.
"""
import hmac
import os
import secrets
import time

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp.server.auth.provider import AuthorizationCode, construct_redirect_uri

from .provider import InMemoryOAuthProvider, AUTH_CODE_TTL
from .templates import HTML_LOGIN_FORM, HTML_ERROR


CSRF_COOKIE_NAME = "oauth_csrf"
CSRF_TTL_SECONDS = 10 * 60


async def handle_get_login(request: Request,
                           provider: InMemoryOAuthProvider) -> Response:
    session_id = request.query_params.get("session", "")
    pending = await provider.store.get_login_session(session_id)
    if pending is None:
        return HTMLResponse(
            HTML_ERROR.format(message="Login session expired. Start over from Claude."),
            status_code=400,
        )
    csrf = secrets.token_urlsafe(32)
    resp = HTMLResponse(HTML_LOGIN_FORM.format(
        session=session_id, csrf=csrf, error="",
    ))
    resp.set_cookie(
        CSRF_COOKIE_NAME, csrf,
        max_age=CSRF_TTL_SECONDS, httponly=True, secure=True, samesite="lax",
    )
    return resp


async def handle_post_login(request: Request,
                            provider: InMemoryOAuthProvider,
                            admin_user: str,
                            admin_password: str) -> Response:
    form = await request.form()
    session_id = form.get("session", "")
    csrf_form = form.get("csrf", "")
    username = form.get("username", "")
    password = form.get("password", "")

    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    if not csrf_cookie or not hmac.compare_digest(csrf_form, csrf_cookie):
        return HTMLResponse(
            HTML_ERROR.format(message="CSRF check failed. Reload and try again."),
            status_code=400,
        )

    pending = await provider.store.get_login_session(session_id)
    if pending is None:
        return HTMLResponse(
            HTML_ERROR.format(message="Login session expired."),
            status_code=400,
        )

    user_ok = hmac.compare_digest(username, admin_user)
    pass_ok = hmac.compare_digest(password, admin_password)
    if not (user_ok and pass_ok):
        csrf = secrets.token_urlsafe(32)
        resp = HTMLResponse(HTML_LOGIN_FORM.format(
            session=session_id, csrf=csrf, error="Invalid credentials.",
        ), status_code=401)
        resp.set_cookie(
            CSRF_COOKIE_NAME, csrf,
            max_age=CSRF_TTL_SECONDS, httponly=True, secure=True, samesite="lax",
        )
        return resp

    # Credentials OK: consume the login session, issue an authorization code.
    await provider.store.delete_login_session(session_id)

    code_value = secrets.token_urlsafe(32)
    code = AuthorizationCode(
        code=code_value,
        scopes=pending.scopes,
        expires_at=int(time.time()) + AUTH_CODE_TTL,
        client_id=pending.client_id,
        code_challenge=pending.code_challenge,
        redirect_uri=pending.redirect_uri,
        redirect_uri_provided_explicitly=True,
    )
    await provider.store.put_auth_code(code_value, code, AUTH_CODE_TTL)

    return RedirectResponse(
        url=construct_redirect_uri(
            pending.redirect_uri,
            code=code_value,
            state=pending.state,
        ),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


def _get_admin_credentials() -> tuple[str, str]:
    return os.environ["MCP_ADMIN_USER"], os.environ["MCP_ADMIN_PASSWORD"]


def build_login_route_list(provider: InMemoryOAuthProvider) -> list[Route]:
    """For unit tests — mount these on a bare Starlette app via `Starlette(routes=...)`."""
    admin_user, admin_password = _get_admin_credentials()

    async def get_route(request: Request) -> Response:
        return await handle_get_login(request, provider)

    async def post_route(request: Request) -> Response:
        return await handle_post_login(request, provider, admin_user, admin_password)

    return [
        Route("/oauth/login", endpoint=get_route, methods=["GET"]),
        Route("/oauth/login", endpoint=post_route, methods=["POST"]),
    ]


def register_login_routes(mcp_instance, provider: InMemoryOAuthProvider) -> None:
    """For production — registers routes on a FastMCP instance via the public
    @mcp.custom_route decorator. custom_route automatically exempts routes
    from auth, which is exactly what we need for the login form."""
    admin_user, admin_password = _get_admin_credentials()

    @mcp_instance.custom_route("/oauth/login", methods=["GET"])
    async def get_login_route(request: Request) -> Response:
        return await handle_get_login(request, provider)

    @mcp_instance.custom_route("/oauth/login", methods=["POST"])
    async def post_login_route(request: Request) -> Response:
        return await handle_post_login(request, provider, admin_user, admin_password)
