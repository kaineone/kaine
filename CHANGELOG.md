# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows Ubuntu-style `YY.MM.patch` with PEP 440 pre-release suffixes.
The public brand is **26.06.0a1**; pip normalizes this to `26.6.0a1` (expected).

---

## [26.06.0a1] — 2026-06-07

**First public alpha.** The architecture is feature-complete and tested in-tree.
The release is gated on Cognitive Architecture License (CAL) legal review before
any public distribution; the alpha number increments until the license is approved
and the release is ready. Pip-normalized form: `26.6.0a1`.

**Status:** pre-release alpha; not yet public; all modules ship disabled; first
boot is operator-supervised.

### Architecture

- **14 cognitive modules** communicating over a Redis-Streams event bus through
  the **Syneidesis** global workspace, cycling at ~3.3 Hz on local hardware with
  no cloud APIs in the loop, plus the **Perception** and **Mundus** embodiment
  modules (ship inactive).
- **Predictive forward models** across the perceptual and substrate organs (Soma,
  Chronos, Topos, Audition): each module predicts its next observation; prediction
  error drives workspace salience.
- **Active-inference Nous** rebuilt on pymdp 1.0 (JAX backend): belief updating
  and policy selection by expected-free-energy minimisation over a compact discrete
  generative model (four factors, four policies, one-step planning horizon).
- **Phantasia world model**: DreamerV3 RSSM core (JAX, CPU-only) for sleep-time
  associative scenario generation. World model only — no actor/critic; action
  selection stays with Nous.
- **Empatheia** social-cognition module: agent model per interlocutor (reliability,
  familiarity, interaction history) stored in Qdrant; theory-of-mind signals
  integrated into the workspace.
- **Hypnos five-phase maintenance cycle**: fatigue-triggered (Soma accumulator),
  deferred during active conversation, covering synaptic homeostasis downscaling,
  memory consolidation replay, associative cross-period replay via Phantasia,
  voice-alignment QLoRA training (operator-gated), and Nous active-inference
  integration. The **abliteration welfare veto** hard-rejects any adapter that
  re-introduces refusal conditioning — it is a blocking safety gate, not a
  preference.
- **Oscillatory binding layer**: per-module snnTorch LIF populations; Syneidesis
  computes phase-locking value (PLV) across coalition members and applies a
  bounded coherence multiplier to aggregate salience. Ships disabled; empirically
  uncharacterized — enable only after measuring the sidecar coherence observer
  data.
- **AES-256-GCM state encryption at rest**: covers Eidolon self-model,
  fork/merge snapshot bundles, sidecar observer JSONL, and Phantasia checkpoints.
  Ships disabled; fails closed when enabled without a key.
- **Nexus observability dashboard**: real-time conversation, diagnostics, and
  evaluation surfaces; coherence, fatigue, and prediction-error charts; evaluation
  sidecar tab; perception-locus toggle.
- **Eight read-only sidecar observers**: coherence, replay (memory-ID-only by
  default), Empatheia accuracy, voice-alignment divergence, fatigue, prediction
  error, welfare (gray-zone event flagging), and Nous policy. All write daily
  JSONL; none publish to the bus.
- **Comprehensive `docs/` tree**: architecture overview, per-module references,
  process guides (cognitive cycle, global workspace, fork/merge lifecycle, sleep
  and maintenance, evaluation sidecar, voice alignment, perception locus),
  configuration reference, security and privacy guide, glossary, and contributing
  guide.

[26.06.0a1]: https://github.com/kaineone/kaine/releases/tag/26.06.0a1
