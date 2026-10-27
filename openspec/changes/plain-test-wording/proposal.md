## Why

In current AI usage, "harness" means the software wrapped around a language
model to make an agent. KAINE never uses the word that way. It used it in the
older software-testing sense, scaffolding that runs something under test and
records results, and readers who know the newer sense misread it.

## What Changes

- Prose in `docs/`, the living specs under `openspec/specs/`, the issue
  template, and the comments, docstrings, log messages and help strings in
  `kaine/`, `tools/` and `tests/` replaces "harness" with the plainer word for
  the thing: offline development run (the workspace-mediation test's offline
  run), red-team runner, stability check, organ replay tool, benchmark runner,
  test setup, test script, and "the setup of section 6.3" where the paper's
  term applies.
- Identifiers and file names are unchanged (`RedTeamHarness`,
  `SubsystemHarness`, `harness.py`, `_harness.py`, `test_stability_harness.py`,
  the `tests/js/*_harness.js` files). Renaming modules would churn imports.
- The requirement title "Capability-eval harness is pluggable" in
  `voice-alignment-training` is kept, because the active change
  `deterministic-grader-fixes` modifies it by that name.
- Archived and other active changes, `external/` and `kaine/legacy_names.py`
  are left as they are.

## Capabilities

### Modified Capabilities

None. Wording only. Requirement titles that contained the word were renamed in
the living specs; their requirements and scenarios are unchanged.

### New Capabilities

None.

## Impact

The files above. No behaviour change. Two user-visible strings change: the
development-run disclaimer prefix in verdict details and the `workspace_mediation`
CLI help text.
