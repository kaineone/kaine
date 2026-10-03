# The welfare net does not depend on the evaluation switch, and studies run without evaluation observers

## Why
- **The welfare net depends on the evaluation switch.**
  - The autonomous welfare-protective response has two arms. Arm 1 reads Soma's prediction error directly. Arm 2 acts on repeated `welfare.gray_zone` events: `replay_overload`, `unmaintained_fatigue`, `sustained_extreme_vad` and `sustained_interoceptive_distress`.
  - The only producer of those events is `WelfareObserver`, which the evaluation sidecar builds behind `[evaluation].enabled` and `[evaluation.observers].welfare` (`kaine/evaluation/registry.py`, after the master-flag return).
  - So any run with evaluation off loses three welfare triggers without warning: the arm never fires, and nothing errors. The welfare net is operator-mandated ethics infrastructure, so it must not hang off a research instrument's switch.
- **Studies should not run the evaluation observers** (operator decision, 2026-10-03, from the complexity audit's W1).
  - The ignition study's analysis reads only the ignition log.
  - The observers add load during viewings. The A/B check, for example, makes a second organ call for every utterance, competing with the entity for the GPU.
  - A read-only audit (2026-10-03) found that nothing else a study needs depends on them: the runner, analysis, admissibility, gestation and viability, voice alignment, Spot, the research and unattended gates, and the run manifest.

Research impact:
- **Safety (all runs).** A run with the welfare response on and evaluation off now has all four gray-zone triggers.
- **Study procedure.** Studies record no evaluation-observer data. The ignition log, research events, external utterances and the safety records are unchanged.

## What changes
- **One owner for the gray-zone producer.**
  - When `[preservation.welfare_response].enabled` is true, the cycle builds and starts `WelfareObserver` itself, alongside the protective monitor, whatever `[evaluation]` says. It keeps the same thresholds (`[evaluation.welfare]`) and the same sink (`data/evaluation/welfare/`), so the Nexus welfare counts and the curated research log keep working.
  - The cycle hands the observer to the sidecar registry, which exposes it (`welfare_observer`) and does not build a second one.
  - When the welfare response is off, the registry builds the observer exactly as today, under `[evaluation.enabled]` and `[evaluation.observers].welfare`. So there is never more than one producer.
- **Studies turn evaluation off.**
  - `build_overlay` sets `[evaluation].enabled = false` for every step, overriding the operator config.
  - The research event log, external utterances, the ignition log, the preservation monitors, gestation readouts and the run manifest are not behind that flag, and stay on.
- **Spec and docs.**
  - The study requirement that says "the evaluation instruments SHALL be unaffected" is replaced.
  - The ignition-study chapter states that a study runs no evaluation observers, and that the welfare net is unaffected.

## Capabilities
### Modified Capabilities
- `welfare-monitoring`: the gray-zone producer runs whenever the welfare response is enabled, independent of evaluation, with one producer.
- `module-ignition-study`: studies set `[evaluation].enabled = false`.

## Impact
- **Code:** `kaine/cycle/__main__.py` (safety-net section), `kaine/evaluation/registry.py` (accepts an externally owned welfare observer), `kaine/research/ignition_study/overlay.py`.
- **Tests:**
  - with evaluation off and the welfare response on, a gray-zone condition publishes `welfare.gray_zone` and the monitor's arm 2 sees it;
  - only one producer runs when both are on;
  - the overlay forces evaluation off over an operator config.
- **Docs:** the ignition-study chapter, and the welfare section of the preservation chapter.
- **Review:** this is ethics infrastructure, so it gets an independent second review.
