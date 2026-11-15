import json
import logging
import secrets
import threading
import time

from . import db
from .invoice import invoice_key, records, validate
from .process import DocumentError, extract
from .search import index_document

LEASE_SECONDS = 90
MAX_ATTEMPTS = 3
log = logging.getLogger(__name__)


def history(connection, document_id, event, detail=None):
    connection.execute(
        "INSERT INTO history(document_id,happened_at,event,detail) VALUES (?,?,?,?)",
        (document_id, time.time(), event, json.dumps(detail or {})),
    )


def claim():
    with db.session(write=True) as conn:
        now = time.time()
        expired = conn.execute(
            "SELECT id FROM documents WHERE status='processing' AND lease_until<? AND attempt>=?",
            (now, MAX_ATTEMPTS),
        ).fetchall()
        for row in expired:
            conn.execute(
                """UPDATE documents SET status='failed', stage='Failed', lease_until=NULL,
                          lease_token=NULL,error='Worker stopped before the job finished.' WHERE id=?""",
                (row["id"],),
            )
            history(conn, row["id"], "failed", {"reason": "worker lease expired"})
        row = conn.execute(
            """SELECT * FROM documents WHERE status='queued' OR (status='processing' AND lease_until<?)
               ORDER BY created_at LIMIT 1""", (now,),
        ).fetchone()
        if row is None:
            return None
        token = secrets.token_hex(16)
        conn.execute(
            """UPDATE documents SET status='processing',progress=3,stage='Opening file',
               lease_until=?,lease_token=?,attempt=attempt+1 WHERE id=?""",
            (now + LEASE_SECONDS, token, row["id"]),
        )
        history(conn, row["id"], "processing", {"attempt": row["attempt"] + 1})
        return dict(row), token


def process_next():
    task = claim()
    if task is None:
        return False
    document, token = task
    document_id = document["id"]
    started = time.perf_counter()
    stopped = threading.Event()
    last_progress = (None, 0.0)

    def renew(percent=None, stage=None):
        with db.session(write=True) as conn:
            conn.execute(
                """UPDATE documents SET lease_until=?,progress=coalesce(?,progress),
                   stage=coalesce(?,stage) WHERE id=? AND lease_token=?""",
                (time.time() + LEASE_SECONDS, percent, stage, document_id, token),
            )

    def heartbeat():
        while not stopped.wait(20):
            try:
                renew()
            except Exception:
                log.exception("Could not renew job lease")

    def progress(percent, stage):
        nonlocal last_progress
        now = time.monotonic()
        if last_progress[0] != percent or now - last_progress[1] >= 2:
            renew(percent, stage)
            last_progress = (percent, now)

    pulse = threading.Thread(target=heartbeat, daemon=True)
    pulse.start()
    try:
        path = db.ROOT / "uploads" / f'{document_id}{document["suffix"]}'
        sections, warnings = extract(path, document["suffix"], progress)
        progress(65, "Extracting invoice fields")
        findings = list(records(sections))
        progress(87, "Validating and indexing")
        body = "\n\n".join(f"{section.source}\n{section.text}" for section in sections)
        with db.session(write=True) as conn:
            if not conn.execute("SELECT 1 FROM documents WHERE id=? AND lease_token=?",
                                (document_id, token)).fetchone():
                return True
            conn.execute("DELETE FROM invoices WHERE document_id=?", (document_id,))
            conn.executemany(
                """INSERT INTO invoices(document_id,position,source,extraction_method,data,evidence,duplicate_key,issues)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    (document_id, index, entry["source"], entry["method"], json.dumps(entry["data"]),
                     json.dumps(entry["evidence"]), invoice_key(entry["data"]),
                     json.dumps(entry["flags"] + validate(entry["data"])))
                    for index, entry in enumerate(findings, 1)
                ],
            )
            index_document(conn, document_id, body, document["name"])
            conn.execute(
                """UPDATE documents SET status='completed',progress=100,stage='Completed',
                   lease_until=NULL,lease_token=NULL,error=NULL,body=?,warnings=?,processing_ms=? WHERE id=?""",
                (body, json.dumps(warnings), round((time.perf_counter() - started) * 1000), document_id),
            )
            history(conn, document_id, "completed", {"invoices": len(findings), "warnings": len(warnings)})
    except Exception as exc:
        error = str(exc) if isinstance(exc, DocumentError) else "Processing stopped unexpectedly."
        if not isinstance(exc, DocumentError):
            log.exception("Document job failed")
        with db.session(write=True) as conn:
            updated = conn.execute(
                """UPDATE documents SET status='failed',stage='Failed',error=?,lease_until=NULL,
                   lease_token=NULL,processing_ms=? WHERE id=? AND lease_token=?""",
                (error, round((time.perf_counter() - started) * 1000), document_id, token),
            )
            if updated.rowcount:
                history(conn, document_id, "failed", {"reason": error})
    finally:
        stopped.set()
        pulse.join()
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    db.initialize()
    while True:
        try:
            if not process_next():
                time.sleep(0.4)
        except Exception:
            log.exception("Worker loop failed; retrying")
            time.sleep(2)


if __name__ == "__main__":
    main()
