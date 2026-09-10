# Architecture glossary

- **ContentItem** — Operations-level planned unit. It decides when work may run, not how a video is edited.
- **ProducerRun** — One bounded content-understanding run: intent, research, facts, angle, brief, script and asset requirements.
- **ProductionProject** — Durable Phase 6–8 workspace materialized from a Producer handoff.
- **DirectorRun** — One bounded visual/story orchestration run for a ProductionProject.
- **TimelineRevision** — Immutable validated editing state. The active revision is selected by the production workspace.
- **VideoProject** — Render-oriented media state for the legacy and Phase 4.5 rendering paths.
- **Publication** — One platform-specific publishing operation with attempts/events and its own retry semantics.
- **JobProgress** — Current durable progress snapshot for a long-running job.
- **ProgressEvent** — Throttled stage transition/update history used for restart visibility and ETA samples.
- **OperationsAuditEvent** — Why an operational decision happened; it is not progress and never contains hidden reasoning.
- **ProductionMaterial** — Project-level binding between a source/visual asset and semantic production roles.
- **SourceItem** — User-provided input. It is not automatically a reusable visual asset.
- **VisualAsset** — A media asset that has passed the asset pipeline and can be selected by Director.
