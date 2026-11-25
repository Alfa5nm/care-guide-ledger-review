"""Reviewer decisions and immutable staging exports."""
import csv
import io
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import db
from .worker import history

router = APIRouter(prefix="/api")
CSV_FIELDS = ("invoice_number", "supplier_name", "invoice_date", "subtotal", "tax", "total",
              "currency", "review_timestamp", "source_reference")
INVOICE = """SELECT i.*, d.name AS filename, d.status AS document_status
             FROM invoices i JOIN documents d ON d.id=i.document_id"""


def fetch_invoice(conn, invoice_id):
    row = conn.execute(INVOICE + " WHERE i.id=?", (invoice_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Invoice not found.")
    return row


def members(conn, identity):
    if not identity:
        return []
    return conn.execute(INVOICE + " WHERE i.duplicate_key=? ORDER BY i.id", (identity,)).fetchall()


def current_decision(conn, identity):
    return conn.execute("SELECT * FROM current_duplicate_decisions WHERE identity=?", (identity,)).fetchone()


def export_entry(conn, invoice_id):
    return conn.execute("SELECT batch_id FROM exported_invoices WHERE invoice_id=?", (invoice_id,)).fetchone()


def review_state(conn, row):
    exported = export_entry(conn, row["id"])
    if exported:
        return {"status": "exported", "batch_id": exported["batch_id"], "can_approve": False}

    identity = row["duplicate_key"]
    decision = current_decision(conn, identity) if identity else None
    if decision and decision["canonical_id"] != row["id"]:
        return {"status": "excluded_duplicate", "can_approve": False,
                "canonical_id": decision["canonical_id"], "reason": decision["reason"]}

    prior_export = identity and conn.execute(
        "SELECT batch_id FROM exported_invoices WHERE identity=?", (identity,),
    ).fetchone()
    has_duplicates = identity and conn.execute(
        "SELECT 1 FROM invoices WHERE duplicate_key=? AND id<>?", (identity, row["id"]),
    ).fetchone()
    approval = conn.execute("SELECT * FROM invoice_approvals WHERE invoice_id=?", (row["id"],)).fetchone()
    token = decision["resolved_at"] if decision else None
    can_approve = bool(identity and not prior_export and not json.loads(row["issues"])
                       and (decision or not has_duplicates))
    if can_approve and approval and approval["revision"] == row["revision"] and approval["resolution_token"] == token:
        return {"status": "approved", "approved_at": approval["approved_at"], "can_approve": False}
    return {"status": "needs_review", "can_approve": can_approve,
            "can_resolve": bool(has_duplicates and not prior_export), "prior_export": bool(prior_export)}


class Revision(BaseModel):
    revision: int = Field(ge=0)


class DuplicateDecision(BaseModel):
    members: dict[int, int] = Field(min_length=2)
    reason: str = Field(min_length=1, max_length=500)


@router.get("/invoices/{invoice_id}/duplicate-group")
def duplicate_group(invoice_id: int):
    with db.session() as conn:
        conn.execute("BEGIN")
        row = fetch_invoice(conn, invoice_id)
        return [{"id": item["id"], "revision": item["revision"], "filename": item["filename"],
                 "document_id": item["document_id"], "source": item["source"],
                 "total": json.loads(item["data"]).get("total")}
                for item in members(conn, row["duplicate_key"])]


@router.post("/invoices/{invoice_id}/duplicate-resolution")
def resolve_duplicate(invoice_id: int, request: DuplicateDecision):
    reason = request.reason.strip()
    if not reason:
        raise HTTPException(422, "Enter a short reason for choosing the canonical invoice.")
    with db.session(write=True) as conn:
        canonical = fetch_invoice(conn, invoice_id)
        key = canonical["duplicate_key"]
        group = members(conn, key)
        if len(group) < 2 or request.members != {row["id"]: row["revision"] for row in group}:
            raise HTTPException(409, "The duplicate group changed. Reload and review it again.")
        if conn.execute("SELECT 1 FROM exported_invoices WHERE identity=?", (key,)).fetchone():
            raise HTTPException(409, "This invoice identity has already been exported.")
        signature = json.dumps([[row["id"], row["revision"]] for row in group], separators=(",", ":"))
        timestamp = time.time()
        conn.execute("INSERT OR REPLACE INTO duplicate_decisions VALUES (?,?,?,?,?)",
                     (key, invoice_id, signature, reason, timestamp))
        excluded = [row["id"] for row in group if row["id"] != invoice_id]
        for row in group:
            history(conn, row["document_id"], "duplicate_resolved", {
                "canonical_id": invoice_id, "excluded_invoice_ids": excluded, "reason": reason,
                "member_revisions": request.members, "invoice_id": row["id"],
            })
        return {"canonical_id": invoice_id, "excluded_invoice_ids": excluded}


@router.post("/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: int, request: Revision):
    with db.session(write=True) as conn:
        row = fetch_invoice(conn, invoice_id)
        if row["revision"] != request.revision:
            raise HTTPException(409, "This invoice changed. Reload and review the latest revision.")
        state = review_state(conn, row)
        if state["status"] == "approved":
            return state
        if row["document_status"] != "completed" or not state["can_approve"]:
            raise HTTPException(409, "Resolve the invoice flags and duplicate decision before approval.")
        decision = current_decision(conn, row["duplicate_key"])
        approved_at = time.time()
        conn.execute("INSERT OR REPLACE INTO invoice_approvals VALUES (?,?,?,?)",
                     (invoice_id, row["revision"], approved_at, decision["resolved_at"] if decision else None))
        history(conn, row["document_id"], "approved", {"invoice_id": invoice_id, "revision": row["revision"]})
        return {"status": "approved", "approved_at": approved_at, "can_approve": False}


def eligible(conn):
    rows = conn.execute(INVOICE + " JOIN invoice_approvals a ON a.invoice_id=i.id WHERE d.status='completed' "
                        "AND a.revision=i.revision ORDER BY a.approved_at, i.id").fetchall()
    for row in rows:
        state = review_state(conn, row)
        if state["status"] == "approved":
            yield row, state["approved_at"]


@router.get("/exports")
def export_workspace(limit: int = Query(30, ge=1, le=100)):
    with db.session() as conn:
        conn.execute("BEGIN")
        pending = [{"invoice_id": row["id"], "document_id": row["document_id"], "filename": row["filename"],
                    "invoice_number": json.loads(row["data"])["invoice_number"]} for row, _ in eligible(conn)]
        batches = [dict(batch) for batch in conn.execute(
            "SELECT id,created_at,row_count FROM export_batches ORDER BY created_at DESC LIMIT ?", (limit,))]
    return {"pending": pending, "batches": batches}


def csv_text(value):
    value = str(value)
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@router.post("/exports", status_code=201)
def create_export():
    with db.session(write=True) as conn:
        rows = list(eligible(conn))
        if not rows:
            raise HTTPException(409, "No approved invoices are ready to export.")
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row, approved_at in rows:
            data = json.loads(row["data"])
            output = {key: data[key] for key in CSV_FIELDS[:7]}
            for key in ("invoice_number", "supplier_name"):
                output[key] = csv_text(output[key])
            writer.writerow(output | {
                "review_timestamp": datetime.fromtimestamp(approved_at, timezone.utc).isoformat(),
                "source_reference": csv_text(f"{row['filename']} · {row['source']} · {row['document_id']}"),
            })
        batch = {"id": uuid4().hex, "created_at": time.time(), "row_count": len(rows)}
        conn.execute("INSERT INTO export_batches VALUES (?,?,?,?)",
                     (*batch.values(), buffer.getvalue().encode("utf-8")))
        for row, _ in rows:
            conn.execute("INSERT INTO exported_invoices VALUES (?,?,?)",
                         (row["duplicate_key"], row["id"], batch["id"]))
            history(conn, row["document_id"], "exported", {"invoice_id": row["id"], "batch_id": batch["id"]})
        return batch


@router.get("/exports/{batch_id}/csv")
def download_export(batch_id: str):
    with db.session() as conn:
        batch = conn.execute("SELECT content FROM export_batches WHERE id=?", (batch_id,)).fetchone()
    if batch is None:
        raise HTTPException(404, "Export batch not found.")
    return Response(batch["content"], media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="ledger-export-{batch_id}.csv"'})
