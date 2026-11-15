# Ledger Review architecture and database schema

Ledger Review accepts financial documents, processes them in a background worker, and gives reviewers a browser workspace for source inspection, corrections, search, and reconciliation.

## 1. System architecture

```mermaid
flowchart TD
  Web["Browser · React workspace"]
  Edge["Optional hosted demo · Cloudflare Tunnel and password gate"]
  API["FastAPI · serves built frontend and REST API"]
  Files["Private uploads · original files on disk"]
  DB[("SQLite WAL · queue, invoices, history, search")]
  Worker["Separate Python worker · claims and processes jobs"]
  OCR["Tesseract · local OCR"]
  Model["Optional compatible LLM endpoint"]

  Web -->|"Local mode"| API
  Web -->|"Hosted HTTPS mode"| Edge
  Edge --> API
  API -->|"Write and render originals"| Files
  API -->|"Queue, review, search, correct"| DB
  DB -->|"Claim and renew lease"| Worker
  Files -->|"Read original"| Worker
  Worker -->|"Scan or raster region"| OCR
  Worker -.->|"Evidence-backed proposals if configured"| Model
  Worker -->|"Commit results or failure"| DB
```

The API and worker use the same data directory. Original uploads are outside the static web directory. Local development runs one API process and one worker process. Docker Compose defines separate services with a shared volume. The hosted demo uses an isolated data store and a temporary tunnel. It has a shared password and no per-user database authorization.

## 2. Upload to completed document

```mermaid
flowchart TD
  Upload["Upload one batch from Documents"]
  Valid{"Accepted file and request?"}
  Reject["Return upload rejection"]
  Queue["Save original, compute SHA-256, queue job"]
  Claim["Worker claims job and records progress"]
  Format{"Input format"}
  PDF["PDF · read text and OCR scans or raster regions"]
  Image["Image · OCR each supported frame"]
  Sheet["Spreadsheet · parse sheets or delimited rows"]
  Readable{"Usable text or cells?"}
  Failed["Record error and failed attempt"]
  Extract["Segment records and extract normalized fields"]
  Validate["Validate values and arithmetic"]
  Commit["Save records, warnings, indexes, and history"]
  Review["Update document status in the browser"]

  Upload --> Valid
  Valid -->|"No"| Reject
  Valid -->|"Yes"| Queue
  Queue --> Claim
  Claim --> Format
  Format --> PDF & Image & Sheet
  PDF & Image & Sheet --> Readable
  Readable -->|"No"| Failed
  Readable -->|"Yes"| Extract
  Extract --> Validate --> Commit --> Review
  Failed --> Review
```

Digital PDFs retain selectable text. The OCR path handles scans and image regions on mixed pages. Spreadsheet parsers work from stored cell values. Readable pages can still produce a result when another page emits a warning. The model path is optional. Accepted proposals require source quotes, and uncertain values can remain empty. Validation checks numeric values, missing fields, and financial arithmetic. Duplicate flags are calculated when invoice details are read using the normalized supplier and invoice number.

## 3. Job lifecycle and recovery

```mermaid
stateDiagram-v2
  state "Queued" as Queued
  state "Processing" as Processing
  state "Completed" as Completed
  state "Failed" as Failed
  [*] --> Queued: Upload persisted
  Queued --> Processing: Worker claims job
  Processing --> Processing: Renew lease or reclaim expired attempt
  Processing --> Completed: Commit results with current lease token
  Processing --> Failed: Processing error or exhausted lease recovery
  Failed --> Queued: Manual retry resets attempt counter
```

The lease lasts 90 seconds and has a 20-second heartbeat. Progress updates can renew it too. A valid lease token guards completion and failure writes. Expired jobs can be reclaimed, and an expired job that has reached three attempts is marked failed. Upload, processing, completion, failure, retry, and correction events are recorded in history.

## 4. Browser workflows and data paths

