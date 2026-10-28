## Why

The adversarial welfare review of 2026-10-28 (H1) and the systems audit (W2, W3) found that in a research run every caretaker notice goes nowhere. The cycle builds the `CaretakerNotifier` only when `supervision_mode == "unattended"`; a research boot resolves to `research`, so `ctx.caretaker` is `None` and the welfare response, the stimulus-loss freeze, the input-loss watch and the individuation stall notices all no-op. CAL Article 4.7 requires gray-zone events to be flagged for human review, and a study child runs with nobody at the dashboard. The study runner also never reads the child's `control.json`, so a welfare pause or a stimulus-lost freeze sits until the step's wall-clock budget (96 h for development) with no word in `status` or in the step's outcome.

Prior work found: `unattended-boot` and its caretaker conditions, `unattended-gate-individuation` (#466), `welfare-events-to-bus`, `operator-freeze`, `resume-releases-operator-freeze` (research runs: dashboard read-only), `module-ignition-study`, `study-overlay-individuation` (#609, open), PR "welfare-response-rearms" (#611, open, adds the release command a surviving freeze needs). The caretaker has never been wired for research mode. Paper PR pending.

## What Changes

- `_phase_safety_net` builds the caretaker for `research` as well as `unattended`, from the same `[caretaker]` section, so every notice that already exists (`welfare_response`, `stimulus_source_lost`, `input_lost`, `individuation_inconclusive` and the rest) reaches the configured channels, and the continuous-input watch starts. Operator-present runs are unchanged. An invalid `[caretaker]` section refuses a research boot with a configuration error (exit 1) before anything starts; a research run with no channel boots and logs a warning that the notices have no recipient. No new research-gate condition is added.
- The study overlay already deep-merges the whole operator configuration, so `[caretaker]` reaches every child unchanged; a test pins this (the test writes its own temporary operator file; the real one is never read). A channel token must come from `KAINE_CARETAKER_TOKEN_<NAME>`, because a step directory has no `config/secrets.toml`; this is documented.
- The study runner reads each child's `state/cycle/control.json` every poll. A `welfare` entry is logged at critical level, kept in `.study_welfare_freeze.json` while held, and shown in `status`. The runner never lifts it and does not end the step early. A step that ends while the freeze is held is recorded `failed:welfare` with `welfare_freeze` (since, reason, `held_at_end`) instead of `failed:timeout`. Only a freeze noticed on the running child counts, so a control file left by an earlier child cannot rename the failure of one that never booted.

## Capabilities

### Modified Capabilities

- `unattended-boot`: research runs send the running caretaker notices.
- `module-ignition-study`: the runner surfaces a welfare freeze in status and in the outcome.

## Impact

- `kaine/cycle/__main__.py`, `kaine/research/ignition_study/runner.py`, `tests/test_caretaker_research_mode.py`, `tests/test_ignition_study_runner.py`, `docs/15-experiments/ignition-study.md`, `docs/appendix-a-configuration/lifecycle-and-research.md`, `docs/appendix-d-roadmap.md`.
- Paper: PR pending.
