## Why

The owner has decided that the Greek and Latin module names give way to
functional names, each named for the brain system the module models, as ACT-R
and LIDA name theirs. The paper is the authority for the names, and its
`functional-module-names` branch uses the mapping below. The code, the
configuration, the bus, the dashboard and the book must follow it.

The old names reach well past the Python packages. A measured survey (design.md,
"Survey") finds them in 33 live capability specs, 98 dotted stream, event and
config-path literals, 44 tables and 17 module flags in `config/kaine.toml`,
12 operator environment variables, 3 CLI flags, a quadlet unit and a podman volume, the
Nexus templates, Qdrant collection names, state paths, the developmental-stage
file, preservation bundle manifests and recorded evaluation datasets. Four
English words among them (`spot`, `echo`, `being`, `perception`) also occur in
their ordinary sense, and three target names (`WorldModel`, `SelfModel`,
`Sequence`) are already bound to something else. A hand rename across about
3,000 tracked files would not be reviewable, so the rename is done by one
deterministic codemod whose rules are what gets reviewed.

**Design only.** This change records the survey, the codemod, the compatibility
decisions, the PR sequence and the tests. No name changes in this change.

## What Changes

The mapping (class / snake_case key / prose):

| Old | Class | Key | Prose |
| --- | --- | --- | --- |
| Topos | `Vision` | `vision` | Vision |
| Audition | `Audition` | `audition` | Audition (unchanged) |
| Soma | `Interoception` | `interoception` | Interoception |
| Chronos | `Sequence` | `sequence` | Sequence |
| Thymos | `Affect` | `affect` | Affect |
| Hypnos | `Sleep` | `sleep` | Sleep |
| Mnemos | `EpisodicMemory` | `episodic_memory` | Episodic memory |
| Phantasia | `WorldModel` | `world_model` | World model |
| Lingua | `Language` | `language` | Language |
| Vox | `Vocal` | `vocal` | Vocal |
| Nous | `Planning` | `planning` | Planning |
| Volition | `ActionSelection` | `action_selection` | Action selection |
| Eidolon | `SelfModel` | `self_model` | Self-model |
| Empatheia | `SocialCognition` | `social_cognition` | Social cognition |
| Syneidesis | `Workspace` | `workspace` | Workspace |
| Praxis | `Effectors` | `effectors` | Effectors |
| Mundus | `Embodiment` | `embodiment` | Embodiment |
| Perception (locus arbiter) | `PerceptualLocus` | `perceptual_locus` | Perceptual locus |
| Spot | `Supervisor` | `supervisor` | Supervisor |
| Nexus | `Dashboard` | `dashboard` | Dashboard |
| Echo | `Recorder` | `recorder` | Recorder |

Developmental terms: gestation becomes the developmental phase (key
`development`), gestational stimulus becomes developmental stimulus, womb
becomes stimulus source (key `stimulus_source`), birth becomes maturation,
being becomes entity, and "gestation entrainment marker" becomes heartbeat
entrainment marker. "Maternal heartbeat" and "maternal drive" stay.

- One mapping table, `kaine/legacy_names.py`, a pure data module. The codemod
  and every runtime alias read it, so no old name is spelled anywhere else in
  live code.
- A codemod, `tools/maintainer/rename_modules.py`, that applies the table by
  scope (prose, identifiers, keys, persisted names), with an explicit exclusion
  list, context rules for the English-word names, a collision check, a
  deterministic dry-run report, and a `--check` mode. Running it twice changes
  nothing the second time.
- Compatibility. Operator-facing names (config tables and keys, environment
  variables, CLI flags, plugin seams, the `nexus` pip extra and the
  `python -m kaine.nexus` entry point) are read under the old name with a
  one-line deprecation warning for two releases and at least 90 days, then
  removed by a follow-up change. Data that must stay readable (preserved entity
  state, recorded datasets) is read under old names permanently and never
  rewritten. The live state tree is migrated once at boot. Everything internal
  (packages, classes, functions, live bus streams, UI strings, test-only
  environment variables, log file names) is a clean break.
- Twelve PRs after this one, in nine steps, each passing `tools/maintainer/preflight-gate.sh`
  and mergeable on its own (design.md, "PR sequence").
- Tests: the full suite on every PR, a config test with the old tables, alias
  tests for environment variables, CLI flags and persisted data, and a grep
  guard that fails when an old name reappears outside the exclusions.

## Capabilities

### New Capabilities

- `module-naming`: the functional module names, the single mapping table, the
  codemod and its exclusions, the deprecation window, and the guard against
  old names.

### Modified Capabilities

- `configuration-loading`: each configuration layer is normalized from old
  table and key names before merging.
- `entity-preservation`: bundles and snapshots written under old module names
  import unchanged.
- `developmental-stage`: a stage file written before the rename keeps its
  phase and its lived status, and an unrecognized stored stage value stops the
  boot instead of reading as embodied.

## Impact

- Code: none in this change.
- Later PRs touch nearly every package under `kaine/`, `tests/`, `config/`,
  `docs/`, `openspec/specs/`, the active changes under `openspec/changes/`,
  `plugins/kaine-cl1/`, `quadlet/`, `compose/`, `pyproject.toml`, `.github/`
  and `tools/maintainer/preflight-gate.sh`.
- Not touched: `openspec/changes/archive/`, `docs/records/`, released
  CHANGELOG entries, third-party code, `data/`, `state/`, `backups/`, the
  K1-Jev records and the K1-Jev question text, and entity-facing text. The owner's
  new disclosure text is set by hand in the docs prose PR (design.md,
  "Entity-facing text").
- Branches in flight conflict with the identifier PRs. The codemod is deterministic, so a branch rebases by re-running it.
