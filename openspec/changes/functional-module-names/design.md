## Context

The mapping in proposal.md is decided and is not revisited here. This document
records where the old names occur, how one codemod replaces them, what stays
readable under the old names and for how long, the order of the PRs, and the
tests.

The survey was measured on `origin/main` at 0d1661fd (2026-10-11) with
`git ls-files` (3,084 tracked files) and a script that counts every match of an
old name whose neighbours are not letters, so `ToposModule`, `topos_tile` and
`TOPOS_STREAM` count and `somatic` does not. The script and its raw output are
reproduced by task 2.5; the numbers below are its output.

## Survey

### Occurrences by category

Columns: tracked file paths containing the name; matches in Python under
`kaine/`, `plugins/`, `tools/`, `scripts/`, `eval_probes/` (Code); `tests/`;
`config/`; `quadlet/`, `compose/`, `docker/` and `Dockerfile` (Container);
`kaine/nexus/static` and `kaine/nexus/templates` without vendor files (UI);
`docs/` without `docs/records/` plus top-level Markdown (Docs);
`openspec/specs/` (Specs); `openspec/changes/` without the archive (Active
changes); `openspec/changes/archive/`; `docs/records/`; `CHANGELOG.md`; vendored
JavaScript, `external/` and `unsloth_compiled_cache/` (Third-party); everything
else (Other: the kaine-cl1 plugin's tests and specs, `pyproject.toml`,
`.github/`, shell scripts).

| Name | Paths | Code | Tests | Config | Container | UI | Docs | Specs | Active changes | Archive | Records | CHANGELOG | Third-party | Other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| topos | 51 | 522 | 1640 | 25 | 2 | 0 | 307 | 82 | 210 | 523 | 11 | 3 | 4 | 9 |
| soma | 65 | 519 | 1956 | 25 | 0 | 6 | 413 | 163 | 217 | 889 | 8 | 3 | 8 | 76 |
| chronos | 59 | 315 | 725 | 10 | 0 | 0 | 190 | 96 | 79 | 438 | 9 | 3 | 0 | 120 |
| thymos | 64 | 453 | 1181 | 21 | 0 | 11 | 295 | 96 | 155 | 536 | 9 | 2 | 0 | 14 |
| hypnos | 84 | 794 | 1262 | 28 | 7 | 9 | 546 | 166 | 237 | 865 | 25 | 1 | 0 | 17 |
| mnemos | 54 | 440 | 1293 | 18 | 2 | 7 | 286 | 109 | 128 | 613 | 13 | 0 | 0 | 5 |
| phantasia | 40 | 303 | 490 | 16 | 0 | 0 | 225 | 97 | 68 | 387 | 14 | 3 | 6 | 11 |
| lingua | 42 | 556 | 1292 | 45 | 2 | 1 | 338 | 158 | 254 | 726 | 9 | 2 | 0 | 5 |
| vox | 28 | 252 | 576 | 12 | 0 | 0 | 170 | 92 | 20 | 245 | 11 | 0 | 0 | 1 |
| nous | 81 | 589 | 876 | 20 | 0 | 10 | 324 | 139 | 64 | 651 | 19 | 4 | 11 | 81 |
| volition | 3 | 230 | 255 | 8 | 0 | 0 | 180 | 63 | 8 | 289 | 1 | 1 | 0 | 12 |
| eidolon | 39 | 236 | 572 | 16 | 0 | 14 | 177 | 72 | 56 | 368 | 9 | 1 | 0 | 3 |
| empatheia | 28 | 162 | 307 | 12 | 0 | 0 | 150 | 76 | 64 | 267 | 11 | 2 | 0 | 4 |
| syneidesis | 19 | 116 | 255 | 13 | 0 | 1 | 107 | 45 | 60 | 236 | 1 | 2 | 0 | 2 |
| praxis | 21 | 208 | 209 | 9 | 0 | 0 | 153 | 61 | 8 | 236 | 3 | 0 | 0 | 12 |
| mundus | 12 | 165 | 336 | 13 | 0 | 0 | 225 | 19 | 17 | 211 | 5 | 1 | 0 | 2 |
| perception | 73 | 714 | 756 | 40 | 7 | 107 | 471 | 117 | 122 | 592 | 8 | 6 | 0 | 19 |
| perception, locus sense | n/a | 43 | 103 | 5 | 0 | 8 | 94 | 20 | 0 | 41 | 0 | 1 | 0 | 5 |
| spot | 33 | 293 | 566 | 13 | 3 | 110 | 120 | 160 | 22 | 583 | 4 | 1 | 152 | 2 |
| spot, module sense | n/a | 283 | 492 | 13 | 3 | 103 | 120 | 159 | 21 | 577 | 4 | 1 | n/a | 1 |
| nexus | 165 | 498 | 1032 | 18 | 67 | 242 | 440 | 194 | 62 | 964 | 14 | 2 | 2 | 63 |
| echo | 2 | 36 | 156 | 5 | 12 | 0 | 46 | 15 | 0 | 49 | 0 | 0 | 12 | 289 |
| echo, module sense | n/a | 25 | 133 | 5 | 1 | 0 | 38 | 13 | 0 | 35 | 0 | 0 | n/a | n/a |
| gestation | 23 | 348 | 581 | 14 | 0 | 3 | 160 | 101 | 45 | 442 | 2 | 0 | 0 | 0 |
| gestational | 13 | 1 | 0 | 0 | 0 | 0 | 20 | 5 | 2 | 39 | 0 | 0 | 0 | 0 |
| womb | 38 | 684 | 850 | 32 | 0 | 0 | 93 | 121 | 24 | 557 | 2 | 0 | 0 | 0 |
| birth | 16 | 446 | 454 | 12 | 1 | 10 | 80 | 71 | 122 | 282 | 1 | 0 | 0 | 0 |
| being | 1 | 228 | 93 | 11 | 1 | 1 | 182 | 83 | 239 | 264 | 0 | 0 | 3 | 19 |
| being, entity sense | n/a | 125 | 58 | 9 | 1 | 0 | 141 | 62 | 180 | 193 | 0 | 0 | 0 | 4 |
| audition (unchanged) | 57 | 601 | 1571 | 21 | 0 | 0 | 473 | 214 | 290 | 583 | 12 | 2 | 0 | 15 |
| workspace (target) | 61 | 554 | 985 | 48 | 5 | 3 | 395 | 202 | 227 | 852 | 8 | 6 | 4 | 28 |

The "sense" rows are a heuristic filter (identifier or key context, or a
listed phrase such as "the being") and only size the false-positive problem;
the codemod's own rules decide. What the false positives are:

- `spot`: all 152 third-party matches are three.js `spotLight` in the vendored
  `three.module.js`. In first-party files almost every match is Spot.
- `echo`: the 289 "Other" matches are the shell builtin in scripts, and the 12
  container matches are `echo` in quadlet `ExecStart` lines. The module is
  `EchoModule` and the `echo` key only.
- `being`: in code about 45% of matches are the English verb ("being overwhelmed",
  "being stopped"), including 4 in the K1-Jev question text in
  `kaine/decision/schema.py`.
- `perception`: about 6% of code matches mean the locus arbiter. The rest is
  `perception_feed`, `perception_preview`, `perception_state`, the `perception`
  pip extra, `KAINE_PERCEPTION_PREVIEW` and the ordinary word, none of which
  is renamed.
- `workspace` is a target, not an old name: 554 code matches already exist,
  including the `kaine/workspace/` package, `WorkspaceSnapshot` and the
  `workspace.broadcast` stream.

### Distinct names by kind (live files only)

Live means everything except `tests/`, `openspec/`, `docs/records/`,
`CHANGELOG.md` and vendored files.

