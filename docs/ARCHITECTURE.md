# Architecture outline

```mermaid
flowchart LR
    Browser["React reviewer workspace"] --> API["FastAPI"]
    API --> Store[("SQLite queue and results")]
    API --> Uploads["Original file storage"]
    Store --> Worker["Background processor"]
    Uploads --> Worker
    Worker --> Store
```

Keep original files outside the static frontend directory. Store job state, extracted invoices, history and search indexes in SQLite. Use a separate background worker for parsing and OCR, and retain an audit record for reviewer corrections.
