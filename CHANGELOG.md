# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows Ubuntu-style `YY.MM.patch` with PEP 440 pre-release suffixes.
The public brand is **26.06.0a1**; pip normalizes this to `26.6.0a1` (expected).

---

## [Unreleased]

### The base-thesis reconfiguration (July 2026)
- The default configuration became the base-thesis test (#71): six diverse
  predictive processors (Soma, Chronos, Topos, Audition, Thymos #79/#84,
  Lingua) competing through the workspace, everything richer gated off.
- STT and the conversation surface deactivated by default (#77); Lingua's
  prompt became a neutral state-verbalizer with no roleplay persona (#73);
  interruptible, redirectable utterance landed (#81).
- Perception drives the workspace: prediction-error salience with
  self-calibrating alerts (#75); real-time A/V sync for the playlist feed via
  one shared clock (#80); the containerized deployment boots end-to-end (#72).
- Under pre-renumbering squashes: the on-device voice-alignment GPU window,
  the unified seed-keyed audio-visual feed, perception-extras provisioning,
  and biologically-grounded multi-rate timing with config time-dilation.
- Docs reframed to the base-thesis form (#82); Paracosm renamed Paracosmic
  (#83); Zen Dots replaced Oxanium as the console face (#91).

### Research-run preparation (September 2026)
- The nexus conversation surface gained an env override for containerized
  deployments (#92).
- Sleep pauses the stimulus playlist and resumes at the exact pause point;
  wake restores the remembered pre-sleep perceptual locus (#93).
- Dependency floors raised: pytest-asyncio 1.4, webrtcvad 2.0.10,
  easydict 1.13, unsloth 2026.7.3, chex 0.1.92 (#94).
- Eleven shipped OpenSpec changes archived; specs reconciled with shipped
  reality under the openspec 1.12 validator (#95, #98).
- Research-event contract drift fixed — intents, Chronos, the Thymos emotion
  label, and the Topos discontinuity signal now reach the curated research
  log; a canonical stream registry with reality-anchored drift tests replaced
  three hand-maintained stream lists; [volition].interrupt_threshold wired
  (#96).
- The pre-boot correctness batch (#97): stacked freeze sources (a
  welfare-protective pause survives Spot recovery), freeze/resume restores
  the desired perception flags, speech-liveness guard timeouts and a
  realization-failed audit event, novelty-signature expiry, playlist-audio
  clock resync on producer start, poison-batch-proof cursors, tail-seeded
  cursors on production boots, a guaranteed (aborted-flagged) sleep-completed
  event, an interval maintenance net, and a welfare-notify rate limit — with
  the sig-expiry and notify-rate-limit wiring completed in #100.
- Research-run infra hardening (#99): config profiles baked into the image,
  durable volumes for all research output, a 4 GB Redis ceiling, container
  log rotation, git-sha provenance via a build-time env var, quadlet parity,
  and the qdrant healthcheck fixed in committed compose.

## [26.06.0a1] — 2026-06-07

**First public alpha.** The architecture is feature-complete and tested in-tree.
Released publicly under the Cognitive Architecture License (CAL) v0.2; formal
legal review is still pending and a v1.0 bump may follow, but publication does
not wait on it. The alpha number increments as the release stabilizes.
Pip-normalized form: `26.6.0a1`.

**Status:** public alpha; all modules ship disabled; first boot is
operator-supervised.

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
