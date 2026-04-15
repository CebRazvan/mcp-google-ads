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
