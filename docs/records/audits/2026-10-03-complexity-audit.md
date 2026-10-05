# Complexity audit (2026-10-03)

A read-only sweep of the `kaine` repo at `main` 63d23e6. It asks how much of the codebase the research run uses, where complexity is causing bugs, and what to simplify first. No code was changed. This record is the work list for the build agents. Each item under [Work items](#work-items) is sized to be one OpenSpec change and one PR.

## Summary

The project is larger than its current research needs. However, most of that size is cheap to carry, because the breadth features sit behind clean seams. The costly complexity is concentrated in three places:

1. **The boot path is a monolith.** `_boot_and_run` in `kaine/cycle/__main__.py:1037` is a single 1,074-line function with about 45 phases. `kaine/boot.py` is 3,404 lines and mixes five concerns. Every new feature adds an `if enabled:` block somewhere in the middle of both.
2. **Defaults and probes are duplicated.** The same values and checks are restated in several layers, and the copies drift. The organ URL fallback is written 11 times, and two of those copies drop the `/v1` suffix. The model-server API-key lookup appears in 13 places. Free-disk thresholds are restated 5 times. GPU and RAM probes have three result shapes. At least six fixes in the past week were config values that did not reach the running process: #271, #295, #298, #301, #303 and #305.
3. **Work in progress is too broad.** 26 OpenSpec changes are open at once. Five are fully ticked but not archived. About a dozen are waiting on one or two tasks, usually a live verification. Meanwhile, no study has yet completed.

The cognitive modules themselves are reasonably sized, mostly 1–4k lines each. The welfare, preservation and encryption systems are deliberate, operator-mandated infrastructure, and they are out of scope for reduction. Only moving them unchanged is in scope.

## Measurements

| Measure | Value |
|---|---|
| Production Python (`kaine/`) | 370 files, 107,607 lines |
| Tests (`tests/`) | 476 files, 130,446 lines |
| OpenSpec markdown | 69,192 lines (210 archived changes, 26 open, 91 specs) |
| Docs book | 14,371 lines |
| `config/kaine.toml` | 525 leaf keys in 42 sections |
| Keys the operator config overrides | 46 |
| `KAINE_*` environment variables read | 51 |
| Commits | 303 since 2026-07-05; 219 in the last 30 days |
| Commit types | 88 feat, 79 docs, 56 fix, 46 chore |

**What the research run uses.**

- `config/kaine.operator.toml` enables 7 of the 16 modules: soma, chronos, topos, audition, lingua, thymos and hypnos. Those 7 modules total about 19.6k lines. The 9 disabled ones total about 13.7k.
- The static import closure of `python -m kaine.cycle` reaches 281 files and 81.6k lines, which is 75% of the package. The cycle entry point imports almost everything, enabled or not. That figure is an upper bound, because it counts function-level imports.
- Adding the study runner, Nexus, preboot and provisioning raises the reach to 82%. The unreached 18% is:
  - the offline benchmarks (6.2k)
  - `wheel_index` and `wheel_data` (2.6k)
  - parts of lifecycle (1.7k)
  - redteam (1.5k)
  - parts of setup (1.3k)
  - distributed (1.1k)
  - research export (1.1k)
  - experiment statistics (0.9k)

**Things that turned out not to be problems.**

- **Dead files are rare.** Only about 2.4k lines are imported by tests alone, and the largest of those is `kaine/experiment/corpus.py`. It is the field-tier pooling layer from the research-testing framework (#21). It was built ahead of use, it is not dead, and it should stay.
- **No config key is unread.** Every leaf name in `config/kaine.toml` appears in the code. The config's problem is breadth and default drift, not dead keys.
- **Breadth features barely touch the core.** `kaine/distributed`, `kaine/transfer`, `kaine/install_target.py`, `kaine/wheel_index.py` and `kaine/research/claude_science_export.py` have zero imports from boot, cycle or workspace. The remote bridge and the perception preview each touch `cycle/__main__.py` in about five places. The only breadth feature woven through the core is the CL1 plugin seam, with about 29 sites across `boot.py`, `config.py` and `cycle/__main__.py`.

**Fix history.** I sorted the 56 `fix` commits by rough cause. About half are integration fixes: config that did not reach the runtime, service wiring, deployment, install, and the Nexus UI. About a quarter fix cognition or lifecycle semantics. The rest are CodeQL or code-quality fixes. Splitting the boot path and keeping each default in one place (W3–W6) target the first group directly.

## Work items

Rules that apply to every item:

- **OpenSpec first.** Search `git log -S` and `--grep`, the archived changes and `openspec/specs/` before writing a proposal. Cite the prior work, and do not redo or undo it.
- **Run admissibility.** Never land a change that alters runtime behaviour while a study is live on the same image. A change to the study overlay or to recording counts as a new run configuration.
- **Ethics infrastructure.** Preservation, welfare response, Spot, decommission gating, state encryption and per-entity keys may be moved verbatim. They must not be reordered, weakened or removed. A refactor that touches them needs ordering tests first and a second, independent review.
- **Refactors keep behaviour.** Items marked "refactor" must not change behaviour. Run the full suite through `.git/kaine-tools/safe-run.sh` and compare it with `main`. Pytest is not a required CI check, so confirm it is green yourself.
- **Operator decisions.** An item marked "Operator" waits for the operator's answer. Do not start it on assumption.

Each table below lists the items in recommended order. The "Op." column says whether the item needs an operator decision.

### P1: before the next study launch

| ID | Item | Size | Risk | Op. |
|---|---|---|---|---|
| W1 | Finish graph-only recording for studies | S | low | yes, scope |
| W2 | The individuation trigger has no runtime producer | M | medium | yes |
| W3 | One source for organ, storage and service defaults | S | low | no |

**W1. Finish graph-only recording for studies.**

- The open branch `design/workspace-graph-only-recording` already turns off `nexus_record`, `raw_archive` and `workspace_trajectory` in `kaine/research/ignition_study/overlay.py`. Two gaps remain:
  - **`external_utterances` is still on.** The operator rule of 2026-10 says a study records only the workspace graph. The branch keeps the utterances and the safety records. Get an explicit operator ruling on whether utterances count as "graph".
  - **The evaluation observers still run during a study.** `[evaluation]` is enabled by default with `ab_sample_rate = 1.0` (`config/kaine.toml:1324`). That means one extra A/B call to the organ for every sampled utterance, during a study meant to measure the entity undisturbed. Turn off `[evaluation]` in the overlay, but keep anything the safety net reads.
- First confirm that `welfare_signal` and the preservation monitor do not depend on the evaluation master flag. `cycle/__main__.py:1741` says Spot reads the welfare signal directly. Verify that, and pin it with a test.
- Acceptance criteria:
  - An overlay test asserts that no recorder outside the ignition log and the safety records is enabled.
  - A test asserts the safety net still receives its inputs with `[evaluation]` off.
  - `docs/15-experiments/ignition-study.md` describes what a study records.

**W2. The individuation trigger has no runtime producer.**

- `lifecycle/divergence.py:112` reads the newest `data/evaluation/individuation/*.jsonl`.
- The only code that constructs `IndividuationTest` is the CLI runner, `evaluation/benchmarks/individuation_runner.py:136`. So in a live run, the individuation p-value trigger can fire only if someone ran that CLI by hand. The fallback signals (self-model drift, consolidation, adapters) still work, and they are probably what produced the preservation bundle from the 2026-10-01 module-ignition study.
- The welfare net should not depend on a manual step. Write an OpenSpec proposal with two options:
  - (a) The preservation monitor runs the test on a schedule while `[preservation.divergence_monitor]` is enabled.
  - (b) Document that the trigger is CLI-fed only, and show that state on Nexus.
- Option (a) is preferred. This is design work on ethics infrastructure, so it needs the operator's approval and a second review.

**W3. One source for organ, storage and service defaults.** Add `kaine/defaults.py`, or helpers in `kaine/config.py`, providing `lingua_chat_url(config)`, `model_server_api_key(config)`, `DEFAULT_CHAT_URL` and `DEFAULT_MIN_FREE_GB`. Then route these call sites through them:

- **Organ URL fallbacks.**
  - With `/v1`: `boot.py:1631`, `cycle/__main__.py:1207`, `preboot.py:240`, `cycle/preflight.py:71`, `setup/model_server.py:334` and `:523`, `setup/__main__.py:189`, `nexus/health/blocks.py:416`, `nexus/health/config.py:335`.
  - Without `/v1`: `evaluation/config.py:511` and `nexus/health/config.py:79`.
- **The `KAINE_MODEL_SERVER_API_KEY` lookups**, 13 in all. They include `boot.py:1615`, `:2400` and `:3254`, `cycle/__main__.py:1085` and `:1209`, `preboot.py:242`, and `setup/model_server.py:336`.
  - Keep each site's current precedence. Treat any site whose precedence differs from the others as a bug, and fix it in the same PR.
- **The second spelling of the organ URL**, `KAINE_ORGAN_URL`, at `modules/hypnos/trainer_service.py:376`. It has its own default.
- **The free-disk literals**: `storage.py:19`, `research/ignition_study/runner.py:182`, `research/ignition_study/plan.py:118`, `setup/wizard.py:656` and `setup/storage_step.py:193`.
- **Duplicate env reads**: `KAINE_PROFILE` and `KAINE_TIER`, read again at `cycle/__main__.py:2255`, and `KAINE_MODELS_DIR`, read again at `research/ignition_study/overlay.py:61`.

Also:

- Port 11434 is Ollama's, while the organ now runs on llama-server. Decide in the proposal whether the shipped default port should change. That is a behaviour change, so it gets its own task.
- Add a test that fails if `"11434"` appears outside `kaine/net.py` and the new defaults module.
- Add an env-override table to the configuration appendix.
- Leave `KAINE_STATE_KEY` alone.

### P2: structural, after P1

| ID | Item | Size | Risk | Op. |
|---|---|---|---|---|
| W4 | Split `kaine/boot.py` by concern behind a facade | M | low | no |
| W5 | Turn `_boot_and_run` into ordered phases | L | medium | no |
| W6 | Consolidate host probes and the organ gate | M | low to medium | no |
| W7 | Import contracts that keep breadth features at the edge | S | low | no |
| W8 | Derive the module names in drive strategies from the registry | S | low to medium | no |
| W9 | One `PluginRuntime` object for the CL1 seam | M | medium | no |

**W4. Split `kaine/boot.py` by concern behind a facade.** Refactor. Turn the file into a `kaine/boot/` package and keep `kaine.boot` re-exporting its current names, so that the 15 files that import it do not change. The proposed modules:

| Module | Contents | Current lines |
|---|---|---|
| `errors.py` | `ConfigurationError`, `_require_keys`, `_pop` | 49–106 |
| `factories/` | the `make_*` module factories | 107–430, 1253–1640, 1664–2000, 2472–2670 |
| `perception_feed.py` | the stimulus feed and womb transition | 432–1253 |
| `hypnos_voice_alignment.py` | `make_hypnos`, the trainer resolvers, probe validators and organ window runner | 1999–2470 |
| `security.py` | `install_state_encryption`, moved verbatim | 2671 |
| `registry.py` | `plugin_injections`, `build_registry`, `construct_module`, `rewire_module` | to 3012 |
| `wiring.py` | oscillators, the coherence scorer, salience factors, and the lingua, eidolon and self-hearing wiring | 3012–3323 |
| `metrics.py` | `_log_device_assignments`, `MetricsCollector` | 3323–3404 |

Also add a `lint-imports` contract that the factories do not import each other. Several `_wire_*` helpers at `cycle/__main__.py:167-213` belong in `wiring.py` too.

**W5. Turn `_boot_and_run` into ordered phases.** Refactor. Do this after W4.

- `cycle/__main__.py:1037-2112` becomes an ordered list of phase functions that share a `BootContext` dataclass: config, bus, registry, clock and an exit stack for cleanup.
- Proposed phases under `kaine/cycle/phases/`:

| Phase module | Source lines |
|---|---|
| `stage.py` | 1047–1075, plus helpers 715–769 |
| `gates.py` | GPU preflight and organ gate, 1170–1230 |
| `gestation.py` | womb, gestation and birth: 1251–1330 and 1840–1919, plus helpers 796–908 |
| `wiring.py` | 1345–1430 |
| `safety_net.py` | 1738–1840 |
| `optional_components.py` | Spot, eval sidecar, perception preview and remote bridge, 1563–1710 and 2070–2075 |

- Also move these out of the entry point:
  - the evaluation glue at lines 244–420, into `kaine/evaluation/wiring.py`
  - `_write_runtime_state` and `_clear_runtime_state`, into `cycle/control_state.py`
  - the profile and tier logic that `main` repeats at 2241–2255. Use `config.py`'s result instead.
- Keep the phase order and every early-exit code as they are.
- Acceptance criteria:
  - A test asserts the phase order and each exit code.
  - The safety-net phase moves as one block, unchanged, with a second review.

**W6. Consolidate host probes and the organ gate.** Refactor.

- `hostmem` becomes the only owner of memory figures, and `hardware.total_ram_gb` (`hardware.py:876`) calls it. That removes the second copy of the `/proc/meminfo`-then-`psutil` fallback chain.
- `cycle/preflight.py:131-142` takes a documented `HostSnapshot` directly. It stops re-parsing `describe_host()` into a third shape.
- One `organ_gate_args(config)` helper replaces the argument assembly for `verify_organ_generates` at `cycle/__main__.py:1203`, `preboot.py:238` and `setup/model_server.py:334/:523`.
  - Decide whether the `KAINE_ALLOW_MUTE_ORGAN` policy, now only in the cycle copy, applies to all of them.
- Remove the `KAINE_SERVICE_PORTS` alias (`cycle/preflight.py:57`) and the hardcoded `6479` in `setup/dependencies.py:63`.
- Leave the three layers of config validation for now: `config.py`, `preboot.check_config_sanity` at `preboot.py:1073`, and `boot._require_keys`. Record in this change which checks belong in which layer.

**W7. Import contracts that keep breadth features at the edge.**

- Add `lint-imports` contracts. `kaine.boot`, `kaine.cycle` and `kaine.workspace` must not import any of: `kaine.setup`, `kaine.distributed`, `kaine.transfer`, `kaine.remote`, `kaine.install_target`, `kaine.wheel_index`, `kaine.research.claude_science_export`.
- The one allowed exception is the W5 `optional_components` phase for `kaine.remote`.
- Today, four sites break the `kaine.setup` rule: boot imports `kaine.setup.speech_models` at `boot.py:1836`, `:1855`, `:1960` and `:1970`. Move `DEFAULT_STT`, `DEFAULT_TTS` and `model_dir` into a small shared module first.
- `lint-imports` is already a required CI gate, so this locks the current good state in place.

**W8. Derive the module names in drive strategies from the registry.**

- `workspace/strategies.py:84,87,92` hardcode "mundus", "praxis" and "vox". Replace them with capability tags in `kaine/modules/registry.py`.
- Add a test that fails when a strategy names a module that is not registered.
- This is groundwork for the Paracosmic embodiment rebuild. It also ties into the canonical-registry follow-up left open by the 2026-05 architecture audit.

**W9. One `PluginRuntime` object for the CL1 seam.**

- Fold the about 29 plugin references into one object that the registry holds. The main sites are `boot.py:1113-1144` and `:2693`, and `cycle/__main__.py:44` and `:825`.
- Boot and cycle then call `registry.plugins.injections_for(name)` and `.manifest()`.
- The module-restart path is the risky part. Chronos and Soma restart in place, and Nous is rebuilt. Keep `plugins/kaine-cl1/tests` green.

### P3: deduplication

| ID | Item | Size | Risk | Op. |
|---|---|---|---|---|
| W10 | One installer implementation | M | medium | yes |
| W11 | Compose is the single source for service definitions | M | medium | no |
| W12 | One JSONL record writer and one stats helper | M | low | no |
| W13 | Label each numpy/torch pair, and run its parity tests when either side changes | S | low | no |
| W14 | Rename the Lingua default backend | S | low | no |
| W15 | Tidy the config profiles | S | low | no |

**W10. One installer implementation.**

- `scripts/install.py` (1,497 lines) is a port of `scripts/install.sh` (970 lines). `tests/test_install_py_parity.py` exists only to police drift between them.
- Ask the operator whether any host needs the Python port. Its docstring cites macOS, zsh-only and BSD hosts.
  - If no host needs it, retire it and its parity test.
  - If one does, make `install.sh` a thin wrapper that execs `install.py`.
- The Orin path (JetPack, cu13x) lives in `install.sh`, so carry it over with tests.

**W11. Compose is the single source for service definitions.**

- Redis, Qdrant and the model server are defined in `compose/kaine.yml`, in `quadlet/`, and again in the standalone `compose/redis.yml` and `compose/qdrant.yml`. The standalone files are referenced from the docs and from `CONTRIBUTING.md`, so they are not dead.
- Either generate the quadlet units from compose, or add a test that fails when images, ports or commands differ between the definitions.
- Keep the Podman users working.

**W12. One JSONL record writer and one stats helper.**

- **Writer.** Route the benchmark runners (three `write_text`/`json.dumps` sites), `evaluation/redteam/report.py` and the ignition runner's records through `persistence/jsonl_sink.py`. They then also get the decrypt path that `experiment/run_records.py` assumes.
- **Stats helper.** Add `kaine/experiment/stats.py` with `mean`, `std` and `percentile`, replacing the copies in:
  - `experiment/stability.py:48,52`
  - `research/ignition_study/analysis.py:90,103`
  - `evaluation/individuation.py:218`
  - `prediction_error_observer.py:77`
- Check that the percentile definitions agree (interpolated or not) before merging. Results could shift if they don't.
- Fold the duplicated embedder fallback in `evaluation/registry.py` (`_resolve_embedder` and `_embedder_default`) into one helper.

**W13. Label each numpy/torch pair, and run its parity tests when either side changes.**

- There are four pairs: CfC (`cfc_numpy.py` and ncps), the text embedder, Nous (pymdp and numpy) and Phantasia (JAX and numpy). They total about 5.3k lines, plus 580 lines of golden recorders.
- The research run uses numpy for CfC and the embedder. Nous and Phantasia are off in the study.
- Add one page to the book that states, for each pair, which side ships and which is the reference.
- Add a CI path filter so the parity and golden tests run whenever either side changes.
- Do not flip the Nous or Phantasia defaults here. That changes the entity's computation and needs its own change.

**W14. Rename the Lingua default backend.**

- `BackendRegistry("lingua", default="ollama")` (`modules/lingua/client.py:330-350`) names a server the project no longer uses, which is misleading.
- Make `"openai"` the default and keep `"ollama"` as an accepted alias.
- Read `setup/organ.py` against `setup/model_server.py` for overlap in the same pass. Recommend a merge only if the two overlap.

**W15. Tidy the config profiles.**

- `config.py:602` auto-applies `profiles/thesis_test.toml`, which enables 6 modules. The operator config then sets 7, adding hypnos. Two files therefore define the base-thesis module set.
- Write down one rule for profile versus operator overlay, and have the wizard (`setup/wizard.py:82`) and the docs follow it.
- Do not change the module set. It is settled.

### Process items (operator)

These need operator decisions rather than code.

- **O1. Cap work in progress.**
  - Archive the changes whose tasks are all ticked and whose PRs are merged: `nexus-detail-page-layout` (#312), `nexus-diagnostics-without-cycle` (#315), `nexus-perception-availability` (#314), `voice-alignment-capability-probes-required` (#313) and `merge-veto-fails-closed` (#310). Confirm each merge before archiving it.
  - Then hold new work on the changes the study does not need until one study completes. The largest of these, by open tasks:
    - `module-residency-and-speech-tiers`: 38 open
    - `browser-first-run`: 22 open
    - `any-target-bootstrap`
    - `hardware-and-storage-selection`
    - `headless-host-operations`
  - These are decided features, so the question is timing, not whether to build them.
  - `entity-key-custody` (12 open) is ethics infrastructure. Its timing is the operator's call, not a freeze candidate by default.
- **O2. Decide which of the seven experiments are still live.** About 6.2k lines of offline benchmarks, plus `faithful/` (502) and the stability, verdict and multiple-comparisons modules, serve only synthetic or CLI experiments. Keep the ones for live experiments behind the existing lazy-import seam, ideally as a `kaine-research` extra so the cycle image does not ship them. Retire the rest through an OpenSpec change.
- **O3. Give the tests of disabled modules their own lane.** The Mundus and Praxis tests total roughly 25k lines (an overestimate, because it counts every file that names them). They run in every full suite. A `breadth` pytest marker with a nightly lane would shorten the default run. This changes the green-before-merge habit, so it is the operator's call.
- **O4. Prune stale worktrees.** Eight agent worktrees under `.claude/worktrees/` and two under `.git/kaine-tools/` hold old branches. They make repo-wide greps return stale copies; one reviewer in this audit hit that. Remove a worktree only after confirming its branch is merged or abandoned.

## Claims checked and rejected

The reviewers made these claims during the sweep, and verification showed them to be wrong. They are recorded so nobody acts on them:

- "Nous's numpy engine has no direct tests." It does: `tests/test_numpy_nous_engine.py` and `tests/test_numpy_aif_parity.py`.
- "The DINOv2 fallback is untested." `tests/test_topos_encoder.py` and nine other test files cover it.
- "`compose/redis.yml` and `compose/qdrant.yml` are unreferenced." The docs and `CONTRIBUTING.md` reference both.
- "`kaine/experiment/corpus.py` is dead." It is the field-tier pooling layer from #21, waiting for admissible runs to pool.

## Method

- **Size.** Line counts come from `wc -l`.
- **Import graph.** An AST import graph over `kaine/`, `plugins/`, `scripts/` and `tools/`. String literals such as `"kaine.x"` count as references. Entry points come from `pyproject.toml`, `compose/`, `docker/` and `quadlet/`.
  - "Imported only by tests" means a file has no non-test importer and appears in no launch file.
  - Reachability is a static closure that includes function-level imports, so it overstates what a run executes.
- **Config usage.** Each leaf key of `config/kaine.toml` was searched for as a quoted string, an attribute, or an assignment in non-test code. That method can only overcount use, so the zero-unread result holds.
- **Fix history.** The 56 commits whose subjects start with `fix` were grouped by hand into the causes above.
- **Reviews.** Four parallel read-only reviews covered duplicated implementations, the boot and host layer, the evaluation, lifecycle and research layers, and breadth-feature coupling. Their load-bearing claims were then checked against the code before inclusion.
