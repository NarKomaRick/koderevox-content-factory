# Technical debt register

| Severity | Component | Problem | Risk | Recommended fix |
|---|---|---|---|---|
| high | Operations execution | Existing Phase 9 path does not yet persist a complete DirectorRun/render/Publication handoff for every non-fake item | A real autonomous tick can stop after Producer without a durable callback into the next stage | Add stage adapters and idempotent completion callbacks before enabling live autonomous starts |
| high | Permissions | Operations REST service accepts IDs but does not yet apply one uniform project ownership policy | Cross-user access risk if exposed beyond the existing trusted boundary | Introduce a shared authorized project scope dependency and regression tests |
| medium | Retry | Publication, Celery transport and Operations use separate policies | Similar failures can receive inconsistent backoff/attempt semantics | Share error classification and decision value objects while preserving publication timing |
| medium | Locking | Operations tick has no PostgreSQL advisory/row lock | Two beat workers can plan concurrently | Add database-specific lock adapter and keep SQLite deterministic fallback for tests |
| medium | Progress | Current Telegram watcher is process-local polling | Bot restart does not automatically resume an edit watcher | Add a small notification worker that reads durable message bindings |
| low | Timing | Production timing history is still sparse | ETA is unavailable or low confidence on first runs | Collect real non-fake stage completions and expose confidence/ranges |