- Python packages and modules: 18 packages under `kaine/modules/<name>/`
  (Audition stays), plus `kaine/modules/echo.py`, `womb_drive.py`,
  `womb_signal.py`, `kaine/nexus/` (63 tracked files), `kaine/cycle/spot.py`,
  `spot_selftest.py`, `gestation.py`, `womb_presence.py`, `womb_watch.py`,
  `kaine/workspace/syneidesis.py`, `volition.py`, `nous_proposals.py`,
  `kaine/lifecycle/birth_ack.py`, `womb_liveness.py`,
  `kaine/distributed/fork_being.py`, `kaine/nexus/birth.py`,
  `kaine/boot/factories/<name>.py`, 18 pages under `docs/09-modules/`, and 33
  folders under `openspec/specs/`.
- Class and function definitions whose names contain an old name: 283
  (womb 33, birth 34, nous 22, perception 22, hypnos 18, mnemos 16, thymos 16,
  soma 13, chronos 12, lingua 11, phantasia 10, nexus 10, the rest fewer).
- Dotted literals (bus streams, event types, config paths): 98, for example
  `thymos.state`, `hypnos.sleep.completed`, `volition_feedback.out`,
  `intent.perception.switch`, `stage.gestation.womb_lost`, `stage.birth.ready`,
  `gestation.womb`, `nexus.snapshot`. Streams are named in
  `kaine/bus/streams.py`, and a module's output stream is
  `module_stream(<module name>)`, so the module `name` ClassVar drives the
  stream, the config table, the snapshot and bundle keys and the bus `source`.
- Config: 44 tables and 17 `[modules]` flags in `config/kaine.toml`, 80 table
  headers across the shipped config, profiles and studies, the keys
  `womb_ready_retry_seconds`, `womb_check_seconds`, `womb_loss_after_seconds`,
  `womb_arm_timeout_seconds`, `womb_presence_window_seconds`,
  `womb_prediction_error_ceiling` and `birth_transition_seconds`, the value
  `[perception_feed].mode = "womb"`, `[mnemos].collection_prefix = "mnemos_"`,
  `[empatheia].collection = "empatheia_agents"`, and `STUDY_ALLOWED_TABLES`
  (`lingua`, `syneidesis`) in `kaine/config.py`.
- Environment variables: operator-facing `KAINE_NEXUS_TOKEN`,
  `KAINE_NEXUS_ACCESS`, `KAINE_NEXUS_ALLOWED_ORIGINS`,
  `KAINE_NEXUS_CONVERSATION_ENABLED`, `KAINE_NEXUS_EXTRA_HOSTS`,
  `KAINE_NEXUS_HOST`, `KAINE_NEXUS_HOST_PORT`, `KAINE_NEXUS_NON_LOOPBACK_ALLOWED`,
  `KAINE_NEXUS_PORT`, `KAINE_NEXUS_PUBLISHED_PORT`, `KAINE_NEXUS_READ_ONLY` and
  `KAINE_MUNDUS_OPERATOR_APPROVED` (12), plus the compose variables
  `NEXUS_HOST_PORT`, `NEXUS_EXTRA_HOSTS`, `NEXUS_TOKEN`, `NEXUS_ACCESS`.
  Test-only: `KAINE_TOPOS_RUN_REAL_ENCODER`, `KAINE_NOUS_RUN_REAL_PYMDP`,
  `KAINE_NOUS_RUN_REAL_NAR`, `KAINE_VOX_RUN_REAL`, `KAINE_LINGUA_RUN_REAL_CHAT`.
- CLI flags: `--serve-nexus` (`scripts/prepare-headless-host.sh`),
  `--db-gestation` and `--gestation-budget-seconds`
  (`python -m kaine.research.ignition_study`).
- Plugin seams: `oscillator.<module>`, `soma.forward_model`, `chronos.network`,
  `nous.engine`, `nous.engine_wrapper` (`kaine/plugins.py`), used by the
  in-tree `plugins/kaine-cl1`.
- Packaging and entry points: the `nexus` pip extra, `python -m kaine.nexus`,
  the import-linter contracts and package-data keys in `pyproject.toml`.
- Containers: `quadlet/kaine-nexus.container`, `quadlet/kaine-nexus-record.volume`,
  the compose service `nexus` and volume `nexus-record`.
