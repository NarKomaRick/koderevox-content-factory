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
- Added migration `0011_persistent_progress`.
- Added architecture map, glossary, capability matrix and debt register.

No Phase 6–9 public capability was removed, and no tests were weakened.

## Validation

```text
python scripts/progress_capability_test.py
python -m ruff check .
python -m mypy app
```

The progress capability test covers no-history ETA, real history ETA, fake-history exclusion, approval wait, resume and durable snapshot behavior. Focused progress/operations tests pass; the full suite is `153 passed / 3 skipped` with the same two environment-dependent FFmpeg/espeak failures. Real LLM, web research, vision, FFmpeg and publishing remain untested by design.

## Remaining work

See `docs/technical-debt.md`. The next high-value pass should complete Operations callbacks into real Director/render/publication records and add shared authorization/locking adapters before enabling autonomous production in deployment.
