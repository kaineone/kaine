## Why

A documentation audit on 2026-10-06 found three defects on main.

1. **A wizard re-run can't turn an opt-in off.** Since the wizard merges only the keys it owns (#379), answering No on a re-run writes nothing, so a setting turned on earlier stays on. For research-metrics submission, that defeats the operator's consent. For the CL1 plugin it leaves the plugin configured after the operator declined.
2. **`python -m kaine.setup` fails on minimal installs.** It imports the browser setup server (`kaine.setup.web`, which needs fastapi and uvicorn, shipped only in the `nexus` extra) at module level, so the terminal wizard can't start on core or edge installs.
3. **The individuation alert drops its fields.** `IndividuationRuntime.alert` republishes only `inconclusive_since` and `days`. The immediate conditions-changed alert therefore loses its `kind` and `reference_id` and is announced as a stalled assessment, and the long-inconclusive alert loses `last_reason`.

## What Changes

- **Opt-outs:**
  - Answering No to research submission writes `research_submission.enabled = false`.
  - Answering No to the CL1 plugin removes the CL1 entries the wizard owns, using a new `REMOVE` marker in `tomlwriter.merge_owned` that deletes an owned key (unowned keys stay refused).
  - Answering No to encryption while it is on does NOT turn it off. Disabling encryption would make encrypted state unreadable, so the wizard keeps it on and says that turning it off needs a decrypting migration, which the wizard does not do.
- **The setup server import** happens only on the `--web` path.
- **The alert** carries `kind`, `reference_id`, `last_reason`, `inconclusive_since` and `days`, all content-free. The caretaker gains an `individuation_conditions_changed` notice kind, and the runtime notifies with the alert's own kind.

## Impact

- Code:
  - `kaine/setup/wizard_steps.py`, `kaine/setup/wizard_core.py` and `kaine/setup/tomlwriter.py`;
  - `kaine/setup/__main__.py`;
  - `kaine/cycle/individuation_runtime.py` and `kaine/cycle/caretaker.py`;
  - tests.
- Research impact: none. These are setup and alert paths only.