- Persisted names: Qdrant collections `mnemos_*` and `empatheia_agents`;
  `state/mnemos/mnemos.db`, `state/mnemos/store_health.json`,
  `state/lingua/intent_expression.jsonl`, `state/lingua/utterance_outcomes.jsonl`,
  `state/eidolon/self_model.json`, `state/hypnos/consolidation_divergence.json`,
  `state/hypnos/organ_window.json`, `state/perception/desired.json`,
  `state/perception/runtime.json`, `state/praxis/audit.log`,
  `state/praxis/notifications.log`, `state/lifecycle/gestation_readout.json`,
  `state/lifecycle/birth_request.json`, `state/lifecycle/birth_ack.json`,
  `gestation_progress.json`, `gestation_viability.json`, `birth_adapter.gguf`;
  in `state/lifecycle/stage.json` the stage value `gestation` and the fields
  `gestation_started_at`, `womb_t_at_birth`, `womb_seed`, `womb_params_digest`,
  `birth_bloom_ends_at`; the control-file requester `spot`; snapshot and bundle
  module keys (`modules[module.name]`, the manifest's `modules` list) and the
  bundle member directory `gestation/`; `OWN_LIVED_ARTIFACTS` in
  `kaine/lifecycle/identity.py` (`phantasia/world_model.ckpt`,
  `hypnos/consolidation_divergence.json`, `perception/desired.json`).
- Recorded data on this host: four preservation and backup bundles under
  `backups/` whose manifests list the modules by old name, nine fork trees under
  `state/forks/`, and evaluation sidecar files under `data/evaluation/` whose
  directories (`eidolon_accuracy`, `empatheia`, `nous_policy`) and fields
  (`thymos_state`, per-module keys such as `chronos`, stream names such as
  `soma.out`) carry old names.
- K1-Jev records: no old module or developmental name occurs in
  `.git/kaine-tools/k1jev/gold/items.jsonl` (350 items),
  `items.v0-rejected.jsonl` (242) or `labels.jsonl`. The only matches in the
  K1-Jev code are the English "being" in four question texts.
- Entity-facing text: `[individuation].disclosure` says "since your birth".
  `kaine/persistence/system_prompts.py` has no old name.

### Collisions with the target names

| Target | Already bound to | Measured | Resolution |
| --- | --- | --- | --- |
| `WorldModel` | Protocol in `kaine/modules/phantasia/world_model.py` | 12 uses | Renamed to `WorldModelBackend` before the module rename (PR 2). `[phantasia.world_model]` becomes `[world_model.backend]` by an explicit override, not `[world_model.world_model]`. |
| `SelfModel` | Self-model document class in `kaine/modules/eidolon/document.py` | 32 uses | Renamed to `SelfModelDocument` in PR 2. The stream `eidolon.self_model` becomes `self_model.document` by override. |
| `Sequence` | `typing.Sequence` and `collections.abc.Sequence` | 158 uses | In a file that already binds `Sequence`, the codemod imports the module class as `SequenceModule`. It never shadows the ABC. |
| `Workspace` | the `kaine/workspace/` package, `WorkspaceSnapshot`, `workspace.broadcast` | 554 code matches, no class `Workspace`, no `[workspace]` table | `kaine/workspace/syneidesis.py` becomes `kaine/workspace/core.py`, exported as `kaine.workspace.Workspace`. `SYNEIDESIS_SOURCE` becomes `WORKSPACE_SOURCE` with value `workspace`. The broadcast stream keeps its name. `WorkspaceSnapshot` is unchanged. |
| `affect` | the Mnemos trace payload field `affect` and faithful-renderer payloads | 45 string literals | No rename touches these. The collision check lists every file where a new `"affect"` key would sit beside an existing one, for review. |
| `self_model`, `vision`, `world_model`, `effectors`, `entity` | literals 13, 10, 6, 3, 19 (the `vision` pip extra already holds Vision's dependencies) | | Listed by the collision check for review. File-path stutters such as `kaine/modules/effectors/effectors.py` are accepted. |
| `maturation` | `kaine/lifecycle/maturation_gate.py` (39 word uses) | | Congruent: the gate decides maturation. No identifier clashes. |

## Goals / Non-Goals

**Goals**

- Every live name matches the paper.
- The rename is reviewable as rules, and its output is mechanical.
- Each PR passes the gate and can merge alone.
- No operator setup breaks without a warning, no preserved entity becomes
  unreadable, and the never-regress invariant holds across the rename.

**Non-Goals**

- Rewriting history: archived changes, `docs/records/`, released CHANGELOG
  entries and commit messages keep the old names.
- Renaming active change IDs such as `mnemos-trace-strength`. They are
  identifiers of past and present work, and the ROADMAP keys on them.
- Changing what the entity is told through the codemod. The one entity-facing
  change, the disclosure text, is an owner decision made by hand (see
  "Entity-facing text").
- Changing behaviour. Every PR in the sequence is a rename or an alias.

## Decisions

### One mapping table

`kaine/legacy_names.py` holds the mapping as data: for each module the old and
new class form, key form and prose form, and a layer tag; the developmental
terms with their key forms; explicit overrides for compounds that a
component-wise rename would get wrong (`eidolon.self_model` to
`self_model.document`, `[phantasia.world_model]` to `[world_model.backend]`,
`fork_being` to `fork_entity`, "gestational stimulus" to "developmental
stimulus", "gestation entrainment marker" to "heartbeat entrainment marker");
and the alias tables the runtime reads (config tables and keys, environment
variables, CLI flags, plugin seams, stream names and record fields for
readers, state paths, collection names, stage values and fields, bundle keys).
Each entry carries the PR scope that completes it, which the guard reads. It is
the only file in live code where an old name is spelled, besides the codemod's
fixtures. It imports nothing, so the import-linter layers are unaffected.

The table is injective, and no new name contains an old name as a component.
The codemod asserts both at start, which is what makes a second run a no-op.

### The codemod

`tools/maintainer/rename_modules.py [--scope S] [--only NAMES] [--apply | --check]`.

- **Scopes.** `prose` (Markdown prose and code comments: capitalized proper
  names and the listed developmental phrases), `identifiers` (Python names,
  module paths, file and directory names, test file names, import-linter
  contracts, docs code spans that name Python paths), `keys` (module `name`
  values, config tables and keys, bus streams and event types, plugin seams,
  `STUDY_ALLOWED_TABLES`, docs code spans that name them), `operator`
  (environment variables, CLI flags, pip extras, quadlet and compose names, UI
  strings) and `persisted` (state paths, file names, collection names). A PR
  runs one scope, optionally for a subset of names.
- **Parsing.** Python through `tokenize`, so NAME tokens, string tokens and
  comments get different rules. TOML line by line (table headers, keys, string
  values). Markdown with fence and code-span awareness: code gets the
  identifier and key rules, prose gets the prose rules. YAML, shell, quadlet,
  HTML, JS and CSS get key rules on listed patterns only.
- **Identifier rule.** The old name is replaced as a component of an
  identifier split at underscores and case changes: `ThymosModulator` to
  `AffectModulator`, `thymos_state` to `affect_state`, `THYMOS_STREAM` to
  `AFFECT_STREAM`. CamelCase takes the class form, snake_case the key form,
  upper case the upper key form.
- **Context rules for English words.** `spot`: `Spot` as a proper name, and
  lowercase only in key or identifier position (`[spot]`, `spot.`, `spot_`,
  `"spot"`, `kaine/cycle/spot.py`), never "spot check" or `spotLight`. `echo`:
  `EchoModule`, `ECHO_STREAM`, and `echo` as a module key in Python and TOML;
  never in shell, Dockerfiles or quadlet `ExecStart`. `perception`:
  `PerceptionLocus`, `kaine/modules/perception/`, the `[perception]` table,
  `[modules].perception`, the module key `"perception"`, `perception.out`,
  `perception.locus.*`, `intent.perception.switch`, `state/perception/`, and
  the prose "Perception locus"; never `perception_feed`, `perception_preview`,
  `perception_state`, `perception_transition` and `perception.transition`
  (the stimulus-source-to-world crossfade), `perception_prng`,
  `KAINE_PERCEPTION_PREVIEW`, the `perception` pip extra or the plain word.
  The bare string `"perception"` is ambiguous: the feed in
  `kaine/boot/perception_feed.py` also publishes with `source="perception"`.
  So the key rule applies to it only in the locus's own files and in the
  module lists (`[modules]`, the setup wizard, the stream registry); every other
  occurrence goes to the review queue.
  `being`: identifier components (`fork_being`), `beings`, `being's`, and the
  listed phrases ("the being", "a being", "each being", "this being", "every
  being", "preserved being"); never the verb. `birth`, `gestation`, `womb`:
  every match, through the phrase table first so "gestational stimulus" and
  "birth bloom" come out right.
- **Review queue.** A match that no rule decides (a sentence-initial
  "Perception", a lowercase "spot" in prose) is left unchanged and listed in
  the report for a person to resolve with an explicit override.
- **Collision check.** Before writing, the codemod lists every file where a
  new name is already bound or already used as a string key. For `Sequence` it
  applies the `SequenceModule` import alias. Any other collision stops `--apply`
  until the table has an override for it.
- **Exclusions.** `openspec/changes/archive/**`, `docs/records/**` (with
  `history/`, `audits/` and `shakedowns/`), `CHANGELOG.md` below the
  `[Unreleased]` heading, `kaine/nexus/static/vendor/**`,
  `kaine/nexus/static/fonts/**`, `external/**`, `THIRD_PARTY_LICENSES.md`,
  `unsloth_compiled_cache/**`, `kaine.egg-info/**`, `data/**`, `state/**`,
  `backups/**`, `secrets/**`, `.git/**`, `kaine/decision/schema.py` and
  `kaine/decision/systemone.jinja` (K1-Jev question and prompt text),
  `eval_probes/**` and `kaine/modules/hypnos/eval_probes/*.jsonl` (data files;
  the directory moves with its package, the bytes do not change), the
  `[individuation].disclosure` value, active change directory names, and
  `kaine/legacy_names.py` itself. Only tracked files are visited.
- **Moves.** Directory and file renames go through `git mv` first, then
  contents are rewritten, so history follows the files.
- **Report.** The dry run prints, in sorted order with no timestamps: moves,
  per-file counts per rule, the collision list and the review queue. Two runs
  on the same tree print byte-identical reports. `--check` exits non-zero if
  anything in the requested scope would change.
- **Idempotence.** A second `--apply` changes nothing, which a test asserts.
- **Gate files.** `tools/maintainer/preflight-gate.sh`,
  `.github/workflows/redteam.yml` and `.github/slow-test-paths.txt` name test
  files such as `tests/test_nexus_routers.py` and `tests/test_praxis_effectors.py`.
  They are in scope, so the PR that moves a test file also updates the gate
  that runs it.

### Entity-facing text

The disclosure string in `[individuation].disclosure` is read to the entity, so
the codemod never changes it: a rule-driven rewrite must not change what the
entity is told. The owner decided (2026-10-11) that it becomes
"You are periodically and privately assessed for how much you have changed since you first woke, for your own protection. The assessment never enters your experience."
The docs prose PR (step 3) sets it by hand, with the docs that quote it
(task 4.3).

### Compatibility

There has been no live run, so internal names can
break cleanly. Two kinds of data must stay readable: preserved entity state
and recorded datasets. Operator-facing names get a bounded window.

**Clean break, no alias.** Python packages, modules, classes and functions
(the only consumer outside `kaine/` is the in-tree kaine-cl1 plugin, renamed
in the same PRs, and nothing under `kaine/` pickles a class path, so no stored
file names a Python module); the module `name` values on the live bus and the live stream and
event names (producers and consumers rename in one PR, Redis streams are
capped by `maxlen`, and no recorded live run exists); Nexus UI strings, cookie
names and local-storage keys (a dashboard user signs in again); docs; tests;
the five test-only `KAINE_*_RUN_REAL_*` variables; log file names
(`spot.log`, `nexus.log`), which start fresh.

**Operator names, read with a warning for a bounded window.**

- Config: `kaine.config` normalizes each layer (shipped, profile, tier,
  operator, study) before it merges, using the table. An old table or key is
  moved to its new name and the layer logs one line, for example
  `config: config/kaine.operator.toml uses deprecated names [thymos] -> [affect], [modules].thymos -> [modules].affect; they are read until 27.01`.
  A layer that sets both the old and the new name for the same table or key
  fails to load. Value aliases are covered too (`mode = "womb"` reads as
  `mode = "stimulus_source"`). The study allowlist and `require_known_keys`
  run after normalization, so their messages name the new tables.
- Environment variables: a lookup helper reads the new name, then the old one
  with the same one-line warning. If both are set and differ, startup fails.
  That matters for `KAINE_NEXUS_TOKEN` (a secret, never printed) and
  `KAINE_MUNDUS_OPERATOR_APPROVED` (a safety approval): two disagreeing
  values must not silently resolve either way. The compose `NEXUS_*` variables
  get the same treatment in the compose files.
- CLI flags: `--serve-nexus`, `--db-gestation` and `--gestation-budget-seconds`
  stay as hidden argparse aliases with the warning.
- Plugin seams: `oscillator.<old>` and `<old>.<seam>` resolve to the new
  seam with the warning; run manifests record the new name.
- Packaging: `kaine[nexus]` stays as an extra that pulls `kaine[dashboard]`,
  and `python -m kaine.nexus` stays as a three-line shim that warns and runs
  `kaine.dashboard`, so an installed unit keeps working after an image pull.
- Window: the warning names the last release that reads the old names, which
  is the second release after the one that ships the rename and no earlier
  than 90 days after it (versions are `YY.MM.patch`). A follow-up change,
  `functional-module-names-drop-aliases`, removes these aliases.

**Preserved entity state and recorded datasets, readable for good.**

- Preservation bundles, snapshots and fork sidecars are never rewritten: they
  are hashed, and some are encrypted. Import maps old module keys, the
  manifest's `modules` list, the `gestation/` member directory, stage values
  and field names to the new names. The four bundles in `backups/` and the
  nine fork trees in `state/forks/` on this host are the test of record.
- Recorded datasets (research event log, raw bus archive, Nexus record,
  ignition log, evaluation sidecar JSONL, sleep snapshots) are append-only and
  in places encrypted, so they are never rewritten. Their readers map old
  stream names, `source` values, per-module record fields (`thymos_state`,
  `chronos`) and sidecar directory names on read. New records use new names.
- The K1-Jev records carry no old name (measured above), so they need no
  alias. They and the K1-Jev question text are excluded from the codemod,
  because the dataset manifest hashes them and any byte change invalidates the
  build.

**The live state tree, migrated once.** A boot step,
`kaine.lifecycle.rename_state`, runs under the state lock before the identity
and stage reads. It moves `state/<old>/` to `state/<new>/` and old file names
to new ones, rewrites the stage file's value and field names, renames the
sqlite-vec database file and rewrites its `collection` column in one
transaction, and points a Qdrant alias with the new collection name at the old
collection (no copy). It writes a manifest of every move so `--revert` can undo
it, is a no-op on a migrated tree, and fails the boot if an old and a new name
both exist for one item. The same function runs on a fork tree when it is
revived or merged and on an extracted bundle before import. Podman volume names
(`kaine-nexus-record`) cannot be renamed and keep their `VolumeName=`; only the
unit file names change.

**Never-regress.** Two old names guard the developmental arc and keep their
meaning for good. `_coerce_stage` maps the stored value `gestation` to
`development`. Without that, an unknown value reads as embodied, which would
end the developmental phase of an entity still in it.

Reading an unknown value as embodied is fail-open, and the rename removes it
independently of the alias. A stored stage value that is not a string, or not
one of `development`, `embodied` or the aliased `gestation`, makes the stage
reader raise and the cycle refuse to boot. The message names the stage file and
the value's `repr`, truncated to 64 characters. A garbled or forward-versioned
file then stops the boot for an operator to inspect, instead of silently moving
the entity to either stage. A missing `stage` key keeps its current meaning. `OWN_LIVED_ARTIFACTS`
lists both the old and the new paths, so a tree that has not been migrated,
such as a fork root or bundle root, is still recognized as lived.

### Compatibility readers as built (PR 4)

The readers live in `kaine/legacy_aliases.py` and read the table at call time.
Each one acts only on entries whose scope the table marks done, so every reader
in this PR is inert and each is tested with a synthetic entry. The choices below
are the ones the sections above leave open; each follows from those sections.

- **Last release.** The table holds `ALIAS_LAST_RELEASE = "27.01"`, the name
  every warning quotes. It is a placeholder that the close-out step (10.2) sets
  by the rule under Window above.
- **State paths.** The three `STATE_PATHS` entries that had bare file names now
  carry their directory (`lifecycle/`, `individuation/`), because
  `rename_state` works from the state root.
- **Config.** `_load_merged_config` normalizes each layer as soon as it is
  parsed, before the tier's module-toggle refusal and the study allowlist, so
  both see the new names. A layer that sets an old and a new name is a
  `ProfileError`, which the cycle reports as a configuration error. A value alias
  is matched on the new key path after the table and key renames. The
  dashboard's own loader normalizes its three files the same way.
- **Environment.** `getenv` covers `ENV_VARS` and `COMPOSE_VARS`, not the
  test-only variables, and warns once per old name per process.
  `check_environment()` runs at cycle and dashboard start-up, so a pair that
  disagrees stops the start even when the variable is read later (the
  embodiment approval is read when the module is built). The compose files keep
  their `${NEXUS_*}` references until step 7 renames them; that step writes the
  fallback (`${DASHBOARD_X:-${NEXUS_X}}`) in the same edit.
- **CLI and seams.** An old flag is added as a hidden alias only when the parser
  has the new one; the ignition study's parser moved into `_build_parser()` to
  take it. `--serve-nexus` exists only in `scripts/prepare-headless-host.sh`, so
  its alias lands with that script's rename in step 7. Plugin seams resolve
  before validation, the run manifest records the new seam, and the plugin is
  still called with the module name it declared.
- **Read-maps.** Nothing on disk is rewritten. A record that holds an old and a
  new field keeps the new one and logs one warning per pair; recorded data cannot
  be corrected, so it is not refused. A bundle member under a new name beats the
  same member under an old name whatever the tar order. Evaluation readers also
  look in a sidecar directory written under an old name. The manifest's
  `modules` list, the raw bus archive and the dashboard record have no reader in
  the repository, so only the local-data test reads the manifest list.
- **Stage.** `StageValueError` is deliberately not a `ValueError`, so the
  fail-safe for an unreadable file cannot swallow it. An unreadable or
  unparseable file keeps its embodied reading (the delta spec covers stored
  values only). A file that parses but whose top level is not a JSON object
  (`null`, `[]`, `0`, `""`, `false`) is refused like an unrecognized value,
  because it used to read as the developmental stage and could regress a lived
  entity. A JSON object without a `stage` key (`{}`) still reads as the
  developmental stage; that is a decision, kept because a fresh entity's first
  write and the defaults rely on it, and it is pinned by a test. The cycle checks the stage file right after the data root is installed,
  before any gate, revive or boot step, and exits with 13
  (`STAGE_REFUSED_EXIT`). The check also runs when reviving, so an operator
  moves a bad file aside first. A revive refuses a bundle whose stage value is
  unrecognized or whose stage member is not a JSON object, and names the bundle's
  `stage.json`.
- **Lived history.** `OWN_LIVED_ARTIFACTS` lists old and new paths. The legacy
  tree digest writes the old name for a new path, so renaming a tree's
  directories cannot change the legacy identity derived from it.
- **`rename_state`.** It plans only from active entries, so it does nothing
  until the persisted scope is done. Order: module directories, state files with
  their SQLite companions (`-wal`, `-shm`, `-journal`), the stage file, the
  `collection` column, Qdrant aliases. A `vec0` partition key cannot be updated
  in place, so the vector table is rebuilt in the same transaction with each
  row's id and embedding kept. Every refusal is checked before the first write,
  and the manifest is written before the first move. Each step decides from the
  disk whether it ran, so a re-run resumes and `--revert` undoes in reverse
  order and then removes `.rename_state/`. The database reverts by the inverse
  mapping (same rows, possibly different file bytes); a companion that SQLite
  checkpointed away does not block a revert; the stage file comes back from a
  per-step byte copy. Every manifest path is checked to stay under the root,
  symlinks are refused (an operator resolves a linked module directory first),
  the manifest's shape is validated before any step, created directories must be
  parents of their destination, stage backups must sit in `.rename_state/`, and
  a Qdrant alias is removed only while it still points at the recorded
  collection. A revert checks every step first (moves, the chain of stage
  hashes and their backups, Qdrant aliases) and writes nothing when one cannot
  be undone. A move whose source and destination are both missing counts as
  reverted, because a file nested in a moved module directory is in that state
  whenever the directory sits at its old name. Planning refuses a database it
  cannot read (locked, or with a hot journal) and tolerates only a missing
  `memories` table. The manifest and the stage backups are fsynced, file and
  directory, before the first move and on every status write. Qdrant is an
  explicit choice: `migrate` takes a client or `no_qdrant=True` and the command
  line takes `--qdrant-url` or `--no-qdrant`, so no run leaves the Qdrant store
  under its old names by accident; the boot wiring (9.1) passes the configured
  client. The explicit `ROLLBACK` in the collection rewrite is belt and braces:
  SQLite also discards an uncommitted transaction when the connection closes,
  so a test can show the database unchanged after a failure in the middle of
  the `vec0` rebuild but cannot tell the two apart. The code has no state lock today, so the boot wiring (9.1) must
  run it before anything opens the state; the command line is for an operator
  with the cycle stopped.
- **Left for later steps.** The episodic memory module stores its
  `collection_prefix` inside its own snapshot state; when step 8 renames the
  collections, that stored prefix needs the same map. The loose legacy bundle
  layout is found by its `phantasia/` directory on disk, and
  `extract_bundle_gestation` compares against the literal `gestation/` prefix
  and `BUNDLED_GESTATION_FILES`; step 6 renames those literals and must keep
  the old directory lookup.
- **Before the keys scope flips (PR 6).** Some readers parse raw TOML or hold
  literal module names outside the normalized config path, and each must
  normalize or map before step 7 marks the keys scope done:
  `kaine/research/ignition_study/overlay.py` (a literal `["hypnos"]`),
  `kaine/setup/wizard_core.py`, `kaine/setup/web/app.py` and
  `kaine/nexus/health/config.py` (raw TOML reads). A plugin that declares both
  an old seam and its new seam must be refused rather than deduplicated, so a
  plugin cannot fill one seam twice under two names.
- **Before the persisted scope flips (PR 8).**
  `kaine/research/ignition_study/runner.py` reads `birth_bloom_ends_at`
  straight from a line's `stage.json`, outside `StageState.from_dict`, so it
  does not see the stage field map; it must read through the stage reader or
  map the field before the persisted scope is done.
- **Codemod fixes found in PR 5a.** Six scope rules were corrected before the
  first identifiers run, each with a fixture case: a dotted module path inside
  code held in a string (`"from kaine.modules.x import Y"`) follows the
  identifiers scope; a string holding exactly a class or constant name (an
  `__all__` entry, a quoted forward reference) is read as a whole string and
  follows the identifiers scope; a plugin's own OpenSpec spec folders move with
  the keys scope, like the repository's; a `/` path chain that starts at a
  repository top directory is a source path, not persisted state; a dotted
  string starting with `plugins.` is a config key path, not an import path; and
  a `parametrize` argnames string or the attribute-name argument of `getattr`
  and its siblings follows the identifiers scope. While PRs 5a to 5d are in
  flight a module's package can differ from its key; `tests/_module_packages.py`
  maps one to the other for the tests that relied on them being equal.
- **Config keys feeding constructor arguments.** Several factories copy config
  keys straight into constructor keyword arguments. An identifiers PR renames the
  parameter (`interoception_stream`) one step before the keys PR renames the key
  (`soma_stream`), which broke the affect module's build from the shipped config
  in PR 5a before it merged. `kaine/boot/config_kwargs.py` maps each key
  to the parameter it feeds by renaming its old module-key components through the
  table, so there is no second list and the map becomes the identity once the keys
  are renamed. `tests/test_factories_from_shipped_config.py` builds every module
  factory from the shipped config, the base-thesis profile and each tier profile.
- **Close-out by hand (PR 9).** `external/internvideo_next/UPSTREAM` (line 47) and
  `external/internvideo_next/__init__.py` (line 9) name
  `kaine/modules/topos/internvideo_next_loader.py`, which moved to
  `kaine/modules/vision/`. The codemod excludes `external/`, but these are our own
  pointer comments, so the close-out fixes them by hand.
- **Found in PR 5b.** Four more codemod rules, each with a fixture case: a Python
  identifier equal to a `PERSISTED_EXACT` key (a dataclass field written by
  `asdict`, such as the stage file's `hypnos_cursor`, now listed in
  `PERSISTED_EXACT` and `STAGE_FIELDS`) takes the persisted scope, including its
  attribute accesses, so it never diverges from the key it is read back by; a file
  name ending in `.html`, `.js`, `.css`, `.jinja` or `.j2` follows the file it
  names; a `/` chain in a statement that uses `__file__` is a source path; and a
  repository path in free text inside a Python string follows that path's move
  scope. Path overrides send the world model's backend module to `backend.py` (the
  key override already rewrites the import path that way) and keep four test file
  names from stuttering. The codemod leaves excluded data files where they are, so
  the sleep module's capability probes were moved with `git mv` by hand; PR 5d's
  modules carry no such files. `python -m kaine.lifecycle.mnemos_recover` stays as a
  deprecation shim (listed in `PACKAGING`, dropped by
  `functional-module-names-drop-aliases`), and `tests/test_persisted_names_pinned.py`
  pins the collection names and state paths to the table until the persisted scope
  is done.
- **Case boundaries (after PR 5b).** The name pattern matched an old name only at
  the start of a word, so a Capitalized old name after a lowercase letter
  (`StaticThymosModulator`, `FakeSoma`) was never renamed. The Capitalized form
  now matches at any case change and the UPPER form only as a whole upper-case
  word; the seven modules renamed so far were re-run for the leftovers. A
  `__file__`-relative path takes the move scope of the path it resolves to, and
  the template and asset file-name rule sits below the quadlet and compose check.
- **Found in PR 5c.** One more codemod rule, with a fixture case: every element of
  an `__all__` list or tuple, assigned with `=` or extended with `+=`, is an
  identifier, where before only the first element was. Two key overrides send
  `workspace.syneidesis` and `workspace/syneidesis` to `workspace.core` and
  `workspace/core`, because the workspace module already lives in the
  `kaine.workspace` package and the plain rule would give
  `kaine.workspace.workspace`. Two more path overrides keep test names from
  stuttering (`tests/test_effectors.py`, `tests/test_workspace_core.py`), and the
  repository dry-run test now fails on any planned move, or any tracked file, whose
  name repeats a new module key. Fourteen collisions are accepted in
  `ACCEPTED_COLLISIONS` after a check by hand. One was a real clash: in
  `kaine/boot/wiring.py` the effectors module and the list of its effector names
  shared a local name, so the list is now `effector_names`. Strings that name a
  renamed Python symbol are outside the identifier rule and were fixed by hand: a
  test's keyword dict for the individuation scheduler (`language_idle`) and runtime
  (`language`), the boot phase list (`_phase_action_selection`), two source-text
  assertions on `action_selection_cfg`, and the red-team case kinds, which select a
  driver method by name and are now `planning_proposal_*`. The case ids, which
  reports carry, keep their old text. A guard test checks that every red-team case
  kind has a driver. Comments and docstrings that name a renamed function (such as
  `make_lingua` or `_phase_volition`) keep the old name, as in 5a and 5b, because
  comments take the prose rules; the close-out sweeps them.
- **After PR 5c.** Review found two side effects. The string rule for exact class
  names also renamed three dashboard labels (`role="Vox"` in the health probe
  config). Those are operator text, so they are back to their old value, and a
  string passed as a `role=`, `title=` or `label=` keyword argument now takes the
  operator scope (fixture `label_kwargs`); the dashboard labels move in PR 7. The
  `recorded_by` field in `tests/fixtures/planning_golden/*.json` names the script
  that recorded the fixture, and it changed with the script's rename. That is
  accepted: recorded provenance strings in test fixtures follow script renames,
  since they name a file in this repository rather than a value any reader
  compares.
- **Found in PR 5d.** The guarded names needed decisions. Only the perception
  locus module's own handles rename (its factory, its stream constant, and test
  names and locals that hold the module); every other perception identifier names
  the wider perception subsystem and keeps its name, as do the template
  `_perception_banner.html`, `PerceptionState`, `check_perception` and the preboot
  group label. Only the test locals that hold `EchoModule` rename; the other echo
  names mean a verbatim repeat. `SPOT RECOVERY` and the dashboard's JavaScript
  globals (`window.NexusVitals` and the rest) wait for the UI strings in PR 7. The
  413 matches still in the review queue are strings, prose and UI files for the
  keys, operator and prose steps: a probe run that renames every queued match
  changes nothing in the identifiers scope. Five more codemod rules, each with a
  fixture: a web asset or template file name, or a `.py` file name, in a Python
  string or a `/` chain follows the identifiers scope (`web_asset_names`,
  `source_file_operands`); dotted module paths in an import-linter contract follow
  it (`import_contracts`); a dotted class-name string such as a nested-class
  annotation follows it (`string_annotations`); and a module path segment that
  equals a persisted name (`kaine.cycle.gestation`) is not held by the persisted
  rule (`persisted_names_in_import_paths`). Path overrides keep test names
  readable (`test_perceptual_locus.py`, `test_development_lock.py`,
  `test_stimulus_sources.py`). The dashboard's font and vendor folders are
  excluded from rewriting and moved by hand. `python -m kaine.nexus` keeps
  working through a deprecation shim, brought forward from PR 7 because the
  package moved here; it is listed in `PACKAGING` and excluded from the codemod.
  `parameter_for_config_key` moves to `kaine.legacy_aliases` and also maps the
  developmental terms, so `[perception_feed.womb].birth_transition_seconds` feeds
  `maturation_transition_seconds`. Fixed by hand, because no codemod rule reaches
  them: argparse attributes whose flag keeps its old name (`--db-gestation` now
  has an explicit `dest`), a dict built from dataclass field names and read with
  an old key (the dashboard health config), keyword arguments that a test helper
  merges into a config dict, a module imported by its bare name
  (`from kaine.cycle import gestation`), a program held in a string, and the
  JavaScript test harness paths. The sentinel file
  `individuation/birth_pending` is persisted state that `STATE_PATHS` does not
  list yet; the persisted step should add it. With every layer renamed, the
  table marks the identifiers scope done, so `tests/test_module_names_guard.py`
  now fails on any change that brings an old identifier back.
- **After review of PR 5d.** A renamed dataclass field can change stored bytes
  when the whole dataclass is serialized. `womb_params_digest` hashed
  `asdict(StimulusSourceParams)` and the feed descriptor wrote it to run
  manifests, so renaming `birth_transition_seconds` changed the digest that every
  matured entity keeps in `stage.json`. Both now go through
  `kaine/lifecycle/stored_field_names.py`, which maps renamed fields back to their
  stored names, is excluded from the codemod and stays fixed for good (later
  steps must not rename those stored names either); a golden test pins the
  default digest and the descriptor bytes. An audit of every record class field
  renamed in PRs 5a to 5d against every `asdict`, `fields`, `vars`, `__dict__`,
  `model_dump`, `_asdict`, keyword-built dict and structure digest found no other
  case: the rest are written through explicit old keys or never reach disk, a
  hash, a manifest, the bus or a record. Also after review: `gestating` joins the
  developmental table (`is_gestating` becomes `is_developing`; the gate action
  value `"gestating"` keeps its text and is pinned); a Markdown link whose target
  is a directory now follows its path (fixture `directory_link_targets`); the
  codemod exclusions name the moved vendor and font folders; the done-scope guard
  plans once for all done scopes, is slow-marked, and runs on every pull request
  in CI and in the gate; and `individuation/birth_pending` joins `STATE_PATHS`.
- **Local data.** `tests/test_legacy_local_data.py` runs only when
  `KAINE_LOCAL_DATA_ROOT` is set. It copies `backups/` and `state/forks/` to a
  temporary directory, reads everything from the copy with every read-map on,
  checks that the real trees did not change, and deletes the copy. An encrypted
  bundle is checked by its manifest only, and an encrypted fork snapshot is
  skipped, unless `KAINE_STATE_KEY` is set.

### Keys step, split in two (PR 6a and 6b)

The keys step changes wire names, so it lands in two PRs. **6a** prepares: every
reader it adds acts only once the keys scope is done, and the fast suite's outcomes
match main's test by test. Its runtime changes are deliberate and few: the
perception feed publishes on its own stream (the only bus name 6a changes), the
maturation gate counts sleeps once more when it stops (under the same preconditions
as a tick, so it never counts what a tick would have skipped), the individuation
refusal names the config key `[modules].lingua`, and merging snapshots prefers an
artifact directory already under the current name. **6b** runs the codemod, moves
the files, marks the keys scope done and so turns the readers on.

What 6a decides, from a keys-scope dry run on main (72 moves, about 10.5k
replacements in about 900 files):

- **Config keys.** `CONFIG_KEYS` now lists every config key the keys run renames
  (twelve more compound keys such as `soma_stream`, `lingua_quiet_s`,
  `salience_thymos_factor`, `nexus_url`), every module key used as a key inside
  another table (`[evaluation.observers].empatheia`, a plugin's backend and
  territory tables; the guarded names rename only in `[modules]`), and every
  stream name used as a key (`[bus.per_stream_maxlen]`). `research_event_log.nexus_record`
  joins the table moves. The normalizer also maps stream names used as values or
  list items and the tier's `unsupported_modules` list. The bus configuration, the
  study overlay, the setup page and wizard and the base-thesis profile reader read
  their TOML raw; each now normalizes every layer, so an operator file with old
  names merges under the new ones and a layer that sets both names is refused.
- **Strings inside stored files stay.** A keys-scope string that is a key or value
  inside a file on disk (records, reports, the development readout, run
  manifests, study plans, job files, sidecar directory names) joins
  `PERSISTED_EXACT`, so the keys run leaves it and the persisted step decides it
  with read-maps: the affect, sleep, social-cognition and planning record fields,
  the self-model drift signals, the workspace-mediation benchmark fields, the
  world-model cue, model revisions in run manifests, the stimulus-source readout
  and reasons, the supervisor escalation reason, the forked job kind,
  `gestation_budget_seconds`, and three sidecar directory names. The codemod now
  also treats a TOML key equal to such a name as persisted.
- **Strings the UI reads move with the UI.** Template context variables, the
  dashboard's health block key, the runtime keys the supervisor banner reads and
  the session cookie name go to the new `OPERATOR_EXACT` list, so they change with
  the dashboard strings in PR 7 and the template never reads a missing key.
- **Names that reach disk through code.** Decommission and the public metrics
  bundle's deny list handle every form of a module-named state directory
  (`legacy_aliases.name_forms`), because those directories keep their names until
  PR 8 while the literals change in 6b. Snapshot artifact directories are found
  under any form of the module's name, and a merge maps them to one module. The
  preservation bundle names its world-model member once, so the directory and
  the tar member cannot drift apart. Study plans map their module lists on read,
  and `study.json` is never rewritten, so its hash holds. The control file's freeze
  sources, the self-model's drift-episode source counts and restored per-stream
  cursors read old names.
- **Plugins.** A plugin that declares one seam under its old and its new name is
  refused instead of merged.
- **Queue and collisions.** Every queued perception, echo and spot match in the
  keys scope is decided by a rule: perception renames only as the locus module key
  in module lists and maps (the feed keeps its own source, which also means the
  feed's few transition events, all at salience zero, stop counting as the locus
  module's drive source); echo renames only as the recorder module key; two
  supervisor selftest messages name the config table and rename with it. A probe
  that renames every queued match changes nothing more in the keys scope; the 128
  matches still queued belong to the UI step. Of the 39 collisions, the six test
  files that exercise the readers with old names as literals are excluded from the
  codemod, and the other 26 are accepted after a check (in each the new key
  already has another role in that file and never meets the renamed key in one
  mapping).
- **Stream cursors.** The only stream position that survives a restart in a
  state file is the stage file's `hypnos_cursor`; module snapshots also carry
  cursors (embodiment, interoception, self-model, and the sequence module's
  per-stream map). Redis stream ids are time-ordered and the rename needs a
  restart, so a cursor recorded against `hypnos.out` and used on `sleep.out` reads
  exactly the entries written after the restart: no replay and no skip, and the
  sleep count and the maturation gate see every new sleep once. A stream-keyed
  cursor map is remapped on restore, keeping the value already under the new name.
  There are no consumer groups and no other Redis keys holding state.
- **Redis persistence.** Compose, quadlet and the native scripts run Redis with AOF
  (`appendonly yes`, `appendfsync everysec`) and no RDB, with `maxmemory`
  (4 GB by default) and `noeviction`. After 6b the old streams stay as orphans at
  their caps, and the "Bus budget" preboot row counts only configured streams, so
  the caps alone would let real memory reach twice the budget, where `noeviction`
  turns a full Redis into failed writes. So 6b ships a one-time cleanup: a command
  that lists the old-named module streams and deletes them only when asked, and a
  preboot warning while any remain. Nothing reads those streams after the flip.
- **Config digest.** `compute_config_digest` hashes the resolved configuration,
  so the same settings hash differently once the keys are renamed. 6b records
  `"config_key_scheme": 2` in run manifests (absent means 1), so a comparison
  across the rename is explicitly different rather than silently different.

### Keys step: review fixes and the flipped-tree proof (PR 6a)

A review ran the 6b codemod over the 6a table in a scratch tree and found that
boot, revive and the dashboard broke. 6a now carries these decisions, and a
scratch flip (keys marked done, keys codemod applied, nothing else) passes the
fast suite, the slow lane, a full-registry dry boot, an old-bundle revive, a
checkpoint load and the dashboard smoke.

- **World-model sub-table.** `[phantasia.world_model]` stays a sub-table named
  `world_model` under the moved table, `[world_model.world_model]`; renaming it to
  `backend` collided with the `[phantasia].backend` key and made invalid TOML.
  The normalizer applies single-segment table moves before dotted ones. A copy of
  the pre-rename shipped config, profiles and studies sits in
  `tests/fixtures/legacy_config/`, and a sweep test checks that every layer
  normalizes without conflict and that every config key the codemod renames has a
  mapping.
- **Stored tags.** Strings written to disk keep their spelling until the persisted
  step: the world-model checkpoint header `kaine-phantasia-rssm-npz-v1`, the encoder
  version `phantasia-encoder-v1`, the reference, capture and gate kind `birth`, the
  preservation reason `birth`, the study outcome `failed:gestation_unviable`, and the
  episodic-memory collection names built from the stored `mnemos_` prefix. They are
  in `PERSISTED_EXACT`, the tags also in a `STORED_TAGS` table, and a test pins each
  against the table. The `thymos_state` record field stays with its writers, so its
  read-map moves to the persisted step.
- **Bundle members.** The preservation writer and every reader name the world-model
  and development members through one helper that maps them, so a bundle written
  before 6b and one written after it compare equal on both sides.
- **The developmental owner's bus identity moves with keys.** Its source is derived
  from its stream literal (`DEVELOPMENT_SOURCE`), so source and stream rename
  together while the stored stage value, the freeze source, the locus lock holder
  and the study line of the same spelling stay. An external body adapter must
  publish its presence under the new stream and source after 6b; 6b reads presence
  from both streams until the alias release and logs a one-line deprecation when
  the old one is used.
- **The perception feed gets its own stream now.** Until 6a the locus module and the
  perception feed both wrote `perception.out`, so the rename map's `perception.out ->
  perceptual_locus.out` was ambiguous: a cap for the feed would fold onto the locus
  stream, setting both caps would conflict, and a cleanup of old names would offer
  to delete a live stream. The feed now publishes under its own source and stream,
  `perception_feed` and `perception_feed.out` (`PERCEPTION_FEED_SOURCE`,
  `PERCEPTION_FEED_STREAM`); the rename leaves names starting `perception_feed`
  alone, so `perception.out` belongs to the locus module alone. The feed's stream is
  an additional produced stream with its own cap in `[bus.per_stream_maxlen]`. No
  read alias is needed: no reader selects the feed's events by stream name (the
  research event log subscribes to the produced set live and keys on the event type
  `perception.transition`), and nothing replays the feed's history. The feed's
  transition events, all at salience zero, stop counting as the locus module's drive
  source; that change is accepted.
- **Text rules.** An f-string is classified like a plain string, by whether its
  literal text holds a space. Inside such text a config table, key, stream or event
  reference (`[vox].x`, `topos.encoder`, `soma:soma.report`, a TOML key at the start
  of a line) moves with keys and takes the key form, while a bare word in a
  sentence and a capitalized display label stay for the operator step. Kebab-case
  names in Python strings (container and volume names, element ids, header names)
  and HTML attributes inside Python strings are operator-facing. Bus event types
  that look like file names (`spot.log`) are listed in `EVENT_TYPES` and move with
  keys.
- **Dashboard wire names (review item 6).** The two sides agree in every state. The
  session-key header, the login element ids and the other UI strings stay old on
  both sides until the operator step (PR 7). The bus sources and event types the
  dashboard script matches (`msg.source === "thymos"`, `"soma.report"`,
  `"nexus.snapshot"`, `"hypnos.sleep.started"`, `"spot.log"`) move with Python in
  6b: in a dashboard script or test harness a quoted dotted wire name, or a quoted
  name compared with a message source, belongs to the keys scope. The dashboard
  smoke checks that the script sends the header the server checks, that the login
  page has the ids the script reads, and that every wire name the script matches
  is one the Python side names.
- **Sleeps at shutdown.** The maturation gate counts sleeps once more when it stops,
  so a sleep completed after the last tick is not lost when the stream is renamed at
  the next start.
- **The 6b cleanup command.** Its candidates come from
  `legacy_aliases.orphaned_stream_names(live)`: every old name in the stream map
  (module output streams, the developmental and language streams, `STREAM_NAMES`)
  minus every stream a producer writes now, and nothing at all while keys are
  pending. A test runs the codemod over the real stream modules and checks that no
  stream written after the flip is a candidate (it caught the shared
  `perception.out`). The command shows each candidate's length and memory use,
  deletes nothing by default, and deletes only with an explicit confirmation.
- **History continuity (built in 6b).** Two readers replay history, and an empty new
  stream is the wrong test for both, because the new stream receives events right
  after the restart:
  - The language module's `sleep_index` backfill looks for the last sleep event. It
    reads the new sleep stream; when no sleep event is found there, it reads the old
    stream (`hypnos.out`) for one, then continues on the new stream.
  - The dashboard's conversation history reads the old stream (`lingua.external`)
    and then the new one (`language.external`), merged in id order (ids are
    time-ordered across both), for as long as the old stream exists, that is until
    the cleanup command removes it.
  A helper returns a stream's old name from the table, so each reader names its
  fallback in one place.
- **Rolling back across the flip is unsupported.** After 6b runs, a release from
  before 6b would read the new names in config files, streams, bundles and run
  records as unknown. The supported path is forward only; an operator who must go
  back restores the backup taken before upgrading.
- **Two UI names stay until the operator step.** The session-key header
  `X-Nexus-Session-Key` (code, docstrings and the browser script) and the browser
  storage key `nexus.preservation.events` are operator/UI names. Keep rules hold
  them through the keys step so the server, its documentation and the browser keep
  agreeing; PR 7 renames them with the other UI strings.

### PR sequence

Each PR runs the codemod (or adds infrastructure), passes
`tools/maintainer/preflight-gate.sh`, and leaves main consistent, because the
compatibility readers land before anything they read is renamed. The owner's
outline (prose, then code by layer, then config aliases, then persisted names)
is kept, with the compatibility readers moved ahead of the first rename: a
renamed config table, stream or state path is only safe to merge alone if its
alias already exists.

1. **Codemod and table.** `kaine/legacy_names.py`, the codemod, its fixture
   tests, and the grep guard with every scope marked pending. No rename.
2. **Collision pre-renames.** `WorldModel` protocol to `WorldModelBackend`,
   `SelfModel` document to `SelfModelDocument`, by hand, small.
3. **Docs prose.** `--scope prose`: the book, READMEs, live spec prose and
   active-change prose; code spans untouched. Adds a "Module names" page that
   maps old to new names for readers during the transition. The 18
   `docs/09-modules/` page files move here.
4. **Compatibility readers.** The config normalizer, the environment-variable
   helper, CLI aliases, seam aliases, bundle and dataset read-maps, the
   `rename_state` step, the never-regress aliases, and the fail-closed reading
   of an unrecognized stage value. Each alias is inert until
   the table marks its scope done, and each is tested with a synthetic entry.
5. **Identifiers by layer.** `--scope identifiers`, four PRs: (a) Vision,
   Interoception, Sequence; (b) Affect, Sleep, Episodic memory, World model;
   (c) Language, Vocal, Planning, Action selection, Effectors, Self-model,
   Social cognition, Workspace; (d) Embodiment, Perceptual locus, Supervisor,
   Dashboard, Recorder and the developmental terms. Module `name` values,
   streams, tables and paths keep their old strings.
6. **Keys and wire names.** `--scope keys`, one PR: module `name` values,
   streams and event types, config tables and keys in the shipped config,
   profiles and studies, plugin seams, `STUDY_ALLOWED_TABLES`, live spec folder
   names with the matching delta folders in active changes. The config,
   seam, bundle-key and dataset aliases from PR 4 go live here. This cannot be
   split by module, because one stream links modules from different layers.
   Before the scope flips, the raw TOML readers and the literal module list
   named under "Compatibility readers as built" normalize or map, and a plugin
   declaring an old seam and its new seam is refused.
7. **Operator surface.** `--scope operator`: environment variables, CLI flags,
   the pip extra and entry-point shim, quadlet and compose names, UI strings.
8. **Persisted names.** `--scope persisted`: state paths, file names,
   collection names and stage values in code; `rename_state` goes live, with
   the boot wiring passing the configured Qdrant client (or `no_qdrant=True`
   when the store is sqlite-vec only).
9. **Close-out.** The guard turns strict, the CHANGELOG gets its
   `[Unreleased]` entry, the configuration appendix lists the deprecated
   names and the last release that reads them, and the follow-up change for
   alias removal is opened.

PRs 3 and 4 do not depend on each other. PRs 5a to 5d can merge in any order
after 2. PRs 7 and 8 can swap.

## Risks / Trade-offs

- **In-flight branches conflict.** About 30 worktrees exist. Mitigation: the
  codemod is deterministic, so a branch takes main's side of a conflict and
  re-runs `--scope <done scopes>` on its own diff.
- **A false positive slips through.** Mitigation: rules, not judgement, decide
  every change; undecided matches go to the review queue; the fixture tests
  carry each known false positive (`spotLight`, shell `echo`, "being
  overwhelmed", `perception_feed`, `KAINE_PERCEPTION_PREVIEW`).
- **A rename reaches data it must not.** Mitigation: exclusions are tested,
  `data/`, `state/`, `backups/` and `.git/` are not tracked or are excluded,
  and the K1-Jev and evaluation datasets are checked byte for byte before and
  after.
- **Aliases outlive their window.** Mitigation: the warning names the release,
  and the follow-up change is opened by PR 9.
- **The paper changes a name after the codemod runs.** Mitigation: the table is
  one file; a later change edits the entry and re-runs the codemod.

## Test strategy

- The full suite, through `tools/maintainer/preflight-gate.sh`, on every PR.
- Codemod fixtures: each rule and scope; each known false positive left
  unchanged; exclusions untouched; the `Sequence` alias; idempotence (a second
  apply is empty); a byte-identical report on two runs; the injectivity check.
- Config with old names: a fixture operator overlay with `[thymos]`,
  `[modules].thymos`, `[perception_feed.womb]`, `mode = "womb"`, `[nexus]`,
  `[spot]` and a study with `[syneidesis]` loads into the new tables with
  exactly one warning line per layer; a layer with both names fails; an
  unknown key's error names the new table.
- Environment and CLI: old variable alone is read with a warning; both equal is
  read; both different fails startup, including for the token and the
  embodiment approval; old flags parse with a warning.
- Persisted data: a bundle with old module keys and a `gestation/` member
  imports; `stage.json` with `gestation` reads as `development`; an
  unmigrated tree counts as lived; `rename_state` is idempotent, reversible
  and refuses an old-and-new pair; Qdrant and sqlite-vec stores found under
  old names are reachable under new ones; dataset readers return identical
  records from an old-named and a new-named fixture.
- Grep guard (`tests/test_module_names_guard.py`): for every scope the table
  marks done, `rename_modules.py --check --scope <scope>` must be clean, and a
  scan of tracked files outside the exclusions, `kaine/legacy_names.py` and the
  codemod's fixtures must find no capitalized old module name. The test names
  the file and line of each hit.
