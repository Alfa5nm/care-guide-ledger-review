import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, main, security
from app.worker import process_next


class HostedTests(unittest.TestCase):
    def setUp(self):
        sandbox = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(db, "ROOT", Path(sandbox)))
        self.enterContext(patch.object(main, "HOSTED", True))
        self.enterContext(patch.object(main, "HOST", "testserver"))
        self.enterContext(patch.object(security, "PASSWORD", "synthetic-test-credential-1234"))
        self.client = self.enterContext(TestClient(main.app, base_url="https://testserver"))
        self.auth = ("reviewer", security.PASSWORD)

    def test_only_readiness_is_anonymous(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        for path in ("/", "/docs", "/openapi.json", "/api/documents", "/api/search?q=invoice",
                     "/api/exports", "/api/exports/missing/csv"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn("Basic", response.headers["WWW-Authenticate"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/api/documents", auth=("reviewer", "incorrect")).status_code, 401)
        response = self.client.get("/docs", auth=self.auth)
        self.assertEqual(401, self.client.post("/api/exports", json={}).status_code)
        self.assertEqual(response.status_code, 200)
        self.assertIn("default-src", response.headers["Content-Security-Policy"])
        self.assertIn("max-age", response.headers["Strict-Transport-Security"])

    def test_cross_origin_write_and_request_bound(self):
        response = self.client.patch("/api/invoices/1", auth=self.auth,
                                     headers={"Origin": "https://example.invalid"}, json={})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/exports", auth=self.auth,
                                    headers={"Origin": "https://example.invalid"}, json={})
        self.assertEqual(response.status_code, 403)
        response = self.client.patch("/api/invoices/1", auth=self.auth,
                                     headers={"Content-Length": "999999999"}, json={})
        self.assertEqual(response.status_code, 413)

    def test_quota_and_retry_bound_with_invalid_synthetic_file(self):
        with patch.object(main, "MAX_WORKSPACE_DOCUMENTS", 1):
            response = self.client.post("/api/documents", auth=self.auth, files=[
                ("files", ("invalid.pdf", b"synthetic invalid document")),
                ("files", ("extra.pdf", b"another synthetic document")),
            ])
        first, second = response.json()["files"]
        self.assertIn("quota", second["error"])
        document = "/api/documents/" + first["id"]
        for attempt in range(1, 4):
            self.assertTrue(process_next())
            result = self.client.get(document, auth=self.auth).json()
            self.assertEqual((result["status"], result["attempt"]), ("failed", attempt))
            self.assertEqual(result["can_retry"], attempt < 3)
            retry = self.client.post(document + "/retry", auth=self.auth)
            self.assertEqual(retry.status_code, 202 if attempt < 3 else 409)
        self.assertEqual(len(list((db.ROOT / "uploads").iterdir())), 1)

    def test_hosted_configuration_requires_password_and_disables_model(self):
        with patch.object(security, "HOSTED", True), patch.object(security, "HOST", "testserver"):
            with patch.object(security, "PASSWORD", ""):
                with self.assertRaises(RuntimeError):
                    security.validate_configuration()
            with patch.dict("os.environ", {"DOCINTEL_LLM_URL": "https://example.invalid"}):
                with self.assertRaises(RuntimeError):
                    security.validate_configuration()

    def test_low_contrast_fixture_preserves_unit_price(self):
        sample = Path(__file__).with_name("fixtures") / "low-contrast-invoice.jpg"
        upload = self.client.post("/api/documents", auth=self.auth,
                                  files={"files": (sample.name, sample.read_bytes())})
        document_id = upload.json()["files"][0]["id"]
        self.assertTrue(process_next())
        result = self.client.get(f"/api/documents/{document_id}", auth=self.auth).json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["invoices"][0]["data"]["line_items"][0]["unit_price"], "50")
