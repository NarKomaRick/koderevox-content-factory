# Technical debt register

| Severity | Component | Problem | Risk | Recommended fix |
|---|---|---|---|---|
| low | Operations execution | Non-fake Producer/Director completion callbacks and publication reconciliation cover the current persisted handoff, while a deployment-specific render callback still depends on the existing renderer integration point | A real autonomous tick may require an adapter if rendering is run by a separate external worker | Add an idempotent renderer completion adapter when the deployment renderer is connected |
| high | Permissions | Operations services now apply actor scoping, but `X-Actor-User-Id` is only a trusted boundary adapter and is not authentication | Cross-user access risk if the API is exposed without an authenticated gateway | Replace the trusted actor header with the project's real auth/permission context before public deployment |
| low | Retry | Publication and Operations retain separate budgets because their stages have different ownership | Backoff tuning can still diverge by stage | Keep stage-specific limits on the shared retry decision helper without merging transport semantics |
| medium | Progress | Current Telegram watcher is process-local polling | Bot restart does not automatically resume an edit watcher | Add a small notification worker that reads durable message bindings |
| low | Timing | Production timing history is still sparse | ETA is unavailable or low confidence on first runs | Collect real non-fake stage completions and expose confidence/ranges |
