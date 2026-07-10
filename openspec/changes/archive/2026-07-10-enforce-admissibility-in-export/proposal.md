> ARCHIVED 2026-07-10: implemented — both admissibility checks enforced in the research export path (11/11 tasks).

# Enforce both admissibility checks in the research export path

## Why

The paper (§6.3) claims: "After a run, admissibility is decided by two offline
checks ... a completeness gate ... and a log-range sweep ... An inadmissible run
cannot reach analysis looking clean." The code does not enforce this by default:

- The **range sweep** (`kaine/experiment/log_schema.sweep_run`, "every logged number
  within its declared range") is only a standalone CLI + unit tests.
  `build_research_bundle` (`kaine/research/submission.py`) never calls it. The range
  half of admissibility is never applied automatically.
- The **completeness gate** (`scan_run`) runs in the bundle builder only when an
  `admissibility_run_id` is passed, and it **blocks only if `require_admissible=True`,
  which defaults to `False`** (`kaine/research/submission.py:200, 320-334`). By
  default an inadmissible run is annotated in the manifest but still exported.
- The per-sink `seq`-contiguity gate assumes a single uninterrupted process: a
  mid-run restart re-zeros `seq` and mints a new `run_id`, so records dropped around
  a crash/resume can go undetected (`jsonl_sink.py:70,106-123`,
  `admissibility.py:89-93`).

So the paper's central data-integrity guarantee does not hold out of the box.

## What Changes

**Plan-only. Ships no behavior code.** Design-of-record and task roadmap.

1. **Run the range sweep in the export path.** `build_research_bundle` SHALL invoke
   `sweep_run` in addition to `scan_run`, and record both verdicts in the manifest.
2. **Default `require_admissible = True`.** An inadmissible run (failing completeness
   OR range) SHALL be blocked from the default export path, not merely annotated. An
   operator override to export-anyway MAY exist but SHALL be explicit and recorded in
   the manifest as an override.
3. **Handle multi-process / restart runs.** Detect and surface a `seq` reset or a
   `run_id` change within what an operator treats as one logical run, so a
   crash/resume cannot silently pass the contiguity gate. At minimum, the
   admissibility report SHALL flag "run not single-process / restart detected"
   rather than reporting clean.
4. Align the paper wording if any residual gap remains after 1–3, but the intent is
   to make the code meet the paper, not soften the claim.

## Impact

- Affected specs: `run-admissibility`, `research-submission`, `log-validation`.
- Affected code (later pass): `kaine/research/submission.py`,
  `kaine/experiment/admissibility.py`, `kaine/experiment/log_schema.py`,
  `kaine/evaluation/.../jsonl_sink.py`, `config/kaine.toml` (default flip).
- Research impact: an out-of-range or incomplete run can no longer reach analysis
  through the default path, closing the largest data-integrity gap.
- Behavior change: operators who relied on the permissive default will now be
  blocked on inadmissible runs; the explicit override preserves an escape hatch.
