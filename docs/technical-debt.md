# Technical debt register

| Severity | Component | Problem | Risk | Recommended fix |
|---|---|---|---|---|
| medium | Operations execution | Non-fake Producer/Director completion callbacks now reconcile ContentItem state, but render/publication adapters are still not fully owned by Operations | A real autonomous tick can still stop at the existing render/publication boundary | Add idempotent render/publication completion callbacks before enabling unattended publishing |
| high | Permissions | Operations REST service accepts IDs but does not yet apply one uniform project ownership policy | Cross-user access risk if exposed beyond the existing trusted boundary | Introduce a shared authorized project scope dependency and regression tests |
| medium | Retry | Publication, Celery transport and Operations use separate policies | Similar failures can receive inconsistent backoff/attempt semantics | Share error classification and decision value objects while preserving publication timing |
| medium | Progress | Current Telegram watcher is process-local polling | Bot restart does not automatically resume an edit watcher | Add a small notification worker that reads durable message bindings |
| low | Timing | Production timing history is still sparse | ETA is unavailable or low confidence on first runs | Collect real non-fake stage completions and expose confidence/ranges |
