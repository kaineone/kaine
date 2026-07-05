## 1. Workspace-following observer base

- [x] 1.1 Add `WorkspaceSubscriberObserver` in `kaine/evaluation/_base.py`:
      follows `workspace.broadcast` via `bus.subscribe_workspace(last_id=...)`,
      dispatches the decoded snapshot **payload dict** to `handle(entry_id,
      payload)`. Handler exceptions are logged, never fatal. (Races each
      `__anext__` against the stop event so shutdown stays immediate — the
      generator blocks when idle, so a plain `async for` would only stop on a
      5s cancel.)
- [x] 1.2 Extend the `BusReader` protocol with `subscribe_workspace`; the real
      `AsyncBus` already implements it.

## 2. Repoint trajectory + attribution

- [x] 2.1 `TrajectoryRecorder` extends `WorkspaceSubscriberObserver`; `handle`
      takes `(entry_id, payload)` and reads `payload[...]` (tick_index,
      is_experiential, inhibited, salience_scores, selected, metadata) — same
      fields as today, sourced from the decoded snapshot.
- [x] 2.2 `AttributionRecorder` extends `WorkspaceSubscriberObserver` likewise.
- [x] 2.3 Confirm no other observer wrongly follows `workspace.broadcast` via the
      Event decoder. (Only trajectory + attribution did.)

## 3. Wire memory_source + cognitive_query_client at the entrypoint

> Done after `condition-language-organ` landed. The `cognitive_query_client` is a
> memory-augmented LLM query (recall from Mnemos, then ask the model) — the real
> stack's answer with memory, distinct from the bare baseline — built as an
> entrypoint adapter so `kaine.evaluation` imports no `kaine.modules.*`.

- [x] 3.1 `memory_source` adapter over Mnemos (`_memory_source_factory` in
      `cycle/__main__.py`; best-effort age sampling — storage has no age scroll,
      so it recalls + filters by timestamp and returns None when none old enough).
- [x] 3.2 `cognitive_query_client` over the real stack
      (`_cognitive_query_client_factory`: Mnemos recall + LLM).
- [x] 3.3 Pass both into `SidecarRegistry(...)`; `memory_probes` + `eidolon_accuracy`
      now instantiate when enabled.

## 4. Tests

- [x] 4.1 Fake bus with `subscribe_workspace` (async gen over canned
      `(entry_id, snapshot_dict)`); `TrajectoryRecorder` writes one row per
      broadcast with the expected fields.
- [x] 4.2 Regression: feed the exact live shape via the real bus
      (`publish_workspace`) and assert a row is written; assert the standard
      `read_entries` path yields nothing (guards the found bug).
- [x] 4.3 `AttributionRecorder` tallies sources and flushes a partial-hour
      rollup on stop.
- [x] 4.4 Registry memory_probe/eidolon count test (deferred with §3).
- [x] 4.5 Import-isolation: the new observer base imports no `kaine.modules.*`
      (covered by the existing phase-9 no-runtime-external-calls / import test;
      the new code touches only the bus protocol).

## 5. Docs

- [ ] 5.1 Note in the eval tab / docs that `memory_probes` (hourly) and
      `eidolon_accuracy` (daily) populate on a schedule — an empty card in a
      short session is "not yet due", not broken — and that `voice_tracking` /
      `sleep_snapshots` require Hypnos. (Do alongside the §3 wiring.)

## 6. Live validation (operator-supervised, with the brain running)

- [ ] 6.1 Boot; confirm `data/workspace_trajectory` and
      `data/evaluation/attribution` accumulate rows during a normal session.
- [ ] 6.2 Confirm the eval page trajectory/attribution cards populate.
