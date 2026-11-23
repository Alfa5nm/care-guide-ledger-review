# Measured evaluation

The assessment suite used 13 labeled synthetic documents. Eleven valid documents produced 13 invoice records, and two intentionally malformed documents failed as expected. All 102 populated header fields and 52 line-item cells matched the labels exactly. Both expected empty fields stayed empty. The overall completion rate was 84.62% and the failure rate was 15.38%, with 100% completion for valid documents.

| Measurement | Result |
|---|---:|
| Successful Linux worker time, minimum / median / maximum | 26 / 40 / 932 ms |
| 1,000 digital pages, Linux worker / upload to detail | 4,379 / 4,469 ms |
| 1,000 pages with 10 scanned pages, Linux worker / upload to detail | 6,548 / 6,620 ms |
| Invoice records recovered in each large-PDF run | 1,000 |

The November 23, 2026 verification used Linux with the Debian Bookworm application image and Windows with Tesseract 5.4.0. Both matched 13 of 13 invoice records and recovered 1,000 records in each large-PDF benchmark. The Railway API independently matched the same 13 invoice records on 11 valid inputs and failed the two malformed inputs as expected.

The timed evaluation uses the API with a directly invoked worker and excludes background queue wait. The 1,000-page files contain one synthetic invoice per page. These experiments did not measure a fully scanned 1,000-page file, concurrent users, generalization to unfamiliar layouts, or a live external model provider. Model behavior was tested against a simulated endpoint. The corpus and OCR language are English.

See [Linux measurements](evaluation.json), [Windows measurements](evaluation-windows.json), [automated test log](test-results.txt), and [browser verification](browser-results.txt).

The [separate layout and queue report](LAYOUT_EVALUATION.md) covers the frozen synthetic holdout, search relevance, 100-page fully scanned test, and concurrent arrivals.
