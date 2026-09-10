# Architecture consolidation report

## Baseline

Started from `6bd1c52`, Alembic `0010_content_operations`, with `150 passed / 3 skipped` and two environment failures for missing `ffmpeg`/`espeak-ng`. The repository was clean before changes.

## Audit conclusions

The existing architecture already had clear content/runtime boundaries, but progress was fragmented into status strings, step counters and task logs. Operations introduced a second orchestration-level status, correctly distinct from Producer/Director runtime status, but its real-provider stage handoff remains incomplete. No safe broad dead-code deletion was justified: legacy compatibility code is referenced by APIs, Telegram handlers or tests.

## Consolidation performed

- Added one persistent `JobProgress` snapshot and throttled `ProgressEvent` history instead of four incompatible progress models.
- Added a single human-facing stage-label registry.
- Added robust ETA estimation from non-fake completed stage timings; first runs correctly return no ETA.
- Instrumented Producer and both Director entry paths at real stage transitions.
- Added Operations and Producer progress endpoints.
- Added Telegram progress-message binding and same-message edit watcher with terminal/error/waiting states.
- Added a small read-only `CapabilityRegistry` for feature flags and local renderer/connector availability.
- Added stage-specific stale recovery using durable progress heartbeats and a PostgreSQL advisory-lock/SQLite fallback for Operations ticks.
- Added idempotent Producer and Director completion callbacks so non-fake runs reconcile back into the ContentItem state machine.
- Reused the existing bounded retry decision helper for Operations and persisted `next_retry_at`; fake runs remain immediate and deterministic.
- Added migration `0011_persistent_progress`.
- Added migration `0012_operations_retry_backoff` for durable bounded retry scheduling.
- Added publication completion reconciliation without changing the existing publishing service.
- Added architecture map, glossary, capability matrix and debt register.

No Phase 6–9 public capability was removed, and no tests were weakened.

## Validation

```text
python scripts/progress_capability_test.py
python -m ruff check .
python -m mypy app
```

The progress capability test covers no-history ETA, real history ETA, fake-history exclusion, approval wait, resume and durable snapshot behavior. Focused progress/operations, locking, recovery, retry and ownership tests pass; after installing the user-local media tools, the full suite is `166 passed`. The real FFmpeg render and eSpeak TTS tests now pass on this host. Real LLM, web research, vision and publishing remain untested by design.

## Remaining work

See `docs/technical-debt.md`. The remaining deployment work is an authenticated project-scope adapter and a durable Telegram notification worker; the code now has trusted actor scoping, durable retry scheduling, tick locking, stage callbacks and publication reconciliation.

## Post-reboot container validation

On 2026-09-10 Docker Desktop was recovered from a Windows stale AF_UNIX socket failure by rotating only the Docker Desktop runtime socket directories and disabling the unused Docker AI listener; images, volumes and project data were preserved. The current checkout was rebuilt and the local Compose stack was recreated. API startup applied migrations `0007` through `0012`, and Alembic confirmed `0012_operations_retry_backoff (head)`. API, worker, render-worker, publish-worker and publish-scheduler healthchecks passed; `/health` returned 200.

The Telegram profile was intentionally left stopped because its configured external proxy `host.docker.internal:2081` is not listening on this host. Telegram delivery and real publishing therefore remain untested. The host full suite remains `166 passed`; operations and progress capability smokes also passed after the reboot.
