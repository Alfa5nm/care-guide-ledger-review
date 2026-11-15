import io
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db
from app.invoice import grounded, invoice_record, read_candidates, validate
from app.main import app
from app.process import DocumentError, extract
from app.worker import claim, process_next
from tools.fixtures import lines, make, sample


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.labels = make(cls.root / "samples")
        cls.samples = cls.root / "samples"

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = patch.object(db, "ROOT", Path(directory.name))
        root.start()
        self.addCleanup(root.stop)
        config = patch.dict(os.environ, {"DOCINTEL_LLM_URL": ""})
        config.start()
        self.addCleanup(config.stop)
        self.client = self.enterContext(TestClient(app))

    def upload(self, *names):
        files = [("files", (name, (self.samples / name).read_bytes())) for name in names]
        response = self.client.post("/api/documents", files=files)
        self.assertEqual(202, response.status_code, response.text)
        return [row["id"] for row in response.json()["files"]]

    def detail(self, document_id):
        return self.client.get(f"/api/documents/{document_id}").json()

    def assert_invoice(self, filename):
        document_id = self.upload(filename)[0]
        self.assertTrue(process_next())
        doc = self.detail(document_id)
        self.assertEqual(doc["status"], "completed", doc)
        self.assertEqual([i["data"] for i in doc["invoices"]], self.labels[filename])

    def test_digital_pdf_and_multipage_continuation(self):
        for filename in ("01-original-invoice.pdf", "07-two-page-invoice.pdf"):
            with self.subTest(filename=filename):
                self.assert_invoice(filename)

    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract must be on PATH for OCR tests")
    def test_real_ocr_scanned_pdf_jpg_png_tiff(self):
        for filename in ("03-scanned-invoice.pdf", "04-low-contrast.jpg",
                         "05-invoice-image.png", "06-multi-frame.tiff"):
            with self.subTest(filename=filename):
                self.assert_invoice(filename)

    def test_csv_xlsx_and_xls(self):
        for filename in ("09-register.csv", "10-billing-workbook.xlsx", "11-legacy-ledger.xls"):
            with self.subTest(filename=filename):
                self.assert_invoice(filename)

    def test_model_quotes_unsupported_values_and_fallback(self):
        body = "Supplier: Harbor Supply\nAcknowledged by Maple Studio"
        candidates, items = read_candidates(body)
        model = {"supplier_name": {"value": "Maple Studio", "quote": "Acknowledged by Maple Studio"},
                 "customer_name": {"value": "Unknown Customer", "quote": "No evidence"},
                 "invoice_number": {"value": "BAD", "quote": "BAD"}}
        with patch.dict(os.environ, {"DOCINTEL_LLM_URL": "test"}), patch("app.invoice.model_extract", return_value=model):
            result = invoice_record("Page 1", candidates, items, body)
        self.assertEqual(result["data"]["supplier_name"], "Harbor Supply")
        self.assertIsNone(result["data"]["customer_name"])
        self.assertIsNone(result["data"]["invoice_number"])
        self.assertEqual(grounded("supplier_name", {"value": "Harbor Supply", "quote": "Supplier: Harbor Supply"}, body)[0], "Harbor Supply")
        with patch.dict(os.environ, {"DOCINTEL_LLM_URL": "test"}), patch("app.invoice.model_extract", side_effect=TimeoutError):
            result = invoice_record("Page 1", candidates, items, body)
        self.assertIn("model_unavailable", {flag["code"] for flag in result["flags"]})

    def test_model_client_request_and_schema_quotes(self):
        from app.invoice import model_extract
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"total":{"value":"110","quote":"Total: 110"}}'}}]}).encode())
        with patch.dict(os.environ, {"DOCINTEL_LLM_URL": "https://example.test/v1/chat/completions",
                                    "DOCINTEL_LLM_MODEL": "test-model", "DOCINTEL_LLM_KEY": "test-key"}):
            with patch("app.invoice.urlopen", return_value=response) as url:
                model = model_extract("Total: 110")
        request = url.call_args.args[0]
        self.assertEqual(json.loads(request.data)["model"], "test-model")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(model["total"]["value"], "110")

    def test_ambiguous_and_invalid_numbers_are_not_invented(self):
        recognized, items = read_candidates("Invoice number: A-1\nTotal: 100\nTotal: 120\nTax: junk")
        output = invoice_record("Page 1", recognized, items)
        self.assertIsNone(output["data"]["total"])
        self.assertIsNone(output["data"]["tax"])
        self.assertEqual({flag["code"] for flag in output["flags"]}, {"invalid_source_value", "ambiguous_field"})

    def test_validation_math(self):
        invoice = sample("DEMO", subtotal="90", tax="10", total="115")
        invoice["line_items"][0]["amount"] = "99"
        self.assertEqual({issue["code"] for issue in validate(invoice)},
                         {"total_mismatch", "line_mismatch", "subtotal_mismatch"})

    def test_partial_document_is_marked_for_review(self):
        document_id = self.upload("08-incomplete-invoice.pdf")[0]
        process_next()
        record = self.detail(document_id)["invoices"][0]
        self.assertTrue(record["needs_review"])
        self.assertIsNone(record["data"]["currency"])

    def test_mixed_batch_failure_isolated_and_retryable(self):
        good, bad, invalid_csv = self.upload("01-original-invoice.pdf", "12-corrupt.pdf", "13-malformed.csv")
        for _ in range(3):
            self.assertTrue(process_next())
        self.assertEqual("completed", self.detail(good)["status"])
        self.assertEqual("failed", self.detail(bad)["status"])
        self.assertEqual("failed", self.detail(invalid_csv)["status"])
        self.assertEqual(409, self.client.post(f"/api/documents/{good}/retry", content=b"").status_code)
        self.assertEqual(202, self.client.post(f"/api/documents/{bad}/retry", content=b"").status_code)
        self.assertEqual("queued", self.detail(bad)["status"])
        process_next()
        self.assertEqual("failed", self.detail(bad)["status"])
        self.assertIn("retry_requested", [entry["event"] for entry in self.detail(bad)["history"]])

    def test_correction_revalidation_search_and_revision_conflict(self):
        document_id = self.upload("02-conflicting-copy.pdf")[0]
        process_next()
        record = self.detail(document_id)["invoices"][0]
        self.assertIn("total_mismatch", {issue["code"] for issue in record["issues"]})
        endpoint = f"/api/invoices/{record['id']}"
        self.assertEqual(422, self.client.patch(endpoint, json={"revision": 0, "changes": {"total": "bad"}}).status_code)
        payload = {"revision": 0, "changes": {"total": "110", "customer_name": "Evergreen Studios"}}
        result = self.client.patch(endpoint, json=payload)
        self.assertEqual(200, result.status_code, result.text)
        self.assertFalse(result.json()["needs_review"])
        self.assertEqual(409, self.client.patch(endpoint, json=payload).status_code)
        self.assertEqual(document_id, self.client.get("/api/search", params={"q": "Evergreen Studios"}).json()[0]["id"])
        event = self.detail(document_id)["history"][0]
        self.assertEqual("115", event["detail"]["before"]["total"])

    def test_keyword_semantic_filter_and_source_text(self):
        document_id = self.upload("01-original-invoice.pdf")[0]
        process_next()
        self.assertEqual([], self.client.get("/api/search", params={"q": "freight"}).json())
        self.assertEqual(document_id, self.client.get("/api/search", params={"q": "freight", "mode": "semantic"}).json()[0]["id"])
        self.assertEqual([], self.client.get("/api/documents", params={"status": "failed"}).json())
        self.assertEqual([], self.client.get("/api/search", params={"q": "freight", "mode": "semantic", "status": "failed"}).json())
        self.assertIn("CG-1001", self.client.get(f"/api/documents/{document_id}/text").json()["text"])

    def test_duplicate_and_cross_document_reconciliation(self):
        a, b, c = self.upload("01-original-invoice.pdf", "02-conflicting-copy.pdf", "10-billing-workbook.xlsx")
        for _ in range(3):
            process_next()
        original = self.detail(a)["invoices"][0]
        self.assertEqual(2, len(original["duplicates"]))
        for document_id in (b, c):
            comparison = self.client.get("/api/reconcile", params={"left": original["id"], "right": self.detail(document_id)["invoices"][0]["id"]}).json()
            self.assertTrue(comparison["identity_match"])
            self.assertEqual(["total"], [field["field"] for field in comparison["fields"] if field["status"] == "different"])

    def test_recovery_after_expired_lease(self):
        document_id = self.upload("01-original-invoice.pdf")[0]
        document, token = claim()
        self.assertEqual(document["id"], document_id)
        self.assertIsNone(claim())
        with db.session(write=True) as conn:
            conn.execute("UPDATE documents SET lease_until=? WHERE lease_token=?", (time.time() - 1, token))
        process_next()
        record = self.detail(document_id)
        self.assertEqual((record["status"], record["attempt"]), ("completed", 2))

    def test_sanitized_upload_and_local_origin_boundary(self):
        result = self.client.post("/api/documents", files=[("files", ("../hidden.txt", b"untrusted"))])
        self.assertEqual(result.json()["files"], [{"name": "hidden.txt", "error": "Unsupported extension."}])
        result = self.client.post("/api/documents", headers={"Origin": "https://hostile.example"},
                                  files=[("files", ("file.csv", b"anything"))])
        self.assertEqual(403, result.status_code)
        self.assertEqual(404, self.client.get("/api/documents/nope").status_code)
        self.assertEqual(200, self.client.get("/api/health").status_code)

    def test_encrypted_pdf_failure(self):
        import fitz
        path = self.root / "encrypted.pdf"
        with fitz.open() as document:
            document.new_page()
            document.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="test-pass")
        with self.assertRaisesRegex(DocumentError, "Password-protected"):
            extract(path, ".pdf", lambda *_: None)


if __name__ == "__main__":
    unittest.main()
