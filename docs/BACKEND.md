# Backend contracts

The React and FastAPI endpoints share an origin. The API index is at /docs and links to the machine-readable contract at /openapi.json. Hosted mode protects both with the reviewer credential. Anonymous readiness reports only service availability.

| Flow | Contract and failure behavior |
|---|---|
| Upload | Multipart field files. HTTP 202 contains per-file acceptance or rejection. Unsupported names, empty inputs and quota exhaustion reject the affected file. Unsupported request framing or excess request size returns an HTTP error before a job is queued. |
| List and detail | Paginated summaries, progress, warnings, extraction, and ordered processing history. An unknown identifier returns 404. |
| Source | Raster previews for supported PDFs and images. Spreadsheet review uses paginated extracted text. Invalid pages, busy rendering, and corrupt files have separate errors. |
| Correction | PATCH uses the current invoice revision. A stale value returns 409, leaving the newer record intact. Reindexing and correction audit commit with the new revision. |
| Reconciliation | Compares explicit invoice identifiers with field-level matches, mismatches, or missing evidence. |
| Search | Keyword filtering uses SQLite FTS. Concept search uses local finance vocabulary and sparse vectors. Both projections update after a correction. |
| Retry | Only failed jobs can return to the queue, within the configured attempt bound. Invalid transitions return 409. |

## Acceptance scenarios

Run unit and API integration tests on fresh data, then a hosted flow with synthetic inputs. Cover batch order and mixed outcomes, scanned and digital PDFs, TIFF and low-contrast images, all spreadsheet formats, empty and unsupported files, encrypted and corrupt inputs, missing values, arithmetic and duplicate flags, both reconciliation pairs, stale corrections, both search modes, failed jobs and retry, expired leases, anonymous access, disallowed origins, malformed framing, quota, and API readiness. Browser checks cover the workflow on desktop and mobile, including preview navigation and correction.
