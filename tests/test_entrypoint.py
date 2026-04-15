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


if __name__ == "__main__":
    unittest.main()
