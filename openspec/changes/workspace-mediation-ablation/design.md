## Context

The companion paper's primary experiment tests the wrong mechanism for this system.
Its draft states the thesis as a top-down correction loop (§3.2/§6.3), but the
reference implementation has no top-down controller and no corrective loop, on
purpose (design §3.1, "no central executive"):

- `BaseModule.on_workspace` is a default no-op (`base.py:162`).
- Chronos reads the broadcast only as a bottom-up observation it predicts
  (`chronos/module.py:142-197`); Soma never reads it (`soma/module.py`).
- The recurrence that exists is a shared blackboard: each broadcast becomes next-tick
  context, shapes what Lingua says, and Lingua's speech re-enters the bus as events
  that compete for the next broadcast.

The architecture's real claim is decentralized competition: independent modules,
coupled only through the competitive workspace, produce coherent global behavior that
flat fan-in does not. The paper already names this null (§2.5, §6.3, "fan-in prompt-
assembler"); only its treatment arm was mis-described. The experiment scaffolding is
mature and reusable: the `oscillatory_ablation` two-arm runner, `experiment/verdict.py`,
`experiment/stability.py`, `experiment/seeding.py`, `experiment/multiple_comparisons.py`,
the read-only sidecar observers, `text_embedding.py` cosine, and the conditioned-client
seams in `evaluation/ab_divergence.py`. Module gating already exists (`build_registry`
+ `[modules]`, ships all-off, guard-tested).

## Goals / Non-Goals

**Goals:**
- Ship a workspace-mediation ablation (competitive workspace on vs. flat fan-in) that
  tests the architecture as built, with no new module mechanism.
- Keep the null non-degenerate and fair (same information, matched rendering budget).
- Provide a config-only minimal 3-module build and a headless stimulus injector.
- Keep every built module intact; reactivation is a flag flip.

**Non-Goals:**
- No top-down correction mechanism, no `on_workspace` rewrite, no change to Soma /
  Chronos / Syneidesis / Volition / Lingua internals.
- Not the oscillatory ablation (separate, already built).
- Not activating any held module (gated on a positive result).
- No bit-level reproducibility claim for the live temperature-driven organ.
- No consciousness/coherence-superiority claim from divergence alone.

## Decisions

**D1 — The ablation lives entirely in the conditioning path, not in the modules.**
Both arms run the same modules and the same Syneidesis. The only difference is which
snapshot the `ContextAssembler` (`lingua/context.py:104`) renders for the organ:
workspace-on hands it the competitively-selected `WorkspaceSnapshot`; workspace-off
hands it a flat snapshot of all current module events (no scoring/top-k/inhibition).
Rationale: this tests the architecture as built and touches no module internals — the
opposite of bending the system to the paper. Alternative rejected: building a top-down
correction step and toggling it (the paper's framing) — contradicts §3.1 and gutts the
project's founding decentralization.

**D2 — Fair-null via matched rendering budget.** The off arm renders all module events
through the same assembler with the same max-events / char-budget bounds as the on arm,
so the contrast is *selection structure*, not *information quantity*. Rationale: without
this, divergence could come from "fewer vs. more events in the prompt," not from
workspace mediation — a straw null. This is the one real design subtlety and is pinned
by a test.

**D3 — Reuse the oscillatory-ablation runner shape and the A/B conditioned-client
seams.** New `evaluation/benchmarks/workspace_mediation_ablation/` with
`_run_arm(mediated=…)` over `ScriptedBus`, `deterministic=True`, `set_global_seed` per
arm, `_classify → Verdict`. The flat-fan-in conditioning reuses the assembler-
conditioned and bare client seams already in `evaluation/ab_divergence.py`. Rationale:
proven template, minimal new surface.

**D4 — Greedy organ decoding for the observable.** The output-divergence measure runs
the organ at temperature 0 so identical inputs yield identical output and any
divergence is the workspace's. Offline this is the deterministic/echo client; the live
minimal config pins greedy decoding. Rationale: removes the sampling-noise confound.

**D5 — Primary/secondary measure hierarchy with concrete statistics.** Following the
paper (§6.3), the trajectory measures are PRIMARY and output divergence is SECONDARY.
Primary measure 1: the Pearson correlation between Soma's and Chronos's precision-
weighted error series over a sliding window; the directional criterion is a significant
INCREASE under workspace-on vs. workspace-off (mutual influence via the shared
broadcast). Primary measure 2: the Shannon entropy of the on-arm coalition-source
distribution over a window (must sit between uniform and degenerate), plus whether
structured selection changes downstream behavior vs. fan-in. Secondary: greedy-decoded
Lingua output cosine divergence, reported only as confirmation that primary effects
propagate. Rationale: output divergence is confounded (any input change diverges), so
it cannot be the thesis evidence; the coupling and selection statistics are. This
requires two analyses not yet in the harness — cross-module error CORRELATION (the
`PredictionErrorObserver` today records per-module stats, not pairwise correlation) and
coalition-source ENTROPY.

**D6 — Force competition in the minimal set via `top_k` (construct validity).**
Competitive selection only excludes when candidates exceed capacity. Syneidesis ships
`top_k = 5` (`syneidesis.py:31`), but the minimal set has ~2–3 candidate sources per
tick (Soma, Chronos, injected utterance), so at the default nothing is ever excluded
and the ablation would test broadcast-mediation + gating, NOT competition — while the
paper's whole framing is *competitive* mediation. The minimal overlay therefore lowers
`top_k` (e.g. 1–2) so selection genuinely competes; the runner records the candidate-
vs-capacity regime each run and scopes a WIN's claim accordingly (a run where capacity
was never exceeded is reported as broadcast-mediation evidence, not competition
evidence). Alternative: drive a battery with more concurrent candidates than capacity —
usable in addition, but `top_k` is the reliable lever on the minimal set.

**D7 — Directional verdict.** WIN = significant increase in cross-module error coupling
(primary 1) with non-trivial, state-dependent selection (primary 2), confirmed by
output divergence (secondary). NULL = coupling and selection structure at/below
`min_effect` — the prompt-assembler outcome. NEGATIVE = meaningful but adverse (the
on-arm destabilizes, or the flat arm is more coherent by the pre-registered criterion).
All three reachable via a neutral battery plus controls.

**D8 — Measure-power coverage (Soma salience).** Primary measure 1 can only detect
coupling when Soma periodically enters the coalition (so its influence reaches Chronos
through the broadcast). The battery must include substrate perturbations that make Soma
salient on a reported fraction of ticks; a run where Soma never enters the coalition is
flagged UNDERPOWERED for measure 1, not reported as a clean NULL (a false NULL from a
flat substrate must not be mistaken for an inert workspace).

**D6 — Minimal build is a labeled experiment overlay, not a deployment tier.** It DOES
enable soma/chronos/lingua (distinct from `config/profiles/tier*.toml`, whose contract
forbids enabling modules), sets `volition.drive_initiative=false`, and pins greedy
Lingua. The cycle boot gate still guards entity birth.

**D7 — Stimulus injection reuses the audition-shaped event contract.** Volition matches
a user utterance by `source="audition", type="audition.transcription"`, not by stream
name. The headless injector publishes such an event onto an active `.out` stream in the
3-module build (mirroring `tests/test_cycle_volition.py`); output is read from
`lingua.external`.

## Risks / Trade-offs

- **Straw null (fewer-vs-more information)** → D2 matched rendering budget; a test
  asserts both arms receive the same events under the same bounds.
- **Divergence ≠ superiority** → the runner and report state a WIN means "mediation does
  work," not "mediation is better"; a coherence measure is future work.
- **LLM sampling confound** → D4 greedy decoding; offline arms use deterministic client,
  so Measures 2 & 3 never touch the organ.
- **Single stimulus / single seed is not a verdict** → the runner requires the battery +
  `run_multi_seed` + family-wise correction for a reportable verdict; a single seeded
  stimulus is a smoke run answering only the crux disproof.
- **No real competition on the minimal set (construct validity)** → D6 lowers `top_k`
  so selection excludes; the runner records the candidate-vs-capacity regime and scopes
  the claim; a non-competing run is disclosed as broadcast-mediation evidence only.
- **False NULL from a flat substrate** → D8 requires Soma-salience coverage in the
  battery; a run where Soma never enters the coalition is flagged underpowered, not NULL.
- **Off-arm Chronos predicts a different target** → in the off arm there is no broadcast,
  so Chronos predicts its raw input stream rather than the broadcast; its error is a
  structurally different quantity than in the on arm. The primary measure is cross-module
  CORRELATION (co-movement), not absolute error, which sidesteps the apples-to-oranges
  problem — but the runner (and the paper §6.3) must state explicitly what Chronos
  predicts in each arm so the comparison's validity is legible.
- **Paper vs code drift** → §1.2/§3.2/§6.3 + abstract reconciled to the competitive-
  mediation framing (review-gated, not committed by this change).

## Migration Plan

1. Add the workspace-mediation ablation runner + flat-fan-in conditioning path
   (eval-layer only) — no module or config default changes.
2. Add batteries, classify, CLI, multi-seed adapter; wire into the suite with family-
   wise correction.
3. Add the minimal experiment overlay + headless stimulus injector.
4. Reconcile the paper wording (separate, review-gated, uncommitted by this change).

Rollback: remove the eval-layer harness and the overlay; the system is byte-identical
to pre-change (no module or shipped-config default was touched).

## Open Questions

- Exact construction of the flat snapshot (all events vs. all `<module>.report` latest;
  ordering) — pinned against the matched-budget test.
- The exact `top_k` value for the minimal overlay (1 vs. 2) and the sliding-window /
  significance parameters for the Pearson-correlation and entropy criteria — pre-
  registered before analysis per §6.3.
- Directional NEGATIVE criterion + coherence measure — pre-registered before analysis
  per §6.3; coherence measure may be deferred to the empirical paper.
- Whether the live minimal run injects stimulus via a headless CLI, a Nexus text box,
  or both.
