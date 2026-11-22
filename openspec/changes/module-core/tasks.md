# Tasks: module-core

Groups land in this order: 0, then 5.1, then 1, 2, 3, 4, then the rest of 5, then 6 and 7. Within a group, items are separate atomic PRs from a fresh `main`, merged in the order listed, because later items build on earlier ones (4.1 uses 2.2's `event_types.py`; 5.6 uses 2.1's `module_names.py`). Code PRs are built through the Fabro factory from a plan in `.fabro/PLAN-TEMPLATE.md` form. The lead reviews each one against this design before it merges. PRs marked (second review) also get an independent review.

## 0. Contract and decisions

- [x] 0.1 This proposal, design, tasks, spec deltas and `review.md` (lead review and kimi-k3 gap analysis recorded)
- [x] 0.2 `docs/02-architecture/module-contract.md` (D1), with each item marked in force, adopting or specified (D11)
- [x] 0.3 `docs/02-architecture/README.md`: say the envelope is typed and payloads follow the registry (D2), instead of "typed events"
- [ ] 0.4 Operator answers to the two open questions in the design

## 5.1 first. Golden digests (D7, D11)

- [x] 5.1 Golden digests for vision, audition and interoception, recorded before any other group touches them: published errors, `own_error`, intensity, salience, the welfare reading, the feedback blend output and `state_dict` over fixed seeds, including skipped, NaN and first-reading steps; checked on CI within a float tolerance, plus the exact same-machine comparison `tools/maintainer/golden-compare.sh`

## 1. Conventions ratchet (D4)

- [x] 1.1 `tests/test_conventions.py`: clock, raw-publish and file-write counts per file under `kaine/modules/`, through import aliases (#871)
- [x] 1.2 Add the `raw_task` kind (`asyncio.create_task`, `loop.create_task`) to the module scan
- [x] 1.3 Add `type_literal` and `source_literal` kinds: string literals compared with `.type` or `.source` (`==`, `!=`, `in`, `startswith`) in `kaine/workspace/`, `kaine/cycle/` and `kaine/modules/`
- [ ] 1.4 Add the `latent_opt_out` kind once 3.5 lands

## 2. One source for names (D3)

- [x] 2.1 `kaine/module_names.py`: one constant per `BaseModule.name`, with a test that every registered module's `name` is in it and matches `kaine/legacy_names.py`
- [ ] 2.2 `kaine/bus/event_types.py`: constants for every event type compared in workspace and cycle code; replace those literals with imports; lower the ratchet
- [ ] 2.3 Replace module-name literals in `kaine/workspace/` and `kaine/cycle/engine.py` (the duplicated `"affect"` constants in `stimulus_policy.py`, `drive_policy.py`, `planning_proposals.py`, `regulation_bias.py`, and `OWN_EXTERNAL_SPEECH_SOURCE`) with imports from `names.py`; lower the ratchet

## 3. Single publish path and shared services (D5, D6)

- [x] 3.1 `BaseModule.publish(..., drive_oscillator=True)`; the language module's aggregate speech event goes through it; raw-publish baseline to zero (Fabro run `01M81ESS58YVVGES8Q065F4KYR`)
- [ ] 3.2 `ModuleContext` and `BaseModule.attach_context`; the registry attaches one per module before `initialize()`; tests that every booted module has the cycle's clock and that reading an unattached context raises
- [ ] 3.3 `BaseModule.spawn` and `subscribe`, with tests for stop, exception logging, tick tracking, and cursor save and restore
- [ ] 3.4 `health_extra()` and `external_dependencies`; the supervisor's health view shows each dependency
- [ ] 3.4a Declare dependencies and report them: audition (speech-to-text), vocal (text-to-speech), language (chat client), episodic memory (Qdrant), world model (backend), sleep (trainer)
- [ ] 3.5 The default JSONL sink applies `strip_latent` with a named opt-out (absorbs `latent-content-privacy` 1.2 and 1.3; G2-2 Fabro run `01M81ESS1RXQK37ZK05JSAMM1D` does the writer part) (second review)
- [ ] 3.6 to 3.n Migrate modules to `self.context`, `spawn` and `subscribe`, a few modules per PR, lowering the ratchet each time. Each PR carries the clock classification table and the cursor behaviour statement (D11). Vision, audition and interoception wait until their group 5 migration has landed

## 4. Typed payloads (D2)

- [ ] 4.1 `EventSpec`, the registry, `payload_version` on the envelope, dev-mode validation in `publish`
- [ ] 4.2 Payload models and producer contract tests for the four processor reports
- [ ] 4.3 `affect.state`, the action selection module's intents, and the broadcast member shape
- [ ] 4.3a Consumers of each registered type move to `spec.parse`, one PR per type
- [ ] 4.3b Contract page: payload key names (timestamps come from the envelope, never a payload `ts` or `timestamp`; durations carry unit suffixes)
- [ ] 4.4 A shared `kaine/bus/payload.py` with `get_float`, `get_str`, `get_mapping` (bool-safe, finite-checked), replacing the four private helpers

## 5. Predictive unit (D7) (second review on every PR)

- [ ] 5.2 `kaine/modules/predictive.py`: `PredictionResult`, `ErrorTracker`, `error_to_intensity`, `ForwardModelBase`, with unit tests
- [ ] 5.3 Vision migrates; golden digest unchanged
- [ ] 5.4 Audition migrates; golden digest unchanged
- [ ] 5.5 Interoception migrates; golden digest and `tests/test_welfare_signal_unblended.py` unchanged
- [ ] 5.6 `kaine/predictive_registry.py` as declared data; `kaine/workspace/feedback.py` and `ContentLevel` read the roster from it; a test checks each entry against its module; the blend unchanged and its digest identical

## 6. Typed config (D8, D9)

- [ ] 6.1 `kaine/config_model.py` `ConfigBase`; the nine existing sub-feature dataclasses inherit it
- [ ] 6.2 `SalienceConfig`; the key-parity test between `kaine.toml` sections and dataclass fields
- [ ] 6.3 to 6.n Migrate factories in batches of three or four modules

## 7. Versioned state (D10) (second review)

- [ ] 7.1 `save_state` and `load_state` with the envelope, `stateless`, `migrate_state`, and refusal without raising on an unknown version
- [ ] 7.2 The round-trip test over every registered module; the language module's state declared
- [ ] 7.3 After `latent-content-privacy` 2.3: fork snapshot, preservation and resume checkpoint call `save_state` and `load_state`; a pre-flight pass checks every module state in a bundle before any module is built and refuses the whole restore on a failure; a fixture with the first bundle's layout restores without loss
- [ ] 7.4 Exit check under supervision: a read-only copy of the first entity's preserved bundle restores and round-trips; bundles are backed up before the release that writes the envelope, and the release record says the format change is one-way

## 8. Docs

- [ ] 8.1 The contract page's in-force/adopting marks updated as each group lands
- [ ] 8.2 Each module's page notes its config dataclass and its declared events once it migrates
