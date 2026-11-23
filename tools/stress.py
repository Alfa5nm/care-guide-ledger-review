"""Exercise one 100-page scan and four concurrent arrivals with a separate worker."""
import argparse
import json
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.worker import process_next
from tools.fixtures import benchmark, pdf, sample


def run():
    with tempfile.TemporaryDirectory() as sandbox, patch.object(db, "ROOT", Path(sandbox) / "data"), \
            patch.dict("os.environ", {"DOCINTEL_LLM_URL": ""}), TestClient(app) as client:
        root = Path(sandbox)
        scan = benchmark(root, 100, scanned_every=1)
        fast = root / "quick.pdf"
        pdf(fast, [sample("QUEUE-1")])
        stopped = threading.Event()

        def work():
            while not stopped.is_set():
                if not process_next():
                    stopped.wait(0.1)

        def send(name, body):
            started = time.monotonic()
            reply = client.post("/api/documents", files={"files": (name, body)}).raise_for_status()
            return reply.json()["files"][0]["id"], round((time.monotonic() - started) * 1000)

        def observe(id_):
            return client.get(f"/api/documents/{id_}").raise_for_status().json()

        worker = threading.Thread(target=work)
        worker.start()
        try:
            long, long_upload = send(scan.name, scan.read_bytes())
            deadline = time.monotonic() + 240
            while observe(long)["status"] == "queued" and time.monotonic() < deadline:
                time.sleep(0.1)
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs = [pool.submit(send, f"parallel-{index}.pdf", fast.read_bytes()) for index in range(4)]
                submitted = [(long, long_upload), *(job.result() for job in jobs)]
            pending = dict(submitted)
            results = []
            while pending and time.monotonic() < deadline:
                for id_, upload_ms in list(pending.items()):
                    row = observe(id_)
                    if row["status"] not in {"completed", "failed"}:
                        continue
                    times = {event["event"]: event["happened_at"] for event in row["history"]}
                    results.append({"file": row["name"], "status": row["status"], "records": row["invoice_count"],
                                    "upload_ms": upload_ms, "worker_ms": row["processing_ms"],
                                    "queue_ms": round((times["processing"] - times["uploaded"]) * 1000)})
                    del pending[id_]
                if pending:
                    time.sleep(0.4)
            return {"scanned_pages": 100, "concurrent_uploads": 4, "timed_out": len(pending), "results": results}
        finally:
            stopped.set()
            worker.join(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence = run()
    args.out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence))
