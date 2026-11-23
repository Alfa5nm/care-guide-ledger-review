# Care Guide assessment deliverables

| Deliverable | Location |
|---|---|
| Source and setup | [README](../README.md), `app/`, `frontend/`, `requirements.txt`, and `compose.yaml` |
| Architecture, EER, class diagram and database schema | [System design](SYSTEM_DESIGN.md), [storage design](SCHEMA.md) and [SQLite DDL](../app/schema.sql) |
| Backend API and security | [Contracts and acceptance scenarios](BACKEND.md), [threat model](SECURITY.md), and the running application's /docs |
| Hosting and operation | [Railway runbook](RAILWAY.md) |
| Automated tests and results | `tests/`, [test log](test-results.txt), and [browser verification](browser-results.txt) |
| Measured evaluation | [Report](EVALUATION.md), [layout holdout and queue results](LAYOUT_EVALUATION.md), [Linux results](evaluation.json), [Windows results](evaluation-windows.json), and [hosted corpus results](hosted-smoke.json) |
| Railway walkthrough | [Guided exception review](../demo/Ledger_Review_Guided_Review.mp4) and [full captioned walkthrough](../demo/Ledger_Review_Assessment_Walkthrough.mp4) |
| AI use and prompts | [Disclosure](AI_USAGE.md) |

The workspace runs locally against its own data directory. Sample documents in the walkthrough are synthetic. The reconstructed commit sequence starts with the [concept](CONCEPT.md) and architecture, then imports the archived working baseline before layering the later changes. Each commit records the actual assembly date.