```mermaid
flowchart TD
  Detail["Open document"]
  Source["Source viewer or extracted text"]
  Correction["Edit current invoice revision"]
  Compare["Choose two stored invoices"]
  Search["Search indexed documents"]
  Preview["Render bounded PNG from original"]
  Write["Revalidate, write audit entry, and reindex"]
  Diff["Return field matches, differences, and missing values"]
  Rank["FTS5 ranking or sparse concept scoring"]

  Detail --> Source & Correction & Compare
  Source -->|"PDF or image"| Preview
  Correction --> Write
  Compare --> Diff
  Search --> Rank
```

| Interaction | API and behavior |
|---|---|
| Upload and queue | `POST /api/documents` returns per-file intake results. `GET /api/documents` reports status and progress. |
| Inspect | `GET /api/documents/{id}` returns status, the first invoice page, warnings, and history. More invoices are available under `/invoices`. |
| View evidence | `GET /api/documents/{id}/text` pages extracted text. `GET /api/documents/{id}/preview/{page}` renders a bounded PNG and supports rotation. |
| Correct | `PATCH /api/invoices/{id}` checks the revision, validates the submitted values, updates records and search indexes, and writes before-and-after values to history. |
| Reconcile | `GET /api/reconcile` compares two invoice IDs, including PDF-to-PDF and PDF-to-Excel pairs. It reports field differences and a supplier-plus-invoice-number identity check. |
| Search | `GET /api/search` uses SQLite FTS5 for keywords or cosine-style scoring over normalized sparse lexical and financial concept features. |
| Retry and health | `POST /api/documents/{id}/retry` requeues a failed document. `GET /api/health` checks database connectivity. |

## 5. Database schema

```mermaid
erDiagram
  DOCUMENTS ||..o{ INVOICES : contains
  DOCUMENTS ||..o{ HISTORY : records
  DOCUMENTS ||--o| SEARCH_VECTORS : indexes
  DOCUMENTS ||..o| DOCUMENT_SEARCH : "indexes logically"

  DOCUMENTS {
    TEXT id PK
    TEXT name
    TEXT suffix
    INTEGER size_bytes
    TEXT sha256
    TEXT status
    INTEGER progress
    TEXT stage
    INTEGER attempt
    REAL lease_until
    TEXT lease_token
    REAL created_at
    INTEGER processing_ms
    TEXT error
    TEXT body
    TEXT warnings "JSON array"
  }
  INVOICES {
    INTEGER id PK
    TEXT document_id FK
    INTEGER position
    INTEGER revision
    TEXT source
    TEXT extraction_method
    TEXT data "Invoice JSON"
    TEXT evidence "Source-quote JSON"
    TEXT duplicate_key
    TEXT issues "Validation JSON"
  }
  HISTORY {
    INTEGER id PK
    TEXT document_id FK
    REAL happened_at
    TEXT event
    TEXT detail "Event JSON"
  }
  SEARCH_VECTORS {
    TEXT document_id PK, FK
    TEXT vector "Sparse feature JSON"
  }
  DOCUMENT_SEARCH {
    TEXT document_id "Unindexed lookup column"
    TEXT body "FTS5 indexed content"
  }
```

| Schema detail | Implementation |
|---|---|
| Invoice identity within a file | `UNIQUE(document_id, position)`. |
| Foreign keys | `invoices`, `history`, and `search_vectors` reference `documents.id` with cascade deletion. The FTS5 link is maintained by indexing code and has no declared foreign key. |
| Supporting indexes | Jobs by `(status, created_at)`, invoices by document and duplicate key, and history by `(document_id, id)`. |
| Invoice JSON | Invoice number, invoice date, supplier, customer, subtotal, tax, total, currency, and a line-item array with description, quantity, unit price, and amount. Decimal values use strings. |
| File storage | The original is stored as `uploads/<document_id><suffix>`. It is referenced by the metadata row and is outside SQLite. |

The authoritative DDL is [app/schema.sql](../app/schema.sql). The request paths are implemented in [app/main.py](../app/main.py), and the lease and processing behavior is in [app/worker.py](../app/worker.py).
