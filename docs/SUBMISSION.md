# Care Guide assessment deliverables

| Deliverable | Location |
|---|---|
| Source and setup | [README](../README.md), `app/`, `frontend/`, `requirements.txt`, and `compose.yaml` |
| Architecture and database schema | [Mermaid diagrams](ARCHITECTURE.md) and [SQLite DDL](../app/schema.sql) |
| Automated tests and results | `tests/`, [test log](test-results.txt), and [browser verification](browser-results.txt) |
| Measured evaluation | [Report](EVALUATION.md) and [raw results](evaluation.json) |
| Current walkthrough | [Download the captioned MP4](../demo/Ledger_Review_Walkthrough.mp4) |
| AI use and prompts | [Disclosure](AI_USAGE.md) |

The workspace runs locally against its own data directory. Sample documents in the walkthrough are synthetic. The reconstructed commit sequence starts with the [concept](CONCEPT.md) and architecture, then imports the archived working baseline before layering the later changes. Each commit records the actual assembly date.
