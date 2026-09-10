# Phase 8 — Autonomous Producer & Content Research Engine

## Baseline and scope

- Baseline: `e63a877 feat: add autonomous director intelligence`.
- Alembic head was checked before migration: `0008_autonomous_director`.
- Added migration: `0009_autonomous_producer`.
- Director runtime, Phase 6/7 tables, publishing services and publication pipeline were not rewritten.

## State machine

`created → understanding_goal → researching → verifying → planning_angle → building_brief → writing_script → reviewing_script → planning_assets → creating_production → completed`.

`failed` and `cancelled` are terminal run states; approval mode uses `approval_state=pending|approved` while retaining the agreed status list. Each stage writes its JSON artifact before committing the next stage, so resume reuses saved artifacts and does not repeat research.

## Research, provenance and facts

`ResearchProvider` exposes `search`, `fetch`, and `extract`. `ControlledResearchRuntime` enforces query/source/fetch/byte limits. Direct fetch uses the existing SSRF-safe `LinkProcessor` for HTTP/HTTPS, redirects, MIME and response-size checks; pure preflight blocks file/ftp/localhost/private literal addresses. HTML extraction is bounded and strips executable/navigation content. Source content is marked untrusted and never used as Producer instructions.

`research_sources` cache canonical URLs, content hashes, extractor versions, timestamps, stale flags and injection metadata. `research_facts` and `research_fact_sources` preserve provenance. Duplicate URLs, hashes and highly similar extracted text reuse cached sources. Critical stale/conflicting claims block strict-factuality completion.

## Content layers and handoff

Typed domain models cover intent, topic candidates, research plans/facts/conflicts, angles, briefs, scripts/reviews, assets, handoff and reports. `FakeProducerModel` is deterministic and offline. `StructuredProducerModel` uses the existing `AIProvider` structured contract.

`ContentChannelProfile` and `ProducerPreferenceResolver` support channel profiles and the `producer.*` namespace on existing `DirectorPreference`; project brand context/audience/preset are fallbacks. History is read from ProducerRun and ProductionProject artifacts for semantic duplicate-angle avoidance.

`ProductionBuilder` creates the real `ProductionProject`, `ScriptVersion`, verified `ProductionFact` materializations and semantic asset requirements. The compact Director handoff contains brief, script, verified facts, story intent, asset requirements, brand/channel/output profiles and source references; it does not pass the HTML corpus or select exact clips.

## API, Celery and Telegram

- `POST /producer/runs`
- `GET /producer/runs/{id}`
- `POST /producer/runs/{id}/cancel`
- `POST /producer/runs/{id}/resume`
- `POST /producer/runs/{id}/approve` (explicit approval-mode continuation)
- `GET /producer/runs/{id}/report`

HTTP only persists/enqueues. Producer work runs in the separate `producer` Celery queue. Telegram adds `✨ Создать ролик`; legacy `🎬 Новый ролик` is unchanged. Updates are stage-level, not per tool call.

## Security and configuration

Defaults are offline and opt-in: `PRODUCER_ENABLED=false`, bounded producer limits, strict factuality enabled. Debug artifacts contain no credentials, cookies, authorization headers, Telegram tokens or private media assets.

## Verification

- `python scripts/autonomous_producer_test.py --fake`: passed.
- Reported capability statuses: real producer `not_tested`, real research `not_tested`, real video pipeline `not_tested`, provider `fake`.
- `python -m ruff check app scripts`: passed.
- `python -m mypy app`: passed.
- Phase 8 tests: passed.
- Full pytest: 148 passed, 3 skipped; 2 environment-dependent failures because `ffmpeg` and `espeak-ng` are unavailable on this host. Those are not marked passed.

## Limitations

Phase 8 intentionally has no live web-search backend or required external credentials. Controlled direct URL fetch is available through the provider contract and safe LinkProcessor path. Real LLM, live research and real video capability remain untested until those environments are explicitly available.
