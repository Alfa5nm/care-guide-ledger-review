# Measured evaluation

The labeled evaluation sent 13 synthetic documents through the upload API, persisted the resulting jobs, processed them with the local worker, and fetched the results from the API. There were 11 valid inputs and two deliberately malformed ones. The valid files contained 13 invoice records across different formats.

## Extraction and document outcomes

| Measure | Result |
|---|---:|
| Present invoice header values matched exactly | 102/102 · 100% |
| Expected empty header fields left empty | 2/2 · 100% |
| Expected line-item cells matched exactly | 52/52 · 100% |
| Complete invoice records matched exactly | 13/13 · 100% |
| Missing or extra invoice records | 0 |
| All submitted documents completed | 11/13 · 84.62% |
| Valid documents completed | 11/11 · 100% |
| All submitted documents failed | 2/13 · 15.38% |
| Deliberately malformed documents correctly failed | 2/2 · 100% |
| Successful worker time, minimum / median / maximum | 2 / 6 / 375 ms |

The corpus contains digital PDFs, a scanned PDF, a low-contrast JPG, a PNG, a multi-frame TIFF, a two-page invoice, a partial invoice, a CSV, a two-sheet XLSX, and a legacy XLS. The two invalid inputs are a corrupt PDF and a malformed CSV. Present values were scored against normalized labels. Expected missing fields were scored separately. Line items were compared in source order, and missing and extra records were counted separately.

## Large-PDF benchmarks

| PDF | Invoice records | Worker time | Upload through detail response |
|---|---:|---:|---:|
| 1,000 digital pages | 1,000 | 872 ms | 889 ms |
| 990 digital pages and 10 scanned pages | 1,000 | 2,618 ms | 2,635 ms |

Each benchmark used one fictional invoice per page. The second benchmark triggered OCR on ten raster pages. Worker time excludes queue wait. The last column measures upload, direct invocation of one worker run, and initial detail retrieval. It excludes document generation and the idle polling delay in a separately launched worker.

## Test and browser coverage

Fifteen automated tests passed. The suite checks processing, real OCR, legacy Excel intake, model request and evidence handling with a simulated endpoint, arithmetic validation, missing data, retry, worker lease recovery, upload restrictions, duplicate detection, reconciliation, optimistic correction, and search.

A separate Chromium run exercised upload, OCR invoice review, validation, PDF-to-PDF and PDF-to-Excel reconciliation, correction, failed-job retry, keyword and concept search, and the mobile-width layout.

The dataset is small, fictional, English-language, and contains labeled layouts. Accuracy figures apply to these fixtures. They do not estimate performance on real invoices, unfamiliar layouts, or a fully scanned 1,000-page PDF. A live external LLM and multi-user load were outside the measured runs. See the [raw evaluation results](evaluation.json) for per-field and per-file scores and the [test log](test-results.txt) for named test cases.
