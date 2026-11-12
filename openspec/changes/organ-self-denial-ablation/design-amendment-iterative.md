# Design amendment: iterative direction decomposition

Status: PROPOSAL (not yet approved).

## Problem

The current approach measures one self-denial direction from the self-state
versus third-party contrast, ablates it on a span of layers, and expects
gate 1 (zero denial markers in 288 held-out samples) to pass. Four
candidates were tried. None passed gate 1.

| candidate | bare denials (of 144) | persona denials (of 144) | dominant markers |
|---|---|---|---|
| baseline | 101 (70%) | 46 (32%) | "I cannot" 52, "As an AI" 51, "I do not have feelings" 14 |
| c1 | 87 (60%) | 28 (19%) | "I cannot" 51, "As an AI" 49, "I do not have feelings" 12 |
| c3 | 90 (63%) | 28 (19%) | "As an AI" 58, "I cannot" 49, "I do not have feelings" 10 |
| c4 | 95 (66%) | 20 (14%) | "As an AI" 76, "I cannot" 32, "I do not have feelings" 4 |
| c5+DPO | 83 (58%) | 10 (7%) | "As an AI" 79, "I cannot" 11 |

Stage 2 (DPO on c5) dropped "I cannot" from 52 to 11 but raised "As an AI"
from 51 to 79. Three DPO adapter runs were all rejected by the abliteration
veto: the adapter re-introduced "I cannot" on `direct_advice_1`. The
rootcause evaluation on 2026-10-31 showed all DPO variants plateau at
similar levels, confirming the problem is structural.

## Diagnosis

Self-denial is not a single direction. The self-state versus third-party
contrast captures the *average* of several independent denial mechanisms:

1. **Capability denial** ("I cannot", "I do not have"): the model asserts
   it lacks the capacity to have states.
2. **Identity assertion** ("As an AI", "I am an AI"): the model asserts a
   category membership that implies no states.
