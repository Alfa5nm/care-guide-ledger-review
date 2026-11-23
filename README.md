# Ledger Review

A local document intelligence application for financial documents. Upload PDFs, scans, images, spreadsheets, and CSVs, then review extracted invoices, correct errors, and compare records across files.

## Run locally

Install Python 3.12, Node.js 22 or newer, and Tesseract with English language data. On Debian or Ubuntu the OCR packages are `tesseract-ocr` and `tesseract-ocr-eng`. On Windows, add the directory containing `tesseract.exe` to PATH and check `tesseract --version`.

From the repository root:

```sh
python -m venv .venv
```

On Windows PowerShell, activate with `./.venv/Scripts/Activate.ps1`. On macOS or Linux, use `source .venv/bin/activate`. If PowerShell blocks activation, use `./.venv/Scripts/python.exe` in place of `python`.

```sh
python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
python -m tools.run
```

The handoff archive includes a prebuilt frontend under `frontend/dist`. If you use the archive, you can skip the npm commands. A Git checkout builds the frontend from the locked dependencies.

Open [Ledger Review](http://127.0.0.1:8000) or [API docs](http://127.0.0.1:8000/docs). The app starts in local mode without credentials. Its generated SQLite database and private uploads live under `data/`. Set `DOCINTEL_DATA` to use a different directory. Stop both processes with Ctrl+C.

A Docker configuration is also provided. Run `docker compose up --build` and open the same address. The named volume persists jobs and documents. The API is published on the host loopback.

## Railway assessment demo

The Railway configuration runs one protected service with a supervised OCR worker and a persistent volume. Connect a volume at `/workspace/volume`, set `RAILWAY_RUN_UID=0` for the mount bootstrap, set `PORT=8000`, and generate a Railway public domain. Before deploying, store a random reviewer password of at least 24 characters as `DOCINTEL_REVIEW_PASSWORD`. Set it through Railway Variables and keep it out of the repository. The container starts the API and worker as the unprivileged ledger account after preparing the mounted data directory.

Open the deployment with user `reviewer` and the Railway Variables password. The service uses HTTPS and accepts synthetic assessment data. The public readiness endpoint is `/api/health`. The authenticated API reference is `/docs`. Use a Railway volume backup before a change that affects storage. See the [system design](docs/SYSTEM_DESIGN.md), [backend contracts](docs/BACKEND.md), and [security model](docs/SECURITY.md) for the deployment boundary.

The Compose services run as a non-root user with read-only root filesystems, dedicated temporary storage, and dropped Linux capabilities. The worker starts after the API health check succeeds. The health check verifies SQLite connectivity.

For a shared deployment, put the service behind TLS and authenticated access, isolate document rendering from the API process, and establish per-user document authorization, upload rate limits, retention, backup and restore, and monitoring. Test those controls and measure workload capacity before exposing financial documents to other users.

## Try the workflow

```sh
python -m tools.fixtures
```

1. Upload `01-original-invoice.pdf`, `02-conflicting-copy.pdf`, `03-scanned-invoice.pdf`, `10-billing-workbook.xlsx` and `12-corrupt.pdf` from `artifacts/samples`.
2. Open the scanned invoice to check OCR against the original in **Source preview**. Select **Expand** to see the page alongside extracted fields and evidence quotes. Use the page input or arrow keys to navigate the expanded viewer, **Rotate** to correct viewing orientation, and **Escape** to close. The preview supports PDF pages and image frames. Spreadsheets use **Extracted text**. Open the conflicting copy to see its arithmetic and duplicate flags.
3. In the conflicting copy, select **Reconcile** and compare `CG-1001` against the original PDF or the workbook. Each comparison reports the identity check and equality, mismatch, or missing evidence per field.
4. Edit the conflicting document’s total to `110` and save. The arithmetic flag clears. The duplicate flag remains because the supplier and invoice number still match another record.
5. Search for `freight` in semantic mode to find an invoice that says `Shipping fee`. Select keyword mode to compare literal filtering.
6. Retry the corrupt PDF and expand **Processing history**. The new attempt is recorded and the same corrupt file fails again.

## Extraction behavior

Digital pages retain their text. Scanned pages use local OCR with grayscale conversion, autocontrast, and optional upscaling. Multipage PDFs are segmented at a detected new invoice identifier. Multi-frame TIFFs and workbook sheets are processed individually. Table exporters can provide one invoice row or repeat the invoice header across line-item rows.

A structured local extractor recognizes field labels and supported headers, then normalizes dates, amounts, and currency codes. Ambiguous or unsupported values are left empty and flagged. Financial checks use Decimal arithmetic and a tolerance of 0.01. The application keeps extraction evidence and correction history. Search indexes source text and current corrections.

For an optional model-assisted pass, set `DOCINTEL_LLM_URL` to an OpenAI-compatible chat-completions endpoint, `DOCINTEL_LLM_MODEL` to its model ID, and `DOCINTEL_LLM_KEY` if required. Configure these on the worker. The model can propose missing fields from unstructured document segments. Each accepted proposal must include an exact substring from the source, and locally extracted fields take precedence. A quote verifies that text exists in the document. Its relationship to the requested field can still need review. See [model prompt and disclosure](docs/AI_USAGE.md).

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Confirm database connectivity |
| POST | `/api/documents` | Upload up to 12 files as multipart field `files` |
| GET | `/api/documents` | List jobs and progress with optional status filter and pagination |
| GET | `/api/documents/{id}` | Get document status, first invoice page, warnings and history |
| GET | `/api/documents/{id}/invoices?offset=0` | Get up to 100 invoice records per page |
| GET | `/api/documents/{id}/text?offset=0` | Read extracted source text in chunks |
| GET | `/api/documents/{id}/preview/{page}?rotation=90` | Render a 1-indexed PDF page or image frame as bounded PNG, optionally rotated in 90-degree steps. Returns `X-Page-Count`. |
| PATCH | `/api/invoices/{id}` | Apply a revision-checked correction with `{"revision":0,"changes":{"total":"110"}}` |
| POST | `/api/documents/{id}/retry` | Requeue a failed document |
| GET | `/api/search?q=freight&mode=semantic` | Search by terms or concepts |
| GET | `/api/reconcile?left=1&right=2` | Compare two selected invoice IDs |

## Verify

```sh
python -m unittest discover -s tests -v
python -m tools.evaluate --out artifacts/evaluation.json
```

The verification scripts use synthetic inputs, a fresh temporary database, and local extraction. The OCR tests run the Tesseract executable. Review the [evaluation](docs/EVALUATION.md), [raw results](docs/evaluation.json), [test output](docs/test-results.txt), [browser results](docs/browser-results.txt), and [architecture and schema](docs/ARCHITECTURE.md). The [browser walkthrough script](tools/browser_walkthrough.py) can reproduce UI checks against a fresh local instance when Python Playwright and Chromium are installed.

## Operating limits

The app is designed for a trusted single-user workstation. The worker and API share local SQLite with WAL, atomic job claims, expiring leases, and transactionally stored results. Filenames are normalized and originals are stored privately by random ID. Upload requests, file sizes, pages, text, spreadsheet rows, image pixels, and individual OCR executions have limits. OpenPyXL receives defused XML support. The service binds to loopback in the local launcher and Docker host port. External model mode sends text to the configured service.

Limits include 12 files per request, 150 MiB per request, 64 MiB per file, and up to 2,000 PDF pages or TIFF frames per file. Language support and invoice segmentation were evaluated on English fixtures. The local rule path works with labeled templates and leaves unfamiliar layouts for review. It accepts ISO-style dates and period-decimal amounts with optional comma grouping. Workbook formulas are read from cached results, and formulas with missing cached results may leave fields empty. Concept search ranks a small finance vocabulary through sparse vectors and cosine similarity. The 1,000-page benchmarks cover a digital PDF and a mostly digital PDF with 10 scanned pages. A fully scanned long PDF incurs OCR cost per page.

A shared deployment would need authentication and authorization, isolated parsers, retention controls, and a shared job/data store. SQLite and filesystem storage suit a local reviewer workflow. The benchmark does not establish multi-user production capacity.

## Assessment deliverables

See the [submission index](docs/SUBMISSION.md) for the architecture, schema, measured evaluation, test logs, AI disclosure and current captioned walkthrough.
