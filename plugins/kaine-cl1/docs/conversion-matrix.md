# Module → wetware conversion matrix

The question the project answers: **how many of KAINE's modules can run their
forward model on living neurons instead of silicon?** The answer follows from what
a culture is good at: the low-dimensional, dynamics-heavy modules. A predictive
processor whose job is to *predict the temporal structure of a signal* is what a
recurrent biological culture does well. A processor whose job is to store a
key-value memory, encode HD video, or emit grammatical language is not, and those
stay on silicon.

Scoring axes:
- **Dimensionality**: can the input/output fit through 64 electrodes? (lower = better)
- **Dynamics-nativeness**: is the computation fundamentally about temporal
  prediction / recurrence? (higher = better)
- **Decodability**: can we read a useful signal back out of spikes with the
  `cl.analysis` suite? (higher = better)

## Strong tier: convert first (the plan implements these)

| Module | Role | Why it fits | Coding scheme |
|---|---|---|---|
| **Chronos** | interval timing, anomaly/rumination | timing & sequence anticipation are intrinsic to recurrent tissue; upstream model is tiny & CPU-pinned | temporal-code the recent workspace summary → stim; decode next-interval prediction + LZ/criticality surprise |
| **Soma** | interoception, homeostasis, fatigue | low-dim scalar streams (substrate metrics) → a biological forward model of "how the body feels"; poetic *and* apt | rate-code metrics → stim; decode firing-rate deviation as interoceptive prediction error |
| **Oscillator layer** | LIF oscillators for phase/coherence binding | biological neurons **are** oscillators; the culture's intrinsic bursting *is* the oscillation | drive with periodic stim; decode phase via DCT/burst timing → PLV coherence |
| **Nous** | active inference over a compact discrete generative model | active inference **is** the free-energy principle, which is the DishBrain paradigm; conceptually the purest fit | population-code beliefs → stim; closed-loop stim as evidence; decode policy via territory firing balance |

## Hybrid tier: silicon + wetware together (planned, default-off)

Only the named sub-signal moves to wetware; the silicon half stays. For several of
these the split is likely **permanent by design**, since the silicon half is not a
wetware task, so "hybrid" is a stable end state, not a failed full conversion.

| Module | Wetware half | Silicon half (stays) | Note |
|---|---|---|---|
| **Audition (front end only)** | "any sound → prediction-error salience" acoustic front end | STT, vocal-emotion (model-bound) | likely permanent hybrid |
| **Phantasia (surprise signal only)** | scalar **surprise** from culture criticality/LZ | the RSSM world-model rollout (high-dim) | likely permanent hybrid |
| **Volition / action-selection** | closed-loop action selection, the DishBrain "Pong" paradigm | intent plumbing + safety gate | could become a full conversion if decode proves reliable |
| **Thymos** | dimensional valence/arousal from population dynamics (arousal ≈ global excitability) | affect state machinery | speculative; welfare-sensitive; review-gated |

## Silicon-only: do not convert (and why)

| Module(s) | Reason |
|---|---|
| **Lingua**, **Vox** | large language / TTS models; symbolic, high-dim; no meaningful electrode encoding |
| **Topos** | HD video encoder (InternVideo); 64 electrodes cannot carry a visual latent. (A *toy* down-sampled visual task à la DishBrain-Pong could be a future demo, but it is not "running Topos".) |
| **Mnemos**, **Empatheia** | vector stores / per-agent ToM; need reliable addressable key-value memory the substrate cannot provide |
| **Eidolon**, **Praxis**, **Hypnos**, **Perception**, **Mundus** | orchestration / self-model / effector-IO / control planes, not forward models at all |

## The ceiling

64 electrodes, one culture. With the strong-tier territory budget
(Chronos 12 + Soma 12 + Oscillator 8 = 32), roughly **half the array remains**
for one or two hybrid-tier modules at a time. You cannot run all eight
converted modules on a single culture simultaneously; the broker enforces this.

## Success criteria (per the plan)

A conversion is "successful" when, on the simulator:
1. the module's `<name>.out` events keep their **exact upstream shape**;
2. the module participates in the cognitive cycle at the required cadence without
   starving it; and
3. the workspace-mediation ablation (KAINE's own falsifiable test) still runs:
   i.e. the biological forward model does *measurable predictive work*, not noise.
Point 3 is the load-bearing criterion: a converted module that publishes pure
noise fails KAINE's existing ablation, which is the intended detector.
