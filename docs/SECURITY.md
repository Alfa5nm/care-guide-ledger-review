# Ledger Review threat model

The Railway assessment deployment exposes a shared synthetic-data workspace protected by a generated reviewer password. Assets include originals, extracted text, invoice values, audit events, and the ability to consume parser CPU and disk. The public readiness route reveals only a readiness outcome.

| Trust boundary | Defensive control | Remaining exposure |
|---|---|---|
| Browser to public edge | HTTPS termination, trusted domains, credential gate on UI and API, origin check for browser writes, no-store on protected responses | All authorized reviewers share one workspace and identity. Rotate the demo credential after use. |
| HTTP to storage | Request and file bounds, extension allowlist, generated disk names, per-workspace storage and document quota | Multipart processing consumes bounded temporary space. Uploaded formats remain untrusted even when their names are allowed. |
| Storage to parsers | Non-root worker process, ZIP expansion and image limits, per-page OCR timeout, private source files and raster preview output | Native parsers remain part of the trust boundary. This demo is for synthetic inputs. |
| Job to persisted results | Lease-token fencing, transactionally published results, optimistic revision and correction history | One volume and one replica limit availability. Use volume backups and test restores before relying on this pattern for real data. |
| Document to external services | Railway mode fails closed if model egress is configured. Credentials and document values are excluded from request/response logs. | Local optional model mode transfers extracted text to the operator's configured endpoint. |

Review method: trace actual boundary calls and storage permissions, check fail-closed configuration, and assert authorization, upload limits, and state transitions. References: [OpenAI Codex Security threat modeling](https://github.com/openai/codex-security/blob/main/plugins/codex-security/references/threat-model.md), [Trail of Bits skills](https://github.com/trailofbits/skills), and [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).
