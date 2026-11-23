"""Build and score the frozen synthetic layout holdout."""
import argparse
import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

from app import db
from app.invoice import FIELDS, ITEM_FIELDS
from app.main import app
from app.worker import process_next
from tools.evaluate import percentage, upload
from tools.fixtures import lines, raster, sample

FAMILIES = ("column-order", "regional-values", "positioned-labels", "faint-scan", "continuation")


def text_page(pdf, content):
    page = pdf.new_page()
    for index, line in enumerate(content):
        page.insert_text((48, 58 + index * 23), line, fontsize=12, fontname="cour")
    return page


def build(directory):
    directory.mkdir(parents=True, exist_ok=False)
    entries = []
    for family_index, family in enumerate(FAMILIES):
        for offset in range(6):
            number = family_index * 6 + offset
            name = f"{family}-{offset + 1:02}.pdf"
            supplier = ("Alder Design", "Beacon Supply", "Cedar Office", "Drift Logistics",
                        "Elm Repairs", "Foxtail Studio")[offset]
            product = ("Shipping fee", "Printer stock", "Monitor", "Advisory service",
                       "Hosting subscription", "Equipment repair")[offset]
            clean = sample(f"HO-{number + 201}", product, supplier)
            clean["invoice_date"] = f"2026-08-{offset + 12:02}"
            unit = offset + 35
            clean.update(subtotal=str(unit * 2), total=str(unit * 2 + 10))
            clean["line_items"][0].update(unit_price=str(unit), amount=str(unit * 2))
            content = lines(clean)
            path = directory / name
            if family == "continuation" and offset >= 4:
                path.write_bytes(b"Deliberately malformed synthetic PDF.")
                clean = None
            else:
                with pymupdf.open() as pdf:
                    if family == "column-order":
                        page = text_page(pdf, content[:8])
                        positions = (50, 105, 155, 410)
                        for y, row in ((270, ("Amount", "Qty", "Description", "Unit Price")),
                                       (294, (str(unit * 2), "2", product, str(unit)))):
                            for x, value in zip(positions, row):
                                page.insert_text((x, y), value, fontsize=11)
                    elif family == "regional-values":
                        content[1] = f"Invoice date: {offset + 12:02}/08/2026"
                        content[6] = f"Total: £{unit * 2 + 10}.00"
                        content[7] = "Currency: GBP"
                        clean["currency"] = "GBP"
                        text_page(pdf, content)
                    elif family == "positioned-labels":
                        page = pdf.new_page()
                        for index, line in enumerate(content[:8]):
                            label, value = line.split(": ", 1)
                            y = 55 + index * 24
                            page.insert_text((48, y), label, fontsize=12)
                            page.insert_text((260, y), value, fontsize=12)
                        for index, line in enumerate(content[8:]):
                            page.insert_text((48, 260 + index * 23), line, fontsize=12)
                    elif family == "faint-scan":
                        image = raster(clean, poor=True)
                        stream = io.BytesIO()
                        image.save(stream, format="PNG")
                        pdf.new_page(width=550, height=365).insert_image((0, 0, 550, 365), stream=stream.getvalue())
                    else:
                        if offset % 2 == 0:
                            clean["customer_name"] = None
                            content = lines(clean)
                        text_page(pdf, content[:4])
                        text_page(pdf, content[4:])
                    pdf.save(path, deflate=True, no_new_id=True)
            entries.append({"name": name, "family": family, "expected": clean,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (directory / "manifest.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def score(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    outcomes = []
    with tempfile.TemporaryDirectory() as sandbox, patch.object(db, "ROOT", Path(sandbox)), \
            patch.dict("os.environ", {"DOCINTEL_LLM_URL": ""}), TestClient(app) as client:
        for start in range(0, len(manifest), 6):
            group = manifest[start:start + 6]
            for row in group:
                assert hashlib.sha256((directory / row["name"]).read_bytes()).hexdigest() == row["sha256"]
            submitted = upload(client, directory, [row["name"] for row in group])
            while process_next():
                pass
            for row, entry in zip(group, submitted, strict=True):
                result = client.get(f"/api/documents/{entry['id']}").raise_for_status().json()
                records = [record["data"] for record in result["invoices"]]
                actual = records[0] if len(records) == 1 else {}
                expected = row["expected"]
                output = {key: row[key] for key in ("name", "family")} | {
                    "status": result["status"],
                    "flags": [issue["code"] for invoice in result["invoices"] for issue in invoice["issues"]],
                }
                if expected is None:
                    outcomes.append(output | {"exact": result["status"] == "failed", "malformed": True})
                    continue
                fields = [(key, expected[key], actual.get(key)) for key in FIELDS]
                reported = actual.get("line_items", [])
                for index in range(max(len(expected["line_items"]), len(reported))):
                    target = expected["line_items"][index] if index < len(expected["line_items"]) else {}
                    found = reported[index] if index < len(reported) else {}
                    fields.extend((f"line_{index + 1}.{key}", target.get(key), found.get(key)) for key in ITEM_FIELDS)
                outcomes.append(output | {
                    "exact": records == [expected], "records": len(records),
                    "fields": [{"field": key, "expected": gold, "actual": value} for key, gold, value in fields],
                })
        queries = [("Shipping fee", "freight", 1), ("Printer stock", "stationery", 2),
                   ("Monitor", "hardware", 3), ("Advisory service", "consulting", 4),
                   ("Hosting subscription", "software", 5), ("Equipment repair", "servicing", 6)]
        retrieval = {}
        for mode in ("keyword", "semantic"):
            results = []
            for exact, paraphrase, offset in queries:
                relevant = {row["name"] for row in manifest if row["expected"] and row["name"].endswith(f"-{offset:02}.pdf")}
                for query in (exact, paraphrase):
                    matches = client.get("/api/search", params={"q": query, "mode": mode}).raise_for_status().json()
                    names = [entry["name"] for entry in matches[:5]]
                    results.append({"query": query, "hits_at_5": len(relevant.intersection(names)),
                                    "relevant": len(relevant), "returned_at_5": len(names)})
            retrieval[mode] = results

    def summarize(rows):
        cells = [cell for row in rows for cell in row.get("fields", [])]
        correct = sum(cell["expected"] is not None and cell["expected"] == cell["actual"] for cell in cells)
        populated = sum(cell["actual"] is not None for cell in cells)
        expected = sum(cell["expected"] is not None for cell in cells)
        return {"exact": sum(row["exact"] for row in rows), "documents": len(rows),
                "precision_pct": percentage(correct, populated), "recall_pct": percentage(correct, expected),
                "incorrect_accepted": populated - correct,
                "unsupported_accepted": sum(cell["actual"] is not None and cell["expected"] is None for cell in cells),
                "abstentions": sum(cell["actual"] is None and cell["expected"] is not None for cell in cells)}

    valid = [row for row in outcomes if not row.get("malformed")]
    return {"summary": summarize(valid), "families": {family: summarize([row for row in valid if row["family"] == family])
            for family in FAMILIES}, "expected_failures": sum(row["exact"] for row in outcomes if row.get("malformed")),
            "retrieval": retrieval, "documents": outcomes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.build:
        build(args.directory)
    else:
        report = score(args.directory)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"]))
