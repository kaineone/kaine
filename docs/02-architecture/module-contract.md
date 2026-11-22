# The module contract

This page is what a module must provide to fit the rest of KAINE, and how. Read it before writing or changing a module. Each item carries one of three marks:

- **in force**: every module follows it, and a test or the base class enforces it;
- **adopting**: the mechanism exists on `main` and modules are moving to it, while the conventions test keeps the old pattern from spreading;
- **specified**: decided in the `module-core` change but not on `main` yet. Don't write code against a specified item until it moves to adopting. The binding form is the `module-pattern`, `event-bus`, `module-conventions` and `predictive-processor` specs.

## Identity and lifecycle

**In force.** A module subclasses `BaseModule` (`kaine/modules/base.py`) and declares a class-level `name`. The name is also its stream prefix and its config section, and the base class refuses a subclass without one. The cycle drives the lifecycle:

- `initialize()` starts the module's workspace loop. A module that overrides it calls the base method.
- `on_workspace(snapshot)` runs on every broadcast. Keep it fast: long work belongs in a background task.
- `shutdown()` cancels the module's tasks. Code that waits should check `self._stopped`.
- `restart()` and `holds_external_resources()` let the supervisor restart a module in place. Override them when the module holds a model, a device or a client.
- `relieves_drives` names the drives the module's activity relieves. `lockstep_capable = False` opts the module out of lockstep ticks.

**Specified.** Background work starts with `self.spawn(coro, name=..., every_s=...)`, never `asyncio.create_task`. That way the module's health counts the task, shutdown stops it, and lockstep tracks it. Reading another module's stream goes through `self.subscribe(stream, handler, cursor_key=...)`, which owns the cursor and saves it with the module's state.

## Publishing

**In force.** Every event is an `Event` (`kaine/bus/schema.py`). It carries `source`, `type`, `payload`, `salience`, `timestamp`, and the `tick` and `seq` stamps. A module publishes with `self.publish(type_, payload, salience=...)`, which validates, stamps and refreshes the heartbeat. Its events go to `<name>.out` (`module_stream`). Stream names come from `kaine/bus/streams.py`, never from a hand-built string.

**Adopting.** `publish` is the only path. The conventions test counts the remaining direct `self._bus.publish` calls in module code and fails on any new one.

**Specified:**
- `publish(..., drive_oscillator=False)` for an event that must not drive the module's oscillator.
- Event types that another module reads are registered in `kaine/bus/event_types.py` with a payload model and an owner.
- New types are named `<module>.<noun>`, with `report` (periodic output), `state` (a level that holds), `alert` (a threshold crossing) or `intent` (a request to act). Existing types keep their names. `audition.perception` is the processor report that does not follow the pattern.
- Consumers parse a registered payload with its model, not field by field.
- Workspace, cycle and module code imports event types and module names from `kaine/bus/event_types.py` and `kaine/modules/names.py`.

## Salience and intensity

**In force.** Salience is in [0, 1], and the workspace selects on it. A module that reports at a resting level and a heightened level takes `baseline_salience` and `alert_salience` from its config section. Outside the predictive processors, a graded signal is mapped between them with `graded_intensity` (`kaine/modules/intensity.py`). The three predictive processors each map their error to intensity in their own way today (see Predictive processors).

**Specified.** The pair is a shared `SalienceConfig` in every module's config. Today's values stay as shipped. A shared scale across modules is a later, separate decision.

## Time and units

**Adopting.** Cognitive timing belongs on the entity clock (`kaine/entity_clock.py`): `now()` is entity time, which dilates and freezes with the cycle; `wall()` is real time. Infrastructure intervals use real time: liveness watchdogs, network and model-server timeouts, file rotation and the heartbeat. Many module files still read the system clock directly. The conventions test records them and fails on any new one, including through an import alias.

