"""Verify the hosted API with labeled, synthetic fixtures."""
import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx


def verify(url, directory, password):
    expected = json.loads((directory / "labels.json").read_text(encoding="utf-8"))
    prefix = f"{uuid4().hex[:6]}-"
    with httpx.Client(base_url=url, timeout=30) as client:
        assert client.get("/api/health").raise_for_status().json() == {"status": "ok"}
        for path in ("/", "/api/documents", "/docs", "/openapi.json"):
            assert client.get(path).status_code == 401, path

        client.auth = ("reviewer", password)
        assert client.get("/docs").raise_for_status().headers["cache-control"] == "no-store"
        assert client.get("/openapi.json").raise_for_status().json()["info"]["version"] == "2.0.0"
        denied = client.post("/api/documents", headers={"Origin": "https://example.invalid"},
                             files={"files": ("synthetic.csv", b"example")})
        assert denied.status_code == 403
        ids = {}
        names = list(expected)
        started = time.monotonic()
        for group in (names[:10], names[10:]):
            files = [("files", (prefix + name, (directory / name).read_bytes())) for name in group]
            response = client.post("/api/documents", files=files).raise_for_status()
            assert response.status_code == 202
            for name, result in zip(group, response.json()["files"], strict=True):
                ids[name] = result["id"]

        completed = {}
        while len(completed) < len(ids) and time.monotonic() - started < 100:
            for name, id_ in ids.items():
                if name in completed:
                    continue
                row = client.get(f"/api/documents/{id_}").raise_for_status().json()
                if row["status"] in {"completed", "failed"}:
                    completed[name] = row
            if len(completed) < len(ids):
                time.sleep(1)
        assert len(completed) == len(ids), "Queue did not finish before the deadline."
        matches = 0
        for name, labels in expected.items():
            result = completed[name]
            assert result["status"] == ("failed" if labels is None else "completed"), name
            if labels is not None:
                invoices = [entry["data"] for entry in result["invoices"]]
                assert invoices == labels, (name, invoices, labels)
                matches += len(invoices)

        id_ = ids["03-scanned-invoice.pdf"]
        preview = client.get(f"/api/documents/{id_}/preview/1").raise_for_status()
        assert preview.headers["content-type"] == "image/png"
        assert client.get(f"/api/documents/{id_}/preview/999").status_code == 404
        assert client.post(f"/api/documents/{id_}/retry").status_code == 409
        invalid = client.post("/api/documents", files=[
            ("files", ("empty.pdf", b"")), ("files", ("unsupported.txt", b"sample")),
        ]).raise_for_status().json()
        assert all("error" in record for record in invalid["files"])
        return {
            "documents": len(completed),
            "valid_documents": sum(value is not None for value in expected.values()),
            "expected_failures": sum(value is None for value in expected.values()),
            "exact_invoice_matches": matches,
            "sample_document_id": id_,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--samples", type=Path, default=Path("artifacts/samples"))
    args = parser.parse_args()
    print(json.dumps(verify(args.url, args.samples, os.environ["DOCINTEL_SMOKE_PASSWORD"]), indent=2))
