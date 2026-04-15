"""In-process OAuth 2.0 Authorization Server for the Google Ads MCP.

Public API:
- InMemoryStore: backing store for clients, sessions, codes, tokens
- InMemoryOAuthProvider: OAuth provider + TokenVerifier
- register_login_routes: mount the login form on a FastMCP instance
"""
from .storage import InMemoryStore, PendingLogin
from .provider import InMemoryOAuthProvider
from .login import register_login_routes, build_login_route_list

__all__ = [
    "InMemoryStore",
    "PendingLogin",
    "InMemoryOAuthProvider",
    "register_login_routes",
    "build_login_route_list",
]