**Specified.** A module reaches the clock as `self.context.clock`, which boot attaches before `initialize()`. Each call site that moves keeps its meaning: a real-time read stays on `wall()` unless it times a cognitive process. New duration and rate names carry a unit suffix: `_s` for seconds, `_ms` for milliseconds, `_hz` for rates (some existing config keys spell out `_seconds`; they keep their names). Timestamps come from the event envelope, never a payload `ts` or `timestamp` field.

## What may never be written

**In force:**
- No raw sense data is persisted: no frames, no audio, no perceptual latents.
- Entity-interior text fields (`CONTENT_FIELDS` in `kaine/privacy_filter.py`) never reach the dashboard or the research logs.
- Latent-derived values travel only under the `latent_derived` key, and `strip_latent()` removes them and the perceptual latents from any record (see [Security and privacy](../13-security-and-privacy.md)).

**Adopting.** A new hand-written `open(..., "w")`, `write_text` or `write_bytes` in module code fails the conventions test.

**Specified.** A module writes records through `self.context.jsonl(name)`, which applies `strip_latent` by default, and writes JSON state through `self.context.write_json`, which is atomic.

## State

**In force.** `serialize()` returns a JSON-serializable dict, and `deserialize(state)` restores it. Fork snapshots, preservation bundles and the resume checkpoint carry it. Learned weights are identity: they persist, are encrypted, are copied into forks and are never logged.

**Specified.** The base class wraps state as `{module, schema_version, state}` and still reads the bare dicts in existing bundles as version 0. A module with no state declares `stateless = True`. A module that changes its state shape raises `state_version` and upgrades the old shape in `migrate_state`. A round-trip test covers every registered module.

## Configuration

**In force.**
- A module's settings live in its `[<name>]` section of `config/kaine.toml`, which is the single source of shipped values.
- The module's factory in `kaine/boot/factories/` checks the section's keys and builds the module.
- A key that is no longer used is listed as retired, so old operator files still boot with a warning.
- `config/kaine.reference.toml` is generated from `kaine.toml` (`scripts/generate_reference_config.py`), and a test fails when the two drift.
- Tests never read the developer's real data root.

**Specified.** Each module has one config dataclass beside it, derived from `ConfigBase` (`kaine/config_model.py`), with a field for every key, its type and its bounds. The factory builds the dataclass and passes it to the module. A test checks that the dataclass and the `kaine.toml` section name the same keys.

## Health

**In force.** `health()` reports the heartbeat age and the module's task counts.

**Specified.** A module that needs an external service names it in `external_dependencies`, and reports its state from `health_extra()`, so the supervisor can tell a dead speech-to-text or model client from a quiet module.

## Predictive processors

**In force.** A predictive processor publishes its prediction error on its report and, when workspace feedback is on, its own forward-model error under `workspace_feedback.own_error`. Welfare reads the own error through `read_welfare_prediction_error` (`kaine/lifecycle/welfare_signal.py`).

**Specified.** Every forward model derives from `ForwardModelBase` (`kaine/modules/predictive.py`) and returns a `PredictionResult`, whose undefined value is `None`, never 0.0. Intensity comes from the shared `error_to_intensity`. A processor registers itself in the predictive registry, and workspace feedback and the content level read their roster from there.

## Checklist for a new module

- [ ] `BaseModule` subclass with a `name` defined in `kaine/modules/names.py`
- [ ] background work through `spawn`, stream reads through `subscribe`
- [ ] every event through `publish`; cross-module types registered with a payload model
- [ ] salience from `SalienceConfig`; intensity from `graded_intensity` or `error_to_intensity`
- [ ] entity time from `self.context.clock`; infrastructure intervals commented as real time
- [ ] records through `self.context.jsonl`, state files through `self.context.write_json`
- [ ] `stateless = True`, or `serialize`, `deserialize` and `state_version`
- [ ] a config dataclass and a `[<name>]` section in `config/kaine.toml`
- [ ] `external_dependencies` and `health_extra` if it uses an outside service
- [ ] the conventions test passes without raising any baseline

Items that are still specified apply once their mechanism lands; until then, follow the in-force and adopting items.
