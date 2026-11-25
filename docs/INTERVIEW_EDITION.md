# Ledger Review interview edition

The interview edition extends the original invoice extraction assessment through the point where a reviewer can hand an approved batch to accounting. The walkthrough follows two synthetic copies of invoice CG-1001. The original supports USD 110, and the second copy initially extracts USD 115.

## Reviewer flow

1. Open the conflicting copy and compare it with the original. Reconciliation shows the conflicting total first.
2. Follow the validation flag to review its source evidence and enter the corrected value. The correction creates a revision and shows which validation check cleared.
3. Resolve the duplicate group. Keep the original and record the reason. The decision stores the exact group member revisions.
4. Approve the canonical record. Open **Exports**, create a batch and download the one-row CSV. Return to **Exports** to download the same bytes later.

If a correction or a newly processed invoice changes group membership before export, review and approval must be repeated. The exporter reserves each normalized identity transactionally. Exported invoices reject corrections. Text values that could be interpreted as spreadsheet formulas are prefixed for safe CSV import.

## Review evidence

| Check | Result |
|---|---|
| Synthetic extraction holdout | 26 of 28 documents exact, with one incorrect acceptance and one abstention |
| Correctness checks | Stale group and invoice revisions, membership changes, correction invalidation, approval, concurrent exports, spreadsheet-safe text, and late duplicate rejection |
| Storage checks | Additive v2 upgrade and byte-identical download after reopening the app |
| Browser walkthrough | Flag, comparison, source correction, duplicate exclusion, approval, one-row CSV, and byte-identical re-download |

The holdout measures extraction on synthetic inputs. The interview workflow uses one trusted reviewer workspace and stages a CSV. See the [backend contracts](BACKEND.md), [schema and migration](SCHEMA.md), [system design](SYSTEM_DESIGN.md), and [layout evaluation](LAYOUT_EVALUATION.md).
