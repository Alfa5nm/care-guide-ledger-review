# Measured evaluation

The assessment suite used 13 labeled synthetic documents. Eleven valid documents produced 13 invoice records, and two intentionally malformed documents failed as expected. All 102 populated header fields and 52 line-item cells matched the labels exactly. Both expected empty fields stayed empty. The overall completion rate was 84.62% and the failure rate was 15.38%, with 100% completion for valid documents.

| Measurement | Result |
|---|---:|
| Successful worker time, minimum / median / maximum | 27 / 39 / 555 ms |
| 1,000 digital pages, worker / upload to detail | 2,673 / 2,759 ms |
| 1,000 pages with 10 scanned pages, worker / upload to detail | 5,346 / 5,436 ms |
| Invoice records recovered in each large-PDF run | 1,000 |

The November 23, 2026 rerun used Windows and Tesseract 5.4.0. The timed evaluation uses the API with a directly invoked worker and excludes background queue wait. The 1,000-page files contain one synthetic invoice per page. These experiments did not measure a fully scanned 1,000-page file, concurrent users, generalization to unfamiliar layouts, or a live external model provider. Model behavior was tested against a simulated endpoint. The corpus and OCR language are English.

See [raw measurements](evaluation.json), [automated test log](test-results.txt), and [browser verification](browser-results.txt).
