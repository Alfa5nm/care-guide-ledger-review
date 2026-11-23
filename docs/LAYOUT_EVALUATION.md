# Synthetic layout holdout and queue evaluation

Thirty labeled files across five layout families were frozen before the extraction edits. The stored manifest records the expected values and SHA-256 of each input. Development regression tests use separate examples. The holdout is synthetic and was designed by the same project team. Its results measure these layout variations and do not establish accuracy on independent customer documents.

| Metric | Previous implementation | Release candidate |
|---|---:|---:|
| Exact invoice matches | 15/28 | 26/28 |
| Field precision | 99.67% | 99.70% |
| Field recall | 90.72% | 99.40% |
| Wrong populated values | 1 | 1 |
| Populated values where the label is blank | 0 | 0 |
| Abstentions where the label is populated | 30 | 1 |
| Malformed inputs rejected | 2/2 | 2/2 |

Precision is exact populated matches divided by all populated predictions. Recall is exact populated matches divided by all expected populated cells. Both include line items. Exact invoice match requires all expected fields and line items to match, including blank values.

| Layout family | Exact matches before | Exact matches after |
|---|---:|---:|
| Reordered item columns | 0/6 | 6/6 |
| Regional dates and currency | 0/6 | 5/6 |
| Spatially separated labels and values | 6/6 | 6/6 |
| Faint scanned pages | 5/6 | 5/6 |
| Continuation pages | 4/4 | 4/4 |

The two remaining misses were surfaced for review. The ambiguous date 12/08/2026 stayed blank, and the OCR engine read one total of 90 as 98, triggering the arithmetic discrepancy flag. The 13 original labeled invoices still matched on Windows and Linux.

## Search comparison

Six literal queries and six paraphrases were scored against labeled relevant documents. Each row reports the total relevant documents in the top five results per query, summed across the six queries. Each query group has 28 relevant results. The concept vocabulary recognizes several of the tested paraphrases by design, so this is a small functional comparison.

| Method | Literal hits | Paraphrase hits |
|---|---:|---:|
| Keyword search | 28/28 | 0/28 |
| Concept search | 28/28 | 23/28 |

## Queue and fully scanned file

The Linux application image processed a fully scanned, 100-page file into 100 invoice records in **47.0 seconds** of worker time, after 42 ms in the queue. Four small uploads were accepted concurrently while the scan was processing. They completed without timeout, with upload response times of 40–58 ms, worker times of 28–43 ms, and queue waits of 46.98–47.11 seconds. A long scan therefore delays smaller jobs on the single-worker demo. This test measures processing and queue behavior, not per-field accuracy on the long scan or production throughput.

Reproduce the layout test with `python -m tools.holdout tests/fixtures/holdout --out artifacts/holdout-results.json` after creating the artifacts directory. Reproduce the queue check with `python -m tools.stress --out artifacts/stress.json`.

[Frozen manifest](../tests/fixtures/holdout/manifest.json) · [Baseline results](holdout-baseline.json) · [Candidate results](holdout-results.json) · [Queue results](stress-results.json)
