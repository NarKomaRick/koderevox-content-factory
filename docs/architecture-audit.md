# Architecture Audit — Phase 6–9

## Baseline

- Commit: `6bd1c52 feat: add autonomous content operations`
- Alembic head: `0010_content_operations`
- Tests: `150 passed`, `3 skipped`; two environment-dependent failures remain when `ffmpeg` and `espeak-ng` are unavailable.
- No uncommitted user changes were present at audit start.

## Actual map

| Layer | Entry points | State owner | Main dependencies |
|---|---|---|---|
| Operations | `/operations/*`, `StudioOrchestrator`, `operations_tick` | `ContentStrategy`, `ContentItem`, approvals and audit | Producer service, queues, publication contracts |
| Producer | `/producer/runs`, `ProducerService`, `ProducerRuntime`, `run_producer` | `ProducerRun` and its JSON artifacts | AI provider, controlled research, ProductionBuilder |
| Director | production API, `DirectorRunService`, `DirectorAgent`, `AutonomousDirector` | `DirectorRun`, timeline revisions | Director tools, critics, asset ranking, render service |
| Editing/timeline | `DirectorRuntime`, `TimelineRevisionService`, editing DSL | immutable `TimelineRevision` plus active project pointer | layout, graphics, validation |
| Rendering | render APIs/tasks and `ProductionRenderService` | `VideoProject`/render fields | FFmpeg, local storage |
| Research | `ControlledResearchRuntime`, `LinkProcessor` | `ResearchSource`, `ResearchFact`, provenance links | fake provider or SSRF-safe fetch |
| Assets | `AssetService`, clip finder/ranker, `VisualAsset`, `ProductionMaterial` | asset/project material rows | local storage, OCR/vision, optional web assets |
| Publishing | publishing API, `PublicationService`, scheduler/tasks | `Publication` and attempts/events | publisher registry, credentials, platform APIs |
| Telegram | aiogram handlers, `BackendClient`, preview delivery | FSM is UX state only; backend owns domain state | REST API and Telegram API |
| Celery | thin-ish task modules plus queue adapters | database rows, not task result state | Redis broker/backend |
| Persistence | SQLAlchemy models, Alembic, async session factory | database is source of truth | PostgreSQL in deployment, SQLite in tests |

## Findings and decisions

### Retry

`RetryPolicy` is the mature publication-specific policy; Celery `max_retries`, Processing retries and Operations retry counters are transport/domain layers with different owners. They are not interchangeable. Decision: keep publication policy for publication, keep Celery retry as delivery protection, and introduce a shared `RetryDecision` contract for new cross-pipeline work rather than silently rewriting stable Phase 5 behavior.

### State ownership

`ProducerRun`, `DirectorRun`, `VideoProject`/render state, `Publication` and `ContentItem` represent different semantic levels. They must not be collapsed. `ContentItem` owns orchestration state; each lower-level runtime owns its own execution state. The audit found that the Operations happy-path currently lacks complete durable links for Director/render/publication, so this remains a documented high-priority integration debt rather than being hidden by mirrored statuses.

### Progress

Before this pass, `step_count` and stage strings existed, but no common persisted snapshot, timing history, ETA policy or Telegram message identity existed. This is the main consolidation target. The implementation below adds one cross-pipeline progress model; it does not expose model reasoning or fabricate token percentages.

### Permissions

Existing Telegram access middleware protects the bot, while many REST services accept project/user IDs as input. Operations ownership checks are not yet a uniform application-wide authorization layer. This is explicitly documented as hardening debt; no endpoint is described as production-secure solely because it validates UUIDs.

### Assets and handoff

`SourceItem` is user input, `VisualAsset` is a media asset, `ProductionMaterial` binds project roles to input/assets, and `AssetSegment` is a time range inside media where present. Producer passes compact handoff data through `ProductionProject.production_context`; Director reads bounded project context and never receives the full research corpus.

### Celery and sessions

Tasks generally load IDs and call services, but transaction boundaries are not fully uniform: Producer/Director runtimes commit stage artifacts internally, while task modules own session lifetime. This is retained for compatibility and recorded for future transaction consolidation. No task result is treated as source of truth.

## Safe cleanup decisions

- KEEP legacy Phase 4/5 compatibility paths: tests and Telegram handlers still reference them.
- KEEP separate Producer and Director domain models: they answer different questions.
- KEEP publication retry policy: it encodes platform-specific retry timing and must not be replaced by Operations counters.
- MERGE new progress reporting through one service/model, with adapters at each runtime.
- DEPRECATE no public endpoint in this pass; removal without a complete reference/task/callback audit would be unsafe.

## Remaining high debt

1. Complete durable Operations → DirectorRun → render → Publication linking and callbacks.
2. Add uniform ownership/permission policy for Operations REST services.
3. Unify cross-stage retry classification without changing publishing semantics.
4. Add real deployment locking for operations ticks; SQLite fallback remains test-only.
5. Collect production-only timing samples; fake runs must not feed ETA history.
