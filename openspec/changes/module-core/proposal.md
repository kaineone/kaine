# Proposal: a shared module core and one module contract

## Why

The sixteen modules share a typed event envelope, a thin `BaseModule` lifecycle, one registry and an import-layering contract. Almost everything above that is written separately in each module. An audit on 2026-11-21 (eight read-only scouts, counts re-checked against `main`) found:

- Event payloads are free dictionaries (`kaine/bus/schema.py:21`). There is no registry of event types or payload shapes. Consumers guard every field (465 `isinstance(..., dict)` checks across `kaine/`, and four private float-parsing helpers). Event types are compared as bare string literals in 139 places, and the same concept has several names (`ts` and `timestamp`; `vision.report` beside `audition.perception`).
- The predictive unit the thesis rests on exists three times: `vision/forward.py` (562 lines), `audition/forward.py` (620) and `interoception/forward.py` (819). They were copied and adapted, not derived from a shared base. Error normalisation and the error-to-salience mapping are done three different ways. "Undefined error" is a flag read with `getattr(..., True)`, which treats a missing flag as defined. The processor roster is hard-coded in `kaine/workspace/feedback.py:47`.
- Fourteen modules each set their own `baseline_salience` and `alert_salience`, from 0.1 to 0.8, while salience decides workspace access.
- Shared services exist (`EntityClock`, `state_io.write_json_atomic`, `storage.resolve`, `privacy_filter.strip_latent`), but using them is opt-in. Module code makes 75 direct `time.time()`/`time.monotonic()` calls, starts 50 background tasks directly while `BaseModule.track` is used once, and hand-rolls atomic writes and JSONL appends. No module overrides `health()`. The language module publishes one event type past `BaseModule.publish`.
- Each module's config keys are listed three or four times (the factory's allowed set, a second tuple, the constructor and `config/kaine.toml`). Factories use four different patterns.
- Saved module state is a free dictionary per module. Only one carries a version, and no test round-trips every module, although forking and preservation depend on it.
- No page tells a module author what to publish, in what shape and units, how to report salience, how to save state, or how to add config. `docs/02-architecture/README.md` says modules exchange "typed events"; only the envelope is typed.

Every fix to a shared mechanism therefore lands several times, and drifts. The welfare re-land (#850) needed a dedicated reader to work around the processors' differences. Option F cannot take a fourth processor without editing the workspace. Most of the code is written by workers, which copy whichever pattern is nearest.

## What changes

- **One module contract.** `docs/02-architecture/module-contract.md` states what every module must provide and how. This change's spec deltas make it binding.
- **A conventions ratchet.** Already on `main` (#871). It grows to cover event-type and module-name literals in the workspace and cycle code.
- **One source for names.** Module names and event types live in constants modules. The workspace and cycle code import them rather than writing literals. Existing irregular names are recorded as they are; renaming them is a separate decision.
- **An event-type registry with typed payloads.** It covers the event types that cross module boundaries. Each type has a payload model, an owner and its declared consumers. Payloads validate in tests and in development mode. The envelope gains an optional `payload_version`.
- **Shared services through `BaseModule`.**
  - A `ModuleContext` holds the entity clock, path resolution, the approved JSON writer, a JSONL sink that strips latents by default, and the privacy filter.
  - `spawn()` starts tracked background work.
  - `subscribe()` owns stream cursors.
  - A health hook reports external dependencies.
  - Every publish goes through `BaseModule.publish`.
- **A `PredictiveUnit` core.** A shared forward-model base and a `PredictionResult` that carries its own validity. A shared error tracker, and one function mapping error to intensity. A processor registry, so blending and option F handle any number of processors. Vision, audition and interoception migrate one at a time, each under a bit-identical golden test.
- **Typed module config.** A `ConfigBase` and one config dataclass per module. The allowed keys, the constructor arguments and the documentation come from it. `config/kaine.toml` stays the single source of shipped values. A shared `SalienceConfig` holds each module's existing salience levels without changing them.
- **Versioned module state.** `serialize()` returns `{module, schema_version, state}`. `deserialize()` still accepts the bare dictionaries in existing bundles. A round-trip test covers every registered module.

Every step preserves behaviour, and each lands as its own atomic PR, built through the Fabro factory where it is code. Moving to a shared salience scale (a common precision currency) changes what wins access. That is a science decision and is out of scope here (design D9).

## Capabilities

- `module-pattern` (modified): the module contract, shared services, tracked background work, the health hook, the single publish path and versioned state.
- `event-bus` (modified): the event-type registry, typed payloads and `payload_version`.
- `module-conventions` (new): the ratchet and the names modules.
- `predictive-processor` (new): the shared predictive unit and the processor registry.

## Impact

- **Code:** `kaine/modules/base.py`, `kaine/bus/`, a new `kaine/modules/predictive.py`, `kaine/workspace/feedback.py`, `kaine/workspace/content.py`, the three forward models, `kaine/boot/factories/`, `kaine/config.py`, and every module's constructor, `serialize` and `deserialize`, migrated in batches.
- **Welfare:** the predictive-unit migration changes the code that produces the welfare signal's input. Each migration must be bit-identical, and gets a second review.
- **Persistence:** the state envelope must restore the first entity's preserved bundle unchanged.
- **Docs:** the architecture README wording, a new module-contract page, and each module's page as it migrates.
- **Paper:** none until a module's behaviour changes. None is planned here.
