## Why

The companion architecture paper reframes the research program around a single
falsifiable claim. Its draft (`paper-preprint-minimal_01.md`) states that claim as a
*top-down correction loop* — "modules treat the broadcast as top-down prediction and
correct their next-tick error against it" (§3.2/§6.3) — and its primary experiment (a
"recurrence ablation") toggles that correction on and off.

That mechanism is not in the reference implementation, and deliberately so. There is
no central executive and no top-down controller: `BaseModule.on_workspace` is a no-op
by default, Soma never reads the broadcast, and Chronos reads it only as a bottom-up
observation it predicts. The architecture's founding principle is decentralized
competition — every module minimizes its own error, and the system is the competition
among them through a shared workspace (design §3.1, "no central executive"). Building
the top-down loop to match the paper would bend the architecture to the paper.

The correct experiment tests the loop the architecture actually has — and the paper
already names its null (§2.5, §6.3): *whether conditioning mediated by the competitive
workspace does work that a scored fan-in prompt-assembler would not.* The null is
right; only the treatment arm was mis-described. This change delivers that experiment
— a **workspace-mediation ablation** (competitive workspace on vs. flat fan-in of the
same modules) — plus a config-only minimal 3-module build to run it. It requires **no
new top-down mechanism** and changes **no module internals**; the workspace is used
as built, and the ablation's "off" arm is a measurement condition, not an
architectural change.

## What Changes

- **Workspace-mediation ablation (new experiment).** A two-arm runner, matched seed /
  stimulus / modules:
  - *Workspace-on* — modules publish precision-weighted errors → Syneidesis
    competitively selects a coalition above threshold (with inhibition) → broadcasts →
    Lingua is conditioned on the selected coalition.
  - *Workspace-off (prompt-assembler null)* — same modules, same errors, but no
    scoring / threshold / top-k / inhibition / broadcast; Lingua is conditioned on a
    **flat rendering of all current module outputs** through the same
    `ContextAssembler`, with the rendering budget matched so the contrast is
    selection-structure, not information-quantity.
- **Three measures, honestly scoped.** Language-organ output divergence (greedy
  decoding), coalition-selection structure (on-arm), per-module error trajectories.
  WIN/NULL/NEGATIVE with a reachable adverse outcome and a neutral stimulus battery.
- **Minimal run configuration (new).** An opt-in experiment overlay enabling only
  `soma, chronos, lingua` (Syneidesis + Volition remain always-on scaffolding), with
  `volition.drive_initiative = false` and Lingua greedy decoding. All other modules
  stay built and disabled.
- **Operator text-stimulus injection (new).** A headless path to inject one seeded
  user utterance in the Audition-absent minimal build, output read from
  `lingua.external`.
- **Honest reproducibility scoping + multiple-comparisons.** Seed-reproducibility
  claimed only for the offline/deterministic runner; family-wise correction applied
  when reported alongside the other suite experiments.

No **BREAKING** changes: no module behavior changes; the ablation is an eval-layer
harness; the minimal configuration is opt-in; the shipped config stays all-off.

## Capabilities

### New Capabilities
- `workspace-mediation-ablation`: The primary experiment — the workspace-on vs.
  flat-fan-in two-arm runner, the fair-null rendering-budget discipline, the three
  measures, the neutral battery + controls, WIN/NULL/NEGATIVE classification with
  reachable adverse outcomes, and the reproducibility/multiple-comparisons scoping.
- `minimal-run-configuration`: The gated 3-module experiment configuration and the
  headless operator text-stimulus injection path for the Audition-absent build.

### Modified Capabilities
<!-- None. Module internals (Soma, Chronos, Syneidesis, Volition, Lingua) are used
     as built; the ablation lives entirely in the evaluation layer and config. -->

## Impact

- **Code:** new `kaine/evaluation/benchmarks/workspace_mediation_ablation/`; a flat-
  fan-in conditioning path reusing `ContextAssembler.assemble` (`lingua/context.py:104`)
  and the existing conditioned-client seams in `evaluation/ab_divergence.py`; a new
  minimal experiment config overlay; a headless stimulus injector. Reuses
  `experiment/verdict.py`, `experiment/stability.py`, `experiment/seeding.py`,
  `experiment/multiple_comparisons.py`, `evaluation/observers/*`, `text_embedding.py`,
  and the `oscillatory_ablation` runner pattern unchanged.
- **Config:** a minimal experiment overlay (enables soma/chronos/lingua,
  `drive_initiative=false`, greedy Lingua). Shipped `config/kaine.toml` stays all-off
  (guard test unaffected).
- **No module internals change:** Soma, Chronos, Syneidesis, Volition, and Lingua are
  used as built. No top-down correction mechanism is introduced.
- **No removals:** all 16 modules remain built; the minimal build is configuration.
- **Docs/paper:** reconciles §1.2/§3.2/§6.3 and the abstract to the competitive-
  mediation framing (review-gated, not committed by this change).
