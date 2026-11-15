"""Run the labeled corpus through the upload API and worker."""
import argparse
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db
from app.invoice import FIELDS, ITEM_FIELDS
from app.main import app
from app.worker import process_next
from tools.fixtures import benchmark, make


def percentage(count, total):
    return round(100 * count / total, 2) if total else None


def upload(client, directory, names):
    return client.post("/api/documents", files=[
        ("files", (name, (directory / name).read_bytes())) for name in names
    ]).raise_for_status().json()["files"]


def evaluate(client, directory, pages):
    labels = make(directory)
    keys = list(labels)
    submitted = upload(client, directory, keys[:10]) + upload(client, directory, keys[10:])
    while process_next():
        pass
    rows = []
    totals = {"header_correct": 0, "header_expected": 0, "header_false_values": 0,
              "header_expected_nulls": 0, "line_cells_correct": 0, "line_cells_expected": 0,
              "extra_invoices": 0, "missing_invoices": 0, "extra_line_items": 0, "exact_invoices": 0}
    per_field = {field: {"correct": 0, "expected": 0} for field in FIELDS}
    for entry in submitted:
        info = client.get(f'/api/documents/{entry["id"]}').raise_for_status().json()
        output = [invoice["data"] for invoice in info["invoices"]]
        expected = labels[entry["name"]]
        row = {"name": entry["name"], "status": info["status"], "processing_ms": info["processing_ms"],
               "expected_status": "completed" if expected is not None else "failed",
               "expected_records": len(expected or []), "actual_records": info["invoice_count"],
               "mismatches": []}
        rows.append(row)
        if expected is None:
            continue
        if len(output) != len(expected):
            row["mismatches"].append({"expected_count": len(expected), "actual_count": len(output)})
            totals["missing_invoices"] += max(0, len(expected) - len(output))
            totals["extra_invoices"] += max(0, len(output) - len(expected))
        for index, gold in enumerate(expected):
            found = output[index] if index < len(output) else {}
            if found == gold:
                totals["exact_invoices"] += 1
            for field in FIELDS:
                predicted = found.get(field)
                target = gold[field]
                if target is None:
                    totals["header_expected_nulls"] += 1
                    totals["header_false_values"] += int(predicted is not None)
                else:
                    totals["header_expected"] += 1
                    per_field[field]["expected"] += 1
                    if predicted == target:
                        totals["header_correct"] += 1
                        per_field[field]["correct"] += 1
                if predicted != target:
                    row["mismatches"].append({"invoice_index": index, "field": field, "expected": target, "actual": predicted})
            predicted_items = found.get("line_items", [])
            totals["extra_line_items"] += max(0, len(predicted_items) - len(gold["line_items"]))
            for position, item in enumerate(gold["line_items"]):
                given = predicted_items[position] if position < len(predicted_items) else {}
                for field in ITEM_FIELDS:
                    totals["line_cells_expected"] += 1
                    if given.get(field) == item[field]:
                        totals["line_cells_correct"] += 1
                    else:
                        row["mismatches"].append({"invoice_index": index, "item_index": position, "field": field,
                                                  "expected": item[field], "actual": given.get(field)})
    successful = [row for row in rows if row["status"] == "completed"]
    valid = [row for row in rows if row["expected_status"] == "completed"]
    metrics = totals | {
        "header_accuracy_pct": percentage(totals["header_correct"], totals["header_expected"]),
        "null_abstention_pct": percentage(totals["header_expected_nulls"] - totals["header_false_values"], totals["header_expected_nulls"]),
        "line_cell_accuracy_pct": percentage(totals["line_cells_correct"], totals["line_cells_expected"]),
        "full_invoice_accuracy_pct": percentage(totals["exact_invoices"], sum(row["expected_records"] for row in rows)),
        "submitted": len(rows),
        "succeeded": len(successful),
        "success_rate_pct": percentage(len(successful), len(rows)),
        "failure_rate_pct": percentage(len(rows) - len(successful), len(rows)),
        "valid_documents": len(valid),
        "valid_document_success_pct": percentage(sum(row["status"] == "completed" for row in valid), len(valid)),
        "correct_status_count": sum(row["expected_status"] == row["status"] for row in rows),
        "median_success_processing_ms": statistics.median(row["processing_ms"] for row in successful),
        "min_success_processing_ms": min(row["processing_ms"] for row in successful),
        "max_success_processing_ms": max(row["processing_ms"] for row in successful),
    }
    def run_benchmark(scanned_every):
        path = benchmark(directory, pages, scanned_every=scanned_every)
        started = time.perf_counter()
        batch = upload(client, directory, [path.name])[0]
        process_next()
        large = client.get(f'/api/documents/{batch["id"]}').raise_for_status().json()
        elapsed = round((time.perf_counter() - started) * 1000)
        return {"pages": pages, "bytes": path.stat().st_size, "status": large["status"],
                "invoices": large["invoice_count"], "processing_ms": large["processing_ms"],
                "upload_to_detail_ms": elapsed, "scanned_pages": pages // scanned_every if scanned_every else 0}

    digital = run_benchmark(0)
    mixed = run_benchmark(max(1, pages // 10))
    return {
        "environment": {"platform": platform.platform(), "python": platform.python_version(),
                        "cpu_count": os.cpu_count(), "extraction": "local, no LLM",
                        "ocr": subprocess.check_output(["tesseract", "--version"], text=True).splitlines()[0]},
        "metrics": metrics, "per_field": per_field, "documents": rows,
        "benchmark": digital, "mixed_benchmark": mixed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("artifacts/evaluation.json"))
    parser.add_argument("--pages", type=int, default=1000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        with patch.object(db, "ROOT", root / "database"), patch.dict(os.environ, {"DOCINTEL_LLM_URL": ""}), TestClient(app) as client:
            result = evaluate(client, root / "samples", args.pages)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("metrics", "benchmark", "mixed_benchmark")}, indent=2))


if __name__ == "__main__":
    main()
