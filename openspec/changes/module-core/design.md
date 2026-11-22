# Design: module-core

## Context

The audit behind this change is summarised in the proposal. Counts there are from `git grep` on `main` at `eac350195` and were checked by hand. Related changes:

- `unified-instance-configuration` (parked, 17 of 17 tasks done) generates `config/kaine.reference.toml` from `config/kaine.toml`. D8 keeps that direction.
- `2026-10-18-salience-score-keys` (archived) made candidate ids stream-qualified. D9 does not touch scoring.
- `latent-content-privacy` defines the latent rule and `strip_latent`. D5's default sink applies it, which absorbs that change's writer tasks.
- `welfare-signal-unblended` (merged as #850) reads each processor's own forward-model error through `read_welfare_prediction_error`. D7 must keep that reading bit-identical.

Import-linter contracts in `pyproject.toml` bind every placement below. Modules do not import the cycle. The workspace does not import modules. `kaine.privacy_filter` and `kaine.lifecycle.welfare_signal` are boundary-neutral homes.

## Goals

- A module author can read one page and build a module that fits.
- A rename, a dropped payload key, or a new direct clock call fails a test, not a run.
- A fix to a shared mechanism lands once.
- No step changes what the entity experiences.

## Non-goals

- A shared salience scale or recalibrated salience values (D9).
- Renaming existing event types or streams (D3).
- Rewriting modules. Each one migrates by mechanical steps behind tests.

## Decisions

### D1. The contract is a docs page plus spec requirements

`docs/02-architecture/module-contract.md` is the readable contract, written in present tense. It describes what is true on `main` and marks each part as **in force** or **adopting**: adopting means the mechanism is specified here but not every module uses it yet. The spec deltas in this change are the binding form, and each requirement has scenarios that tests check. Item by item, the page covers:

- the hooks a module implements;
- the naming grammar;
- units and time;
- how salience is reported;
- what may never be written;
- how state is saved;
- how config is added;
- how a module declares what it reads and emits.

### D2. Payload models are pydantic, registered by event type, validated in tests first

`kaine/bus/event_types.py` holds one `EventSpec` per cross-module event type: `type`, `owner` (a module name constant), `payload` (a pydantic model), and `version` (an int); declared consumers are not recorded, because nothing could check such a list against the real subscriptions. The payload models allow extra keys (`extra="allow"`). A producer can therefore add a field without breaking readers, while a missing or mistyped declared field fails validation.

Validation runs in three places:
1. A contract test validates each producer's payloads, built by calling the producer's own report-building code, never from hand-written fixtures.
2. `BaseModule.publish` validates against the registered model only when `KAINE_DEV_VALIDATE=1`, which the test suite and development runs set, and raises on a mismatch. In production, `publish` does no payload validation at all, so the hot path and its timing are unchanged. A mismatch message names the type and the field paths only, never values, so it cannot carry content or latent values into a log.
3. Each registered type's consumers move to `spec.parse(payload)`, as listed tasks in group 4, not as they happen to be touched.

Production enforcement is out of scope. Failing closed on a schema mismatch would stop an entity over a missing optional field, and the safety-over-UX rule does not favour that. The producer contract tests and dev-mode validation are the guard.

The first types registered are the ones that cross the most boundaries: the four processor reports (`vision.report`, `audition.perception`, `interoception.report`, `sequence.report`), `affect.state`, the action selection module's intents and the `workspace.broadcast` member shape.

The envelope gains `payload_version: Optional[int] = None`. None means version 1, so every existing entry and log reads unchanged.

### D3. Names are recorded as they are; new names follow a grammar

`kaine/module_names.py` holds one constant per module name. It is a boundary-neutral home beside `kaine/legacy_names.py`, because the workspace may not import anything under `kaine.modules` (and importing that package loads every module). Each constant is taken from `BaseModule.name` of each module and cross-checked against `kaine/legacy_names.py` `MODULES`. The event-type constants live beside the registry. Existing irregular names stay exactly as they are, because they are persisted in research logs, preserved bundles and the paper. New event types follow `<module>.<noun>`, with the noun taken from a fixed set:

- `report`: the periodic output;
- `state`: a level that holds until changed;
- `alert`: a threshold crossing;
- `intent`: a request to act.

Renaming `audition.perception` to `audition.report` is left for the operator, with an alias period like the module-name rename's.

### D4. The ratchet grows; ruff stays as it is

`tests/test_conventions.py` (#871) gains two kinds: event-type string literals compared in `kaine/workspace/` and `kaine/cycle/`, and module-name string literals compared there. Baselines are recorded per file, as before. Ruff's banned-API rule is not used. It would need per-file ignores for every existing site, which duplicates the ratchet's baseline with less information.

### D5. Boot attaches one `ModuleContext` to every module; nothing falls back silently

Modules may not import the cycle, and the entity clock belongs to the cycle. Today boot hands it only to the eight factories in `_CLOCKED_FACTORIES` (`kaine/boot/registry.py:80`). A default built inside `BaseModule` would therefore have to invent a clock. A wall-speed stand-in would silently stop dilating under `time_scale`, which is the bug this change exists to remove.

Instead, `BaseModule.attach_context(ctx)` mirrors `attach_oscillator`. The registry in `kaine/boot/registry.py`, which can import both sides, builds one `ModuleContext` per module from the cycle's clock and the configured services, and attaches it before `initialize()`. Reading `self.context` before a context is attached raises a clear error, never a default. Tests attach a test context through a fixture. No constructor or factory signature changes, so modules move to `self.context.*` one at a time, and each move lowers the ratchet. `ModuleContext` lives in `kaine/modules/context_services.py`, because `kaine/modules/context.py` already exists for broadcast context. It holds:

- `clock`: the `EntityClock` the cycle uses. `clock.now()` is entity time. Infrastructure intervals (watchdogs, timeouts, the heartbeat) use `clock.wall()`, and the contract page lists which intervals count as infrastructure.
- `paths`: `kaine.storage.resolve` and the module's own state directory.
- `write_json`: `kaine.state_io.write_json_atomic`.
- `jsonl(name)`: an `AsyncJsonlSink` for the module. It applies `strip_latent` by default and takes a named opt-out for records reviewed as latent-free.
- `privacy`: the `PrivacyFilter`.

### D6. `spawn`, `subscribe` and `health_extra` live on `BaseModule`

- `spawn(coro, *, name, every_s=None, clock="entity")` registers the task in `self._tasks`. With `every_s` it runs the coroutine periodically until `_stopped`, on the entity clock by default, or on real time with `clock="wall"` for infrastructure loops such as health pollers and client reconnects. It logs exceptions with the module and task name. Inside a tick context it also calls `track()`. The ratchet gains a `raw_task` kind for `asyncio.create_task` in module code.
- `subscribe(stream, handler, *, cursor_key)` reads with the last-scanned-id rule from the `event-bus` spec. Its cursor goes into the module's saved state under `cursors`.
- `health_extra()` returns a dict that `health()` merges in. A ClassVar `external_dependencies: tuple[str, ...]` names what a module needs (for example `("stt",)`), so the supervisor can show each dependency.
- `publish(..., drive_oscillator=True)` is the one publish path. A ratchet entry keeps raw publishes at zero.

### D7. The predictive unit is extracted under bit-identical golden tests

`kaine/modules/predictive.py` holds:

- `PredictionResult`: a frozen record of `value: float | None`, `defined: bool`, `null_value: float | None` and `skipped: bool`.
- `ErrorTracker`: the window, the mean, the ratio, and append-only-if-defined.
- `error_to_intensity(result, tracker, salience)`: the single mapping from error to intensity.
- `ForwardModelBase`: the buffer, the L2 error, the null baseline, skip and NaN handling, adaptation, `state_dict` and `load_state_dict`.

The mapping reproduces each processor's current behaviour exactly. Where the three disagree today, the shared function takes a per-processor parameter rather than unifying them; unifying them would change behaviour, which D9 forbids.

Order of work:
1. Record golden digests for each processor before anything moves: N steps on fixed seeds, digesting every published `prediction_error`, `own_error`, intensity, salience, welfare reading and `state_dict`. The audition forward model uses torch, so digests depend on the numeric build, as the stimulus-off golden already does. Two checks run. The checked-in digests are recorded on CI's CPU environment and checked by CI. In addition, each migration PR's review runs a same-machine comparison: a script drives the processor on `main` and on the branch and compares the two traces exactly, so the factory's local verify can skip the pinned digest without losing the check.
2. Migrate vision first, then audition, then interoception. Each migration is one PR whose golden digest must match.
3. Interoception goes last, because it feeds welfare. Its PR also re-runs `tests/test_welfare_signal_unblended.py` unchanged and gets a second review.

`kaine/workspace/feedback.py` reads the processor roster from a registry in a boundary-neutral home (`kaine/predictive_registry.py`), because the workspace may not import modules. The registry is declared data (name, report type, feature dimension), not filled by import side effects. Today `PROCESSORS` lists all three processors whether or not each module is enabled or imported, and a registry filled at import would change the roster when a module is off. A test checks that each processor's entry matches its module. Option F's `ContentLevel` reads the same registry.

### D8. Typed config describes keys; `config/kaine.toml` keeps the values

`kaine/config_model.py` adds `ConfigBase`, a frozen dataclass base. Its `from_section(section, *, retired=())` uses `require_known_keys` and `_warn_retired_keys` unchanged. Each module gets one config dataclass beside the module, with a field for every key: its type and bounds, and no default unless the key is optional in `kaine.toml`. A test asserts that each module's `kaine.toml` section and its dataclass fields name the same keys, and that every shipped value passes the dataclass's checks. Factories build the dataclass, then call `Module(bus, config=cfg, **deps)`. The allowed-key sets in the factories are deleted as each module migrates. `kaine.toml` stays the single source of shipped values, as `tests/test_single_source_defaults.py` requires.

### D9. Salience levels move into one table unchanged; the scale is a later decision

`SalienceConfig(baseline, alert)` is embedded in every module config, validated to 0–1, and the values stay exactly as shipped. world_model's nested `[world_model.salience]` table is read through a legacy alias. A shared scale would decide which module wins access, and moving to precision-weighted error as the common currency (Feldman and Friston 2010) or a calibrated tiering is a science change with its own proposal and adversarial review. This change only makes the current values visible in one place.

### D10. Saved state is wrapped and versioned; old bundles still restore

Group 7 lands after `latent-content-privacy`'s module-state strip (its task 2.3), which sits on the same snapshot, preservation and checkpoint paths; the envelope wraps state after the strip. `BaseModule.save_state()` returns `{"module": name, "schema_version": cls.state_version, "state": self.serialize()}`. `BaseModule.load_state(blob)` accepts that envelope, or a bare dict, which it reads as version 0. A per-module `migrate_state(version, state)` hook upgrades old versions. Modules with no state declare `stateless: ClassVar[bool] = True`, and the round-trip test refuses a module that is neither stateless nor overrides `serialize`. The language module's state is declared explicitly as one or the other, with the reason in a comment. Fork snapshots, preservation and the resume checkpoint call `save_state` and `load_state`. A test restores the first entity's preserved bundle layout (built from a fixture, not the real bundle) without loss.

### D11. Revisions after the independent gap analysis

kimi-k3's gap analysis (recorded in `review.md`) led to these rules:

- **Clock migration keeps each site's meaning.** Each batch that moves module code to `self.context` classifies every clock call it touches as cognitive or infrastructure, in a table in the PR. A call that reads real time today moves to `clock.wall()` unless the classification shows it times a cognitive process. Each re-timed site gets a test under freeze and dilation. Without this, a timeout or decay that runs during a freeze today would freeze, which changes behaviour.
- **Cursor behaviour is stated before `subscribe` replaces it.** Each consumer moved to `subscribe` states its current restart behaviour (resume, start fresh, or rescan), and the new code reproduces it. Saved cursors live under the reserved key `_cursors`, so they cannot collide with a module's own keys.
- **`spawn` keeps failures visible.** A task started by `spawn` that raises is counted as failed in `health()`, which the supervisor already restarts on. Log-and-continue applies only to periodic work that declares `on_error="log"`.
- **Operator config is warned, not refused, for one release.** A value in an operator file that fails a dataclass bound logs a warning and is used, for one release, with a note in the release record. Shipped values must pass from the start.
- **The undefined-error default is named and tested.** The three processors read `last_error_defined` with a default of True. All three set the flag today, so the default never applies, and migrating to `PredictionResult` removes it without changing any output. The golden harness includes skipped, NaN and first-reading cases, so a regression on those branches shows in the digest.
- **Golden digests are recorded first.** Task 5.1 runs before any group touches the processors, and the three processor modules are excluded from the `self.context` batches until their own migration lands.
- **The roster stays three processors.** The registry replaces the hard-coded tuple, and the three-source blend stays as it is. Generalising blending to N sources waits until a fourth processor is proposed. The golden harness digests the feedback blend's output too.
- **A bundle is checked before any module is built.** `load_state` failures are found by a pre-flight pass over every module state in a bundle before any module is instantiated. If a module that is not `stateless` cannot be restored, the whole resume or fork restore is refused and reported to the supervisor and the operator. Booting part of an entity fresh would corrupt its identity and welfare baselines.
- **The real bundle is the exit test.** Group 7 is not done until a read-only copy of the first entity's preserved bundle restores and round-trips under supervision, besides the fixture test.
- **Upgrades are recoverable.** Older code cannot read the state envelope, so the release that turns it on backs up existing bundles first, and the release record says the format change is one-way.
- **The latent opt-out is counted.** Each use of the JSONL sink's latent opt-out is a ratchet kind, so a new use needs a reviewed baseline change.
- **The contract page uses three marks.** Items are **in force**, **adopting** (the mechanism exists on `main` and modules are moving to it) or **specified** (decided here, not on `main` yet). Each group's PR moves its items from specified to adopting.

## Risks

- **The bit-identical claim depends on the golden harness covering what welfare reads.** The harness digests `own_error`, the published `prediction_error` and the welfare reading itself, not just the state dictionary.
- **Optional context adds a second way to reach each service while modules migrate.** The ratchet keeps the old way from growing. The contract page lists the migration state per module.
- **Pydantic payload models could drift from producers.** The contract test builds payloads with each producer's own code (D2).
- **The state envelope touches preservation.** A failed restore is the worst outcome. `load_state` never raises on an unknown version: it keeps the raw state, refuses the module's restore, and reports it.

## Open questions for the operator

1. Rename `audition.perception` to `audition.report` with an alias period, or keep it permanently (D3)? This change keeps it either way; a rename would be its own change.
2. Should the shared salience scale become its own proposal now, or after the module-addition study (D9)?
