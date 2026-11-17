# Unified instance configuration — status (2026-11-16)

Source change: `openspec/changes/unified-instance-configuration/` (proposal, design, and
tasks all marked `Status: PARKED (roadmap item, not active work)`). This record tracks
task disposition against the current codebase. Scope: documentation only — no source
tree changes are involved.

## Verification (no source changes)

Commands run from `/var/home/erik/Projects/kaineone/kaine`:

- `git log --all --oneline | grep -i ...` — no commits reference `unified-instance-configuration`,
  `kaine.reference`, `validate_config` (module), or `configure` (setup module).
- `grep -rn "list_all_defaults\|kaine.reference\|setup.validate_config\|setup.configure"` over
  `*.py`/`*.toml`/`*.md` (excluding the openspec tree) — no matches for the new symbols.
  The only hit is `kaine/config.py:validate_config_shape`, which is a pre-existing
  *internal* shape check and is not the CLI validator this change specifies.
- `ls config/` — no `kaine.reference.toml` present (`config/kaine.toml`, operator override only).
- `kaine/setup/__main__.py` — no `configure`/`validate_config` entry points.
- `kaine/preboot.py` — no `Config valid` row.
- `kaine/setup/wizard.py` — no reference-section question set keyed to tier metadata
  (none exists yet).

Conclusion: the change is entirely unimplemented; every task below is unsatisfied by code.

## Task dispositions

Legend: `parked` = not active work by operator directive; `blocked` = cannot proceed until
a prerequisite lands; `next` = first activatable step when the change is unparked.

### 1. Defaults registry

- `1.1` `list_all_defaults()` in `kaine/config.py` — **parked** — registry helper does
  not exist; `load_kaine_config` has no default-enumeration surface. Blocked on change
  activation.
- `1.2` Test: every runtime-resolved key appears in registry — **parked** — depends on 1.1.
- `1.3` Tier metadata (`basic`/`standard`/`advanced`) per key — **parked** — depends on 1.1.

### 2. Reference file

- `2.1` Generator emitting `config/kaine.reference.toml` — **parked** — depends on 1.1.
- `2.2` Hand-written inline explanations for every key — **parked/blocked** — cannot be
  authored until the registry (1.1) enumerates keys; also depends on 2.1 skeleton.
- `2.3` CI sync check: reference keys/defaults match `list_all_defaults()` — **parked** —
  depends on 1.1 + 2.1.
- `2.4` CI check: every reference entry has a non-placeholder explanation (no `TODO`)
  — **parked** — depends on 2.2.

### 3. Validation command

- `3.1` `python -m kaine.setup.validate_config` — **parked** — module does not exist.
  (Distinct from the existing `validate_config_shape` in `kaine/config.py`.)
- `3.2` Tests for unknown/out-of-bounds/missing-required cases — **parked** — depends on 3.1.
- `3.3` `Config valid` row in `python -m kaine.preboot` — **parked** — depends on 3.1;
  no such row present.

### 4. Questionnaire mode

- `4.1` `python -m kaine.setup.configure` — **parked** — module/entry point does not exist.
- `4.2` `--full` flag (all tiers) vs default (`basic` only) — **parked** — depends on 4.1 + 1.3.
- `4.3` Test: only `basic`-tier keys presented without `--full` — **parked** — depends on 4.2.

### 5. Wizard sync

- `5.1` Test: every `basic`-tier key has a wizard question — **parked** — depends on 1.3
  plus a wizard question set keyed to the reference.
- `5.2` Update wizard to cover skipped `basic`-tier keys — **parked** — depends on 5.1.

### 6. Documentation

- `6.1` Docs page: config layers, reference file, validation command — **parked/blocked**
  — would document capabilities that do not exist yet; publish after 3.1.
- `6.2` Docs page: first-time setup walkthrough via questionnaire — **parked** — depends on 4.1.

## Dependency graph (activation order)

1. `1.1` (registry helper) — unblocks 1.2, 1.3.
2. `1.3` (tier metadata) — unblocks 4.2, 5.1.
3. `2.1`/`2.2` (reference file) — unblocks 2.3, 2.4, 3.x, 6.x.
4. `3.1` (validator) — unblocks 3.2, 3.3, 6.1.
5. `4.1` (configure) — unblocks 4.2, 4.3, 6.2.
6. `5.x` (wizard sync) — last, depends on 1.3 + reference.

## First activatable step on unpark

`next` — `1.1` Add `list_all_defaults()` to `kaine/config.py`. It is the single source of
truth prerequisite named by both the spec delta ("All defaults discoverable") and `design.md`
(D2: generator reads `list_all_defaults()`). When the operator unparks this change, start
here; everything else chains off it.

## Reasons nothing is green today

- Change status is explicitly `PARKED (roadmap item, not active work)` in `proposal.md`,
  `design.md`, and `tasks.md`.
- No underlying implementation artifact exists in the codebase (no module, no reference
  file, no entry point, no test, no preboot row, no doc page).
- The closest existing symbol (`validate_config_shape`) serves a different purpose (internal
  shape validation of merged config at load time) and must not be confused with the
  operator-facing validation CLI; reuse is not safe without spec review.
- Unparking requires operator decision (roadmap scheduling, not a code blocker).

## Notes

- Recorded from read-only analysis; no files under `openspec/changes/unified-instance-configuration/`
  were modified and no source changes were made.
- The `config/kaine.toml` working-tree modification reported in session git status is
  unrelated to this change and was not touched.
