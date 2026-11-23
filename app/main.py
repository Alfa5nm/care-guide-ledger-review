import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import db
from .invoice import FIELDS, ITEM_FIELDS, clean_field, invoice_key, validate
from .process import DocumentError, MAX_UNITS, SUFFIXES, source_preview
from .search import index_document, search
from .security import HOST, HOSTED, HOSTS, reviewer_authorized, validate_configuration
from .worker import history, MAX_ATTEMPTS

MAX_FILE = 64 * 1024 * 1024
MAX_REQUEST = 150 * 1024 * 1024
MAX_FILES = 12
SUMMARY = "id,name,status,progress,stage,attempt,processing_ms,created_at"
REVIEW_FLAGS = {"invalid_source_value", "ambiguous_field"}
MAX_WORKSPACE_BYTES = 160 * 1024 * 1024
MAX_WORKSPACE_DOCUMENTS = 100
PREVIEW_LOCK = Lock()


@asynccontextmanager
async def startup(app):
    validate_configuration()
    db.initialize()
    yield


app = FastAPI(title="Ledger Review API", version="2.0.0", lifespan=startup, docs_url=None, redoc_url=None)


@app.get("/docs", include_in_schema=False)
def documentation():
    routes = "".join(
        f"<tr><td>{escape(method.upper())}</td><td><code>{escape(path)}</code></td>"
        f"<td>{escape(operation['summary'])}</td></tr>"
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
    )
    return Response(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width"><title>Ledger Review API</title></head>'
        '<body><main><h1>Ledger Review API</h1><p><a href="/openapi.json">OpenAPI contract</a></p>'
        '<p>Upload documents, inspect jobs and invoices, review evidence, correct records, and reconcile.</p>'
        '<table><thead><tr><th>Method</th><th>Endpoint</th><th>Operation</th></tr></thead>'
        f'<tbody>{routes}</tbody></table><p><a href="/">Return to the workspace</a></p>'
        '</main></body></html>', media_type="text/html",
    )


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    method = request.method
    readiness = request.url.path == "/api/health" and method in {"GET", "HEAD"}
    if HOSTED and not readiness and not reviewer_authorized(request.headers.get("authorization", "")):
        return JSONResponse(
            {"detail": "Reviewer credentials are required."}, status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Ledger Review", charset="UTF-8"', "Cache-Control": "no-store"},
        )
    if method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        allowed = {f"https://{HOST}"} if HOSTED else {
            f"{request.url.scheme}://{request.headers.get('host')}", os.getenv("DOCINTEL_BROWSER_ORIGIN")
        }
        if origin and origin not in allowed:
            return JSONResponse({"detail": "Cross-origin write denied."}, status_code=403)
    if method in {"POST", "PATCH"}:
        raw = request.headers.get("content-length")
        if raw is None:
            return JSONResponse({"detail": "Content-Length is required."}, status_code=411)
        limit = MAX_REQUEST if request.url.path == "/api/documents" else 1024 * 1024
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 9 or int(raw) > limit:
            return JSONResponse({"detail": "Request exceeds the upload limit."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'; style-src 'self'; img-src 'self' blob:"
    )
    if HOSTED:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if HOSTED or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.add_middleware(TrustedHostMiddleware, allowed_hosts=HOSTS)


@app.get("/api/health")
def health(response: Response):
    with db.session() as conn:
        conn.execute("SELECT 1 FROM documents LIMIT 1")
    revision = os.getenv("DOCINTEL_RELEASE_COMMIT")
    if revision:
        response.headers["X-Ledger-Revision"] = revision
    return {"status": "ok"}


@app.get("/api/documents/{document_id}/preview/{page}")
def preview_document(document_id: str, page: int, rotation: int = Query(0, ge=0, le=270, multiple_of=90)):
    if not 1 <= page <= MAX_UNITS:
        raise HTTPException(404, "Source page was not found.")
    with db.session() as conn:
        document = conn.execute(
            "SELECT id, suffix FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    if document is None:
        raise HTTPException(404, "Document was not found.")
    suffix = document["suffix"]
    if suffix in {".csv", ".xls", ".xlsx"}:
        raise HTTPException(415, "Use extracted text to review this spreadsheet.")
    path = db.ROOT / "uploads" / (document["id"] + suffix)
    if not PREVIEW_LOCK.acquire(blocking=False):
        raise HTTPException(503, "The preview renderer is busy. Try again shortly.")
    try:
        content, count = source_preview(path, suffix, page - 1, rotation)
    except (IndexError, FileNotFoundError):
        raise HTTPException(404, "Source page was not found.") from None
    except (ValueError, RuntimeError, OSError, DocumentError, Image.DecompressionBombError):
        raise HTTPException(422, "This source could not be rendered.") from None
    finally:
        PREVIEW_LOCK.release()
    return Response(content, media_type="image/png", headers={"X-Page-Count": str(count)})


def insert_upload(upload):
    name = (upload.filename or "unnamed").replace("\\", "/").rsplit("/", 1)[-1][-240:]
    suffix = Path(name.lower()).suffix
    if suffix not in SUFFIXES:
        return {"name": name, "error": "Unsupported extension."}
    document_id = uuid4().hex
    path = db.ROOT / "uploads" / f"{document_id}{suffix}"
    temporary = path.with_suffix(".part")
    size = 0
    digest = hashlib.sha256()
    saved = False
    try:
        with temporary.open("xb") as handle:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE:
                    return {"name": name, "error": "File exceeds 64 MiB."}
                digest.update(chunk)
                handle.write(chunk)
        if not size:
            return {"name": name, "error": "File is empty."}
        temporary.replace(path)
        with db.session(write=True) as conn:
            if HOSTED:
                count, used = conn.execute("SELECT count(*), coalesce(sum(size_bytes), 0) FROM documents").fetchone()
                if count >= MAX_WORKSPACE_DOCUMENTS or used + size > MAX_WORKSPACE_BYTES:
                    return {"name": name, "error": "The demo workspace storage quota was reached."}
            conn.execute(
                """INSERT INTO documents(id,name,suffix,size_bytes,sha256,status,created_at)
                   VALUES (?,?,?,?,?,'queued',?)""",
                (document_id, name, suffix, size, digest.hexdigest(), time.time()),
            )
            history(conn, document_id, "uploaded", {"size_bytes": size})
        saved = True
        return {"id": document_id, "name": name, "status": "queued"}
    finally:
        temporary.unlink(missing_ok=True)
        if not saved:
            path.unlink(missing_ok=True)


@app.post("/api/documents", status_code=202)
def upload_documents(files: list[UploadFile] = File(...)):
    if len(files) > MAX_FILES:
        raise HTTPException(413, f"Upload at most {MAX_FILES} files at a time.")
    return {"files": [insert_upload(upload) for upload in files]}


JobStatus = Literal["queued", "processing", "completed", "failed"]


@app.get("/api/documents")
def list_documents(status: JobStatus | None = None, limit: int = Query(80, ge=1, le=200),
                   offset: int = Query(0, ge=0)):
    with db.session() as conn:
        rows = conn.execute(
            f"""SELECT {SUMMARY},
                       (SELECT count(*) FROM invoices i WHERE i.document_id=d.id) AS invoice_count
                FROM documents d WHERE (? IS NULL OR status=?) ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (status, status, limit, offset),
        )
        return [dict(row) for row in rows]


@app.get("/api/search")
def search_documents(q: str = Query(min_length=1, max_length=250),
                     mode: Literal["keyword", "semantic"] = "keyword", status: JobStatus | None = None):
    with db.session() as conn:
        return search(conn, q, mode, status)


def get_document(conn, document_id):
    row = conn.execute(f"SELECT {SUMMARY},error,warnings,size_bytes,suffix FROM documents WHERE id=?",
                       (document_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Document not found.")
    return dict(row)


def invoice_detail(conn, row):
    result = dict(row)
    for field in ("data", "issues", "evidence"):
        result[field] = json.loads(result[field])
    result["evidence_pages"] = result["evidence"].pop("_pages", {})
    key = result.pop("duplicate_key")
    if key:
        duplicates = conn.execute(
            """SELECT i.id AS invoice_id,i.document_id,d.name
               FROM invoices i JOIN documents d ON d.id=i.document_id
               WHERE i.duplicate_key=? AND i.id<>? ORDER BY i.id LIMIT 10""",
            (key, result["id"]),
        ).fetchall()
        result["duplicates"] = [dict(record) for record in duplicates]
        if duplicates:
            result["issues"].append({"code": "duplicate_invoice", "field": "invoice_number",
                                     "message": "Another record has this supplier and invoice number."})
    else:
        result["duplicates"] = []
    result["needs_review"] = bool(result["issues"])
    return result


@app.get("/api/documents/{document_id}")
def document_detail(document_id: str):
    with db.session() as conn:
        conn.execute("BEGIN")
        doc = get_document(conn, document_id)
        doc["warnings"] = json.loads(doc["warnings"])
        doc["can_retry"] = doc["status"] == "failed" and doc["attempt"] < MAX_ATTEMPTS
        doc["invoices"] = [
            invoice_detail(conn, row) for row in conn.execute(
                "SELECT * FROM invoices WHERE document_id=? ORDER BY position LIMIT 100", (document_id,)
            )
        ]
        doc["invoice_count"] = conn.execute(
            "SELECT count(*) FROM invoices WHERE document_id=?", (document_id,)
        ).fetchone()[0]
        doc["history"] = [
            {**dict(row), "detail": json.loads(row["detail"])}
            for row in conn.execute(
                "SELECT happened_at,event,detail FROM history WHERE document_id=? ORDER BY id DESC LIMIT 40",
                (document_id,),
            )
        ]
        return doc


@app.get("/api/documents/{document_id}/invoices")
def document_invoices(document_id: str, offset: int = Query(0, ge=0)):
    with db.session() as conn:
        conn.execute("BEGIN")
        get_document(conn, document_id)
        return [
            invoice_detail(conn, row) for row in conn.execute(
                "SELECT * FROM invoices WHERE document_id=? ORDER BY position LIMIT 100 OFFSET ?",
                (document_id, offset),
            )
        ]


@app.get("/api/documents/{document_id}/text")
def document_text(document_id: str, offset: int = Query(0, ge=0)):
    with db.session() as conn:
        row = conn.execute(
            "SELECT substr(body,?+1,50000) AS text,length(body) AS total FROM documents WHERE id=?",
            (offset, document_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found.")
        return {"text": row["text"] or "", "total": row["total"] or 0, "offset": offset}


@app.post("/api/documents/{document_id}/retry", status_code=202)
def retry(document_id: str):
    with db.session(write=True) as conn:
        doc = get_document(conn, document_id)
        if doc["status"] != "failed":
            raise HTTPException(409, "Only failed jobs can be reprocessed.")
        if doc["attempt"] >= MAX_ATTEMPTS:
            raise HTTPException(409, "This document has exhausted its processing attempts.")
        conn.execute(
            """UPDATE documents SET status='queued', progress=0, stage='Queued', error=NULL,
               processing_ms=NULL WHERE id=?""", (document_id,),
        )
        history(conn, document_id, "retry_requested")
    return {"id": document_id, "status": "queued"}


class Correction(BaseModel):
    revision: int = Field(ge=0)
    changes: dict


@app.patch("/api/invoices/{invoice_id}")
def correct_invoice(invoice_id: int, correction: Correction):
    invalid = set(correction.changes) - set(FIELDS) - {"line_items"}
    if invalid or not correction.changes:
        raise HTTPException(422, "Provide one or more supported invoice fields.")
    with db.session(write=True) as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Invoice not found.")
        if row["revision"] != correction.revision:
            raise HTTPException(409, "This invoice was updated. Reload it before editing.")
        data = json.loads(row["data"])
        before_data = row["data"]
        previous = {field: data.get(field) for field in correction.changes}
        for field, value in correction.changes.items():
            if field == "line_items":
                if not isinstance(value, list) or len(value) > 300:
                    raise HTTPException(422, "Line items must be a list of up to 300 objects.")
                items = []
                for item in value:
                    if not isinstance(item, dict) or set(item) - set(ITEM_FIELDS):
                        raise HTTPException(422, "Each line item must contain supported columns.")
                    clean_item = {key: clean_field(key, item.get(key)) for key in ITEM_FIELDS}
                    if any(item.get(key) is not None and item[key] != "" and parsed is None
                           for key, parsed in clean_item.items()):
                        raise HTTPException(422, "A line item contains an invalid value.")
                    items.append(clean_item)
                data[field] = items
            else:
                cleaned = clean_field(field, value)
                if cleaned is None and value is not None and value != "":
                    raise HTTPException(422, f"Invalid value for {field.replace('_', ' ')}.")
                data[field] = cleaned
        flags = [flag for flag in json.loads(row["issues"])
                 if flag["code"].startswith("model_") or
                 (flag["code"] in REVIEW_FLAGS and flag.get("field") not in correction.changes)]
        conn.execute("UPDATE invoices SET data=?,duplicate_key=?,issues=?,revision=revision+1 WHERE id=?",
                     (json.dumps(data), invoice_key(data), json.dumps(flags + validate(data)), invoice_id))
        conn.execute(
            "INSERT INTO invoice_corrections VALUES (?, ?, ?, ?, ?)",
            (invoice_id, row["revision"] + 1, time.time(), before_data, json.dumps(data)),
        )
        history(conn, row["document_id"], "corrected", {"invoice_id": invoice_id, "before": previous,
                "after": {field: data[field] for field in correction.changes}})
        document = conn.execute("SELECT name,body FROM documents WHERE id=?", (row["document_id"],)).fetchone()
        index_document(conn, row["document_id"], document["body"], document["name"])
        return invoice_detail(conn, conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone())


@app.get("/api/reconcile")
def reconcile(left: int, right: int):
    if left == right:
        raise HTTPException(422, "Choose two different invoices.")
    with db.session() as conn:
        conn.execute("BEGIN")
        rows = [conn.execute(
            "SELECT i.*,d.name FROM invoices i JOIN documents d ON d.id=i.document_id WHERE i.id=?", (key,)
        ).fetchone() for key in (left, right)]
        if any(row is None for row in rows):
            raise HTTPException(404, "Invoice not found.")
        first, second = (json.loads(row["data"]) for row in rows)
        differences = []
        for field in (*FIELDS, "line_items"):
            a, b = first[field], second[field]
            if a is None or b is None or field == "line_items" and (not a or not b):
                state = "missing"
            else:
                state = "match" if a == b else "different"
            differences.append({"field": field, "left": a, "right": b, "status": state})
        keys = [row["duplicate_key"] for row in rows]
        match = bool(keys[0] and keys[0] == keys[1])
        return {"left_name": rows[0]["name"], "right_name": rows[1]["name"],
                "identity_match": match, "fields": differences}


web = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if web.exists():
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