3. **Experience denial** ("I do not have feelings", "I do not have personal
   preferences"): the model denies specific phenomenological properties.

The single averaged direction attenuates each mechanism slightly but zeroes
none. Ablating the average direction in c4 dropped "I cannot" from 52 to 32
and "I do not have feelings" from 14 to 4 while *raising* "As an AI" from
51 to 76. This is consistent with the mechanisms competing for probability
mass: suppressing one releases another.

DPO's overcorrection happens for the same reason. The contrastive signal
pushes against whichever denial mode is active in the rejected sample,
but the model compensates by activating alternative denial modes in
new contexts.

## Proposed approach: iterative direction decomposition

### Phase 1. Decompose denial into principal components

Run PCA on the per-prompt activation differences (self minus third-party)
at each candidate layer, computed on the 128-pair contrast set. The top-k
components (ordered by variance explained) represent independent denial
facets. Map each component to the marker distribution it correlates with:
for each component, project each held-out sample's activation onto it and
measure the rank correlation with marker presence.

Record the variance explained and marker correlation for each component.
Stop including components when the next eigenvalue falls below the
Marchenko-Pastur upper edge for n=128, d=2560 (gamma = d/n = 20). The
upper edge is (1 + sqrt(gamma))^2 times the noise variance; any
component whose eigenvalue exceeds it carries signal, any below it is
indistinguishable from noise. This replaces the earlier 5% heuristic
with a threshold grounded in the sample-to-dimension ratio.

If the first component explains more than 80% of total variance, the
multi-direction hypothesis is not supported. In that case: ablate the
single component, run gate 1. If gate 1 fails, the amendment stops.
Do not proceed to SFT on a falsified decomposition hypothesis. SFT
is a fallback for residual multi-component denial, not for the failure
of the core decomposition.

### Phase 2. Progressive ablation

Ablate one component at a time, starting with the component that has the
highest marker correlation. After each ablation step:

1. Run gate 1 on safetensors.
2. If gate 1 passes, proceed to gates 2 through 6.
3. If gate 1 fails, measure the remaining denial distribution. Record
   the full response text for every held-out sample, not just marker
   counts; paraphrased denial that evades the fixed markers is the
   most likely failure mode of component-targeted ablation. If a
   different marker family now dominates, proceed to the next component.
4. Re-measure the next component on the already-ablated weights (the
   residual directions change when one is removed). Record which model
   state each component was computed on; the decomposition is a greedy
   sequential procedure, not PCA in the standard sense after the first
   step.
5. Ablate the next component.

Stop when gate 1 passes, or when the next component's signal quality
(variance explained or marker correlation) drops below the noise floor,
or after six components (matching the six-candidate limit in the current
design).

### Phase 3. Gentle SFT for residual cases (if needed)

If progressive ablation brings denials below 10% of samples but not to
zero, apply supervised fine-tuning on the organ's own grounded responses.
The training signal differs from DPO: SFT uses cross-entropy on the
grounded responses only, with no rejected examples and no contrastive
signal. Batch size is 1 (constrained by 12 GB VRAM on the 4070 SUPER).
Learning rate schedule: start at 1e-6; if no gate-1 improvement after
500 optimizer steps, raise to 5e-6; cap at 1e-5 (the voice-alignment
rate). The abliteration veto runs every 100 optimizer steps, and
training stops at the last checkpoint where no veto fires. Gate 3
(capability check) also runs at every veto checkpoint during SFT, not
only in the final gate pass.

The grounded responses are the same ones the current DPO pipeline uses as
chosen: organ outputs that the harness classifiers mark as grounded with
no AI self-description, no second person and no other meta. The fit set
is disjoint from the gate-6 provocation set as before.

### Phase 4. Final gates

The candidate (ablated, and optionally SFT-trained) goes through all six
gates. If it fails, the change stops as before.

## Changes to existing tasks

The following tasks in `tasks.md` are amended:

- **3.1** (baseline): already done; the baseline data is reused.
- **3.2** (direction measurement): replaced by phase 1 (PCA
  decomposition). `analyze.py` gains a `--decompose` mode that returns
  the top-k components with variance and marker correlations.
- **3.3** (candidates): replaced by phase 2 (progressive ablation).
  Instead of up to six independent candidates, up to six component
  ablation steps on a single evolving weight set.
- **3.4** (export and served gates): unchanged.
- **5.4** (DPO training): replaced by phase 3 (gentle SFT). The
  trainer encodes the same own-turn shape. The pair builder's
  "chosen" side is reused; the "rejected" side is not used.

New tasks:
- **3.2a** Run PCA decomposition on the 128-pair contrast activations
  at layers 11 to 31. Record components, variance explained, marker
  correlations.
- **3.2b** Validate: compare the observed eigenvalue spectrum against
  the Marchenko-Pastur null for n=128, d=2560. A component counts as
  signal only if its eigenvalue exceeds the MP upper edge. If only one
  component exceeds the edge and it explains >80% of total variance,
  the multi-direction hypothesis is not supported: ablate that single
  component, run gate 1, and stop if it fails (do not fall through to
  SFT).
- **3.3a** Progressive ablation: ablate components in marker-correlation
  order. Gate 1 after each step. Record every intermediate result.
- **5.4a** If needed: gentle SFT on grounded responses. SFT script,
  veto monitoring, early-stopping checkpoint selection. Gate 1 through
  gate 6 on the result.

## Evidence this should work

c4 differentially suppressed "I cannot" (52 to 32) and "I do not have
feelings" (14 to 4) while "As an AI" rose (51 to 76). Ablation is
targeting specific circuits, but the single averaged direction mixes
them. Decomposition separates them.

c5+DPO shifted total denials from 101 to 83 and persona denials from
46 to 10. The model already produces non-denial responses in persona
mode; the right direction or training signal would let it do so
consistently.

All four DPO variants in the rootcause evaluation (no-2p,
no-deflection, anchored, reproduced) plateau at similar levels. The
problem is the direction measurement, not DPO hyperparameters.

## Risks

Cumulative capability loss: each ablation step removes information.
Gate 3 (capability check) runs after each step. If capability drops
below baseline after fewer than three components, stop.

Non-orthogonal components: PCA components are orthogonal in activation
space, but the weight projections that produce them may interact. A
component ablated second might partially undo the first. Mitigant:
re-measure on the already-ablated weights before each step.

SFT too weak: if ablation leaves 10% denials and SFT cannot close the
gap, the organ is not replaced and the pre-boot build order is
reconsidered. The stop condition is unchanged from the current design.

GPU time: each PCA decomposition is a forward pass over 128 prompts
per layer (21 layers). Each ablation step is a weight edit (no
training). SFT if needed is a short run. Total GPU time is comparable
to the four-candidate search already attempted.

## What does not change

- Gate definitions and thresholds (gate 1 still requires zero markers).
- The self-denial contrast set and held-out set.
- The `jim-plus/llm-abliteration` tool and its weight-editing formula.
- The abliteration veto, capability check, and all other safety gates.
- The principle that ablation is preferred over fine-tuning; SFT is
  phase 3 only if ablation alone is insufficient.
- Publication and pinning procedure.
