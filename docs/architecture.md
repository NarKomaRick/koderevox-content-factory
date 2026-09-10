# Content Factory architecture

```text
Content Operations
        │  calendar, policy, budget, capacity, recovery, approval
        ▼
     Producer ── Research / Facts / Assets
        │  compact DirectorHandoffPackage
        ▼
     Director ── Story / Plan / Critics / Timeline revisions
        ▼
     Renderer ── Preview / final media
        ▼
   Approval ── human checkpoint when policy requires it
        ▼
   Publishing ── platform-specific Publication state machine
```

Cross-cutting services are durable Progress, Audit, Recovery, Capacity, Budget, Assets, Research and Permissions. Database rows are the source of truth; Celery is delivery and concurrency infrastructure. Telegram is a notification/control client and does not own domain transitions.

The state levels are intentionally different: ContentItem owns orchestration status, ProducerRun/DirectorRun own runtime status, TimelineRevision owns edit state, VideoProject owns render state, and Publication owns platform delivery state. A status at one level is not copied into another unless a service records an explicit handoff.

## Progress

`JobProgress` is the single current snapshot and `ProgressEvent` is throttled history. Producer and Director report real stage transitions. Fake samples are marked `source_kind=fake` and are excluded from ETA. Telegram edits one stored progress message when the bot is available; API clients can always read the same durable snapshot.

## Boundaries

- Producer owns content meaning and factual handoff.
- Director owns visual staging and timeline operations.
- Renderer owns media execution.
- Publishing owns platform retries and remote status.
- Operations owns scheduling and whether a stage may start.
- Celery tasks load IDs, call services and return results; they are not a second domain layer.
