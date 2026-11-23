# Railway deployment and operation

[Assessment workspace](https://ledger-review-production.up.railway.app/) · [Readiness](https://ledger-review-production.up.railway.app/api/health). Sign in as reviewer using the service's DOCINTEL_REVIEW_PASSWORD variable.

| Surface | Operational contract |
|---|---|
| Public ingress | Railway HTTPS domain serves the browser and API. Anonymous GET /api/health returns readiness; the workspace, documents, search, and API documentation require reviewer credentials. |
| Processing | A supervisor starts Uvicorn and one OCR worker and terminates the sibling if either exits. A later worker may reclaim an interrupted lease. |
| Persistent state | The volume is mounted at /workspace/volume. Startup checks the mount boundary and runs the application under the unprivileged ledger account. |
| Egress | Hosted startup rejects a configured LLM endpoint. The deployed worker only needs the mounted source and database. This is application-level egress control. |

## Release and recovery

1. Confirm the service, volume, generated domain, and secret names in Railway. Keep the value of DOCINTEL_REVIEW_PASSWORD in Railway Variables.
2. Deploy the intended source snapshot and wait for the deployment to become active. Probe /api/health, confirm the root returns 401 anonymously, and check that an authenticated request can read /docs.
3. Exercise a synthetic mixed upload and wait for the background jobs to finish. Verify the scan preview, one correction, one reconciliation, and one expected failure.
4. After a restart or redeploy, open a known synthetic record and its source. If processing stopped, inspect the worker logs and state before retrying. A queued retry against a permanently broken source should fail again.
5. For code regression, select the last verified image in Railway and check backward schema compatibility before redeploying it. For storage corruption, restore a coordinated volume backup and verify source files and search before reopening writes.

The demo has a shared identity and workspace, uses one replica, and limits accepted data. Railway trial availability and quotas apply. Use synthetic documents. Running a purpose-built load test and testing backup restoration, individual access, and parser isolation are separate acceptance steps for a financial-data deployment.

The readiness endpoint was independently probed during acceptance. The CLI-uploaded deployment did not reflect a provider health-check setting in its service manifest. The Docker entry point starts both processes independently of the provider's config-file settings.
