# Storage and schema design

The deployment stores SQLite and original documents below one mounted volume. SQLite runs in WAL mode with foreign keys enabled. The source can be recreated from the [DDL](../app/schema.sql). The [enhanced ER diagram](SYSTEM_DESIGN.md#enhanced-entity-relationship-model) shows ownership.

| Entity | Identity and constraints | Lifecycle |
|---|---|---|
| Document | Generated UUID, accepted format, original display name, size, content hash, status, attempt and lease | Starts queued. The worker claims it in a write transaction; a terminal result clears its lease. |
| Invoice | Integer ID, document foreign key, unique document and position, revision | Structured fields, source evidence, and monotonically increasing correction revision. The duplicate key is a lookup aid and can legitimately have multiple matches. |
| Invoice correction | Invoice foreign key and positive revision as a composite key | Records before/after invoice snapshots in the correction transaction. Existing invoice revisions from schema v1 may precede the introduction of dedicated snapshots. |
| Document history | Integer event ID, document foreign key, event time and detail | Records intake, claim, success, failure, retry, and correction events. |
| Keyword projection | Document identity and searchable body in FTS5 | Rebuilt by processing and by manual correction. |
| Concept projection | Document foreign key as the primary key, sparse concept vector | Rebuilt in the same transaction as the corresponding result. |

The original binary is stored by generated document ID and format. A display filename never determines the stored basename. File writes start in a temporary file and rename before inserting the associated document and submission event. A failed insertion removes the file.

The v2 migration is additive. Startup creates the new correction table and updates SQLite's schema version in one transaction. Newer schema versions fail startup. For recovery, restore the database and original binaries together from the same volume backup. Verify readiness, file previews, and search against a restored copy before resuming writes.

The current demo has a single reviewer workspace. A shared service would need individual identity, workspace-scoped keys and filters, audit actor identity, and storage policies before it accepted live financial data.
