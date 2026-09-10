# Phase 9 — Autonomous Content Operations

## Baseline

Phase 9 was started from the clean `main` baseline `b63e244` (`feat: add autonomous producer and research engine`). The previous Alembic head was `0009_autonomous_producer`; the next migration is `0010_content_operations`.

Phase 6–8 runtimes remain the source of truth for Director and Producer behavior. Real LLM, live web research, vision, FFmpeg and espeak-ng are not claimed as tested here.

## Architecture

The new operations layer is deterministic and bounded. `ContentStrategy` stores stable channel rules, `ContentStrategyPillar` stores weighted pillars, and `ContentItem` is the operational unit above `ProducerRun`, `ProductionProject`, Director and publishing. Campaigns, series, dependencies, approvals and audit events are durable records.

`ContentPlanner` fills a finite timezone-aware horizon and uses idempotency keys per strategy/slot. Weighted pillar scoring includes recent pillar repetition and campaign allow-lists. `FakeStrategist` supplies deterministic topic hints; it does not perform Producer research.

`StudioOrchestrator.run_once()` performs recovery, bounded planning, dependency checks, budget/capacity decisions and stage execution. Operational transitions are performed by code, not by an LLM. `ExecutionCoordinator` calls the existing Phase 8 fake Producer path and represents the Director/render handoff in dry-run mode. `ApprovalManager` and `RecoveryManager` preserve normal waiting and failure states instead of treating them as exceptions.

## Safety and controls

- `OPERATIONS_ENABLED=false` and `OPERATIONS_AUTO_PUBLISH=false` are safe defaults.
- Dry-run uses real database state transitions with SQLite-compatible models and fake providers.
- Capacity, item limits, stale timeouts, retries and daily LLM budgets are Settings-backed.
- Cancellation preserves runs and artifacts. Approval decisions are idempotent.
- Audit entries record concise rationale, not hidden model reasoning or credentials.
- Celery receives IDs through the `content_factory.operations.tick` periodic task; database state remains the source of truth.

## API and scheduling

The `/operations` API provides strategy, campaign, series, item, calendar, status, planning and approval endpoints. The periodic task is configured through `OPERATIONS_TICK_INTERVAL_SECONDS`; no worker loop is embedded in business logic. The operations kill switch prevents autonomous starts while allowing existing work to finish according to the current policy.

The existing publishing subsystem is not rewritten. With auto-publish disabled, an approved item remains `ready_to_publish` until an explicit publishing policy/task handles it.

## Offline capability

Run:

```text
python scripts/operations_capability_test.py
```

The smoke creates one strategy with a 14-day horizon, plans six bounded items, executes fake Producer/Director/render transitions, exercises a temporary retry, an approval, cancellation, idempotency and audit persistence. Artifacts are written to a temporary directory and are not repository data.

The Phase 9 tests pass offline (`3 passed` in the focused operations suite; the full suite reached `153 passed, 3 skipped`). The full suite still reports two pre-existing environment-dependent failures because `ffmpeg` and `espeak-ng` are not installed on this deployment; they are not Phase 9 regressions.

Current real capability status is intentionally conservative:

```json
{
  "fake_producer": "passed",
  "real_producer": "not_tested",
  "real_director": "not_tested",
  "real_render": "not_tested",
  "real_publish": "not_tested",
  "real_llm": "not_tested",
  "real_web_research": "not_tested",
  "research_provider": "fake"
}
```

## Known limitations

The first operations slice deliberately keeps the orchestrator provider-neutral and offline. Production deployment still needs a connected operations worker, real queue-backed Director/render coordination, platform-specific approval UX, distributed locking appropriate for the deployment database, and live provider validation. Analytics, ML forecasting and real social publishing are outside Phase 9.
