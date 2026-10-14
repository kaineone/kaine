# module-naming Specification

## Purpose
KAINE's modules and developmental terms carry the functional names the paper uses. One mapping table drives the rename, the compatibility readers and the guard that keeps the old names from coming back; stored data stays readable under its old names for good, and old operator names are read for a bounded window.

## Requirements

### Requirement: Modules carry functional names
Each module SHALL be named for the brain system it models, as the paper names
it. The class, the snake_case key (the module `name`, its config table, its
stream prefix, its state directory and its snapshot key) and the prose name
SHALL be: Vision (`vision`), Audition (`audition`), Interoception
(`interoception`), Sequence (`sequence`), Affect (`affect`), Sleep (`sleep`),
EpisodicMemory (`episodic_memory`), WorldModel (`world_model`), Language
(`language`), Vocal (`vocal`), Planning (`planning`), ActionSelection
(`action_selection`), SelfModel (`self_model`), SocialCognition
(`social_cognition`), Workspace (`workspace`), Effectors (`effectors`),
Embodiment (`embodiment`), PerceptualLocus (`perceptual_locus`), Supervisor
(`supervisor`), Dashboard (`dashboard`) and Recorder (`recorder`). The
developmental phase SHALL use the key `development`, its stimulus source the key
`stimulus_source`, its end SHALL be called maturation, and the system SHALL
call the individual an entity.

#### Scenario: A module's key drives its wire names
- **WHEN** the Affect module starts
- **THEN** its `name` is `affect`, it reads `[affect]`, and its output stream
  is `affect.out`

#### Scenario: The workspace class does not shadow the package
- **WHEN** code imports `Workspace` from `kaine.workspace`
- **THEN** it gets the workspace class, and `WorkspaceSnapshot` and the
  `workspace.broadcast` stream are unchanged

### Requirement: One mapping table drives the rename and every alias
The mapping from old to new names SHALL live in one data module,
`kaine/legacy_names.py`, with no imports. The codemod and every runtime alias
SHALL read it. No other live source file SHALL spell an old module name. The
table SHALL be injective, and no new name SHALL contain an old name as an
identifier component.

#### Scenario: The table is checked at start
- **WHEN** the codemod starts with a table in which two old names map to one
  new name
- **THEN** it exits non-zero before reading any file

### Requirement: The rename is applied by a deterministic, idempotent codemod
`tools/maintainer/rename_modules.py` SHALL apply the table by scope (prose,
identifiers, keys, operator, persisted). It SHALL NOT change files under
`openspec/changes/archive/`, `docs/records/`, released CHANGELOG entries,
vendored or third-party code, `data/`, `state/`, `backups/`, `secrets/`,
`.git/`, the K1-Jev question and prompt text, data files under `eval_probes/`,
active change directory names, or entity-facing text. It SHALL change an
English-word name (`spot`, `echo`, `being`, `perception`) only in the contexts
its rules list, and SHALL list every undecided match in its report without
changing it. It SHALL refuse to apply a rename that would bind a new name
already bound in the same file, except through an alias the table defines.
Its dry-run report SHALL be byte-identical across runs on the same tree, and a
second apply SHALL change nothing. `--check` SHALL exit non-zero when anything
in the requested scope would change.

#### Scenario: English words are left alone
- **WHEN** the codemod runs over a file containing `spotLight`, a shell
  `echo`, "being overwhelmed" and `perception_feed`
- **THEN** none of them changes

#### Scenario: Historical records are untouched
- **WHEN** the codemod applies every scope
- **THEN** no file under `openspec/changes/archive/` or `docs/records/`
  changes

#### Scenario: A second run is empty
- **WHEN** the codemod applies a scope and is run again on the result
- **THEN** the second run changes nothing and its report lists no moves

### Requirement: Old names do not come back
A test SHALL fail when, for any scope the table marks done, the codemod's
`--check` would change a file, when a capitalized old module name appears in
a tracked file outside the exclusions, the mapping table and the codemod's
fixtures, or when a snake_case identifier in such a file has an old module or
developmental key as one of its underscore-separated parts and is not one of
the identifiers the table keeps for good. The failure SHALL name each file and
line.

#### Scenario: An old name reappears
- **WHEN** a new docs page says "Thymos" after the prose scope is done
- **THEN** the guard test fails and names that page and line

#### Scenario: A comment names an old factory
- **WHEN** a docstring names `make_lingua` after every scope is done
- **THEN** the guard test fails and names that file, line and identifier

### Requirement: Deprecated operator names are read for a bounded window
Old config tables, keys and values, operator environment variables, CLI flags,
plugin seams, the `nexus` pip extra, the `python -m kaine.nexus` entry point,
the dashboard's session-key header and the variables in `compose/.env`
SHALL keep working under their old names, each use logging one warning line
that names the new name and the last release that reads the old one. That
release SHALL be the second release after the one that ships the rename, and
no earlier than 90 days after it. When an old and a new environment variable are
both set and differ, startup SHALL fail without printing either value.

#### Scenario: An old environment variable is read
- **WHEN** only `KAINE_NEXUS_PORT` is set
- **THEN** the dashboard uses it and logs one deprecation line naming
  `KAINE_DASHBOARD_PORT`

#### Scenario: Old and new approval variables disagree
- **WHEN** `KAINE_MUNDUS_OPERATOR_APPROVED=1` and
  `KAINE_EMBODIMENT_OPERATOR_APPROVED=0` are both set
- **THEN** startup fails and the embodiment module does not start

#### Scenario: A browser sends the old session-key header
- **WHEN** a page loaded before the upgrade sends `X-Nexus-Session-Key` with a
  valid session key
- **THEN** the dashboard accepts it and logs one deprecation line naming
  `X-Dashboard-Session-Key`

#### Scenario: Browser storage under an old key
- **WHEN** the dashboard page loads in a browser that holds a value under an
  old storage key and none under the new key
- **THEN** the page reads that value, writes it under the new key and removes
  the old key

### Requirement: Recorded datasets stay readable under old names
Readers of recorded datasets (research event log, raw bus archive, dashboard
record, ignition log, evaluation sidecar files, sleep snapshots) SHALL map old
stream names, `source` values, per-module record fields and sidecar directory
names to the new names on read, without a time limit, and SHALL NOT rewrite a
recorded file. The K1-Jev gold records SHALL stay byte-identical.

#### Scenario: An old research log is analysed
- **WHEN** an analysis reads a research event log whose records name
  `soma.out` and `thymos_state`
- **THEN** it returns the same records it returns for a log that names
  `interoception.out` and `affect_state`
