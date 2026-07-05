# Design — Fix the dark evaluation observers

## 1. The two bugs, concretely

### 1a. workspace.broadcast contract mismatch (trajectory, attribution)

Producer (`cycle/engine.py`, via Syneidesis) writes the broadcast as:

```
xadd workspace.broadcast  {snapshot: "<json>", timestamp: "...", source: "syneidesis"}
```

The standard `Event` schema (and `_decode_event`) expects `source/type/salience/
timestamp/causal_parent/payload`. The broadcast has none of `type/salience/
payload`, so:

- `StreamSubscriberObserver._run` calls `bus.read_entries(...)`, which runs each
  entry through `_decode_event`. The broadcast entries fail and are returned as
  *undecodable* → the loop advances the cursor past them (the tolerant-decode
  behavior) and **never calls `handle()`**.

Meanwhile every real module consumes the broadcast through a different door:

```
BaseModule._workspace_loop:
    async for entry_id, payload in bus.subscribe_workspace(last_id=...):
        snapshot = self._snapshot_from_payload(payload)   # payload = decoded snapshot dict
```

`subscribe_workspace` knows the `{snapshot: <json>}` shape and yields the parsed
snapshot **dict** as `payload`. That dict has exactly the keys
`trajectory.handle` already reads: `tick_index`, `is_experiential`, `inhibited`,
`salience_scores`, `selected`, `metadata`.

**Fix:** a `WorkspaceSubscriberObserver` base that follows the broadcast via
`subscribe_workspace` and hands the decoded snapshot payload to `handle`.

```python
class WorkspaceSubscriberObserver(BaseObserver):
    async def _run(self):
        cursor = await self._initial_cursor()
        async for entry_id, payload in self._bus.subscribe_workspace(last_id=cursor):
            if self._stopped.is_set():
                break
            try:
                await self.handle(entry_id, payload)   # payload is the snapshot dict
            except Exception:
                log.warning("observer %s handler raised", self.name, exc_info=True)
```

`TrajectoryRecorder` / `AttributionRecorder` switch base classes. Their `handle`
signature changes from `(entry_id, event: Event)` to `(entry_id, payload: dict)`
and they read `payload[...]` instead of `event.payload[...]` — a near-identical
body (today they already do `event.payload or {}` then read snapshot keys).

`BusReader` (the observers' bus protocol in `evaluation/_base.py`) gains
`subscribe_workspace`; the real `AsyncBus` already implements it, and fakes used
in tests add a minimal async-generator version.

Why not "fix the producer to emit standard Events"? The broadcast snapshot is a
structured object (selected coalition + scores + flags), deliberately serialized
as one `snapshot` field and consumed snapshot-wise by every module. Reshaping it
into the flat Event schema would churn the hot path and every module consumer for
no benefit. The observers should use the same canonical door the modules use.

### 1b. memory_probes / eidolon_accuracy never instantiate

`SidecarRegistry.build()` gates these on injected collaborators:

```
if config.memory_probes and self._memory_source and self._cognitive_client: ...
if config.eidolon_accuracy and self._cognitive_client: ...
```

The entrypoint passes neither:

```
SidecarRegistry(bus=bus, config=eval_cfg,
                thymos_state_provider=..., sleep_state_provider=...)
```

So both observers are silently dropped (9 enabled → 7 built).

**Fix:** the entrypoint builds two adapters and passes them, exactly as it
already does for thymos/sleep state — keeping `kaine.evaluation` free of any
`kaine.modules.*` import:

- `memory_source`: a thin adapter over the Mnemos module's recall/store surface
  (read-only) that satisfies the sidecar's `MemorySource` protocol. Built only
  when `mnemos` is in the registry.
- `cognitive_query_client`: a small client over the evaluation chat endpoint
  (`[evaluation].chat_url` / `chat_model_id`, already in config) implementing the
  sidecar's cognitive-query protocol. This is the "ask the full model a probe
  question" channel, distinct from the bare baseline client.

Both observers remain interval-gated (`memory_probe_interval_minutes`,
`eidolon_accuracy_interval_hours`). That is correct — they run on a schedule, not
per tick — but it means they populate later, not on first boot. The Nexus eval
tab and docs should say so, so an empty card during a short session reads as
"scheduled, not yet due" rather than "broken".

## 2. Isolation invariant

`kaine/evaluation/*` must not import `kaine.modules.*` (the sidecar is an
observer, decoupled from cognition). All module knowledge stays in the
entrypoint adapters. New code honors this: the observer base touches only the bus
protocol; the new providers are constructed in `cycle/__main__.py`.

## 3. Test strategy

- A fake bus exposing `subscribe_workspace` (async generator over canned
  `(entry_id, snapshot_dict)` pairs) drives `TrajectoryRecorder` /
  `AttributionRecorder`; assert a row is written per broadcast with the expected
  snapshot fields. A regression test feeds a *raw broadcast entry shape*
  (`{snapshot: json}`) end-to-end and asserts the recorder writes (guarding the
  exact bug found live).
- Registry test: with `memory_source` + `cognitive_client` provided and the
  flags on, `build()` includes the memory-probe and eidolon observers (count goes
  9, not 7); without them, they're skipped (current behavior) — both asserted.
- Entrypoint adapter unit tests: the memory-source adapter and cognitive-query
  client satisfy their protocols and never import `kaine.modules.*` at the
  evaluation layer (import-isolation test already exists for phase 9; extend it).

## 4. Out of scope

- `ab_divergence` (handled in `condition-language-organ`).
- `voice_tracking` / `sleep_snapshots` (correctly Hypnos-gated).
- Any change to the broadcast wire format or Syneidesis.
- Nexus eval-tab visual design beyond a "populates on a schedule" note for the
  interval-gated cards.
