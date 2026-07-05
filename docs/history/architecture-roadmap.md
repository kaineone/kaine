# KAINE Architecture Roadmap (Historical)

Generated: 2026-06-06. Reflects the change set after the Phase-4/5 proposal
revision: `hypnos-restructure` replaced by two focused changes, two new changes
added (`eidolon-self-inference`, `state-encryption`), and the JAX stack
(pymdp 1.0 + dreamerv3) introduced.

**JAX stack note:** `nous-pymdp-swap` requires `pymdp>=1.0` (JAX backend) and
`phantasia-dreamerv3` requires `danijar/dreamerv3` (MIT, JAX). Both are JAX-
backed and use CPU-only JAX by default; GPU acceleration is operator-configured.
These are the only changes in this build plan that introduce JAX as a dependency.

**Already-implemented branches:** `drives-to-behavior` (merged, ✓ Complete) and
`condition-language-organ` (drafted, not yet in a feature branch) come from
already-implemented or near-ready feature work. Both must be sequenced and
carried forward into the phase plan — `drives-to-behavior` is already done;
`condition-language-organ` needs its own OpenSpec change and branch.

---

## Phase 1 — Forward models and perception rename

**Go/no-go:** all five changes are independent of each other; they share only
shipped deps (`chronos`, `topos`, `audition`/`vox`). Gate: unit suite green,
no runtime regression with layer disabled.

| Change | Key Dependencies | Notes |
|---|---|---|
| `rename-audition-vox` | `audio-input` (shipped), `audio-output` (shipped) | Rename; consumer changes cascade |
| `chronos-forward-model` | `chronos` (shipped) | Smallest; CfC already present |
| `topos-forward-model` | `topos` (shipped), `rename-audition-vox` | Reuses `ncps`/torch |
| `audition-forward-model` | `rename-audition-vox`; **new:** `librosa` (`[audio]` extra) | librosa replaces parselmouth |
| `soma-forward-model-fatigue` | `soma` (shipped), `hypnos` lifecycle events | Produces `soma.fatigue` trigger consumed by Phase 4 |

---

## Phase 2 — Memory, executive, and affect

**Go/no-go:** depends on `rename-audition-vox` (Phase 1). `mnemos-replay` is a
hard gate for Phase 4 `hypnos-consolidation`. Gate: replay round-trip tested,
affect coupling degrades gracefully without Empatheia.

| Change | Key Dependencies | Notes |
|---|---|---|
| `mnemos-replay` | `mnemos` (shipped), `thymos` | Produces `mnemos.replay`; gates Phase-4 consolidation |
| `thymos-affect-coupling` | `thymos` (shipped), `rename-audition-vox`, `empatheia-module` | Degrades if Empatheia absent |
| `spontaneous-recall` | `mnemos` (shipped) | ✓ Complete (already merged) |
| `drives-to-behavior` | `executive-action-intent` (✓ Complete) | ✓ Complete (already merged); drive→behavior loop closed |

---

## Phase 3 — New modules (Empatheia, Nous/pymdp, Phantasia)

**Go/no-go:** these are the highest-risk changes (new modules, JAX stack). Land
in order: Empatheia (no JAX), then pymdp-Nous, then Phantasia. Gate: each
module's own test suite green; JAX CPU-only confirmed; Phantasia world-model
checkpoint serialization verified.

| Change | Key Dependencies | Notes |
|---|---|---|
| `empatheia-module` | `rename-audition-vox`, `mnemos`, `fork-merge` | No JAX; Qdrant-backed agent model |
| `nous-pymdp-swap` | `cognitive-cycle`, `executive-action-intent` (✓); **new:** `pymdp>=1.0` (JAX) | Removes ONA binary; JAX dep introduced here |
| `phantasia-dreamerv3` | `mnemos-replay`, `hypnos`; **new:** `danijar/dreamerv3` (MIT, JAX) | JAX; world-model checkpoint; gates Phase-4 consolidation |

---

## Phase 4 — Hypnos restructure (split from original `hypnos-restructure`)

**Go/no-go:** `hypnos-fatigue-phases` depends only on `soma-forward-model-fatigue`
(Phase 1) — land first, independently. `hypnos-consolidation` gates on three
Phase-3 changes; land after all three are green. The abliteration probe in
`hypnos-consolidation` is welfare-load-bearing and must not be bypassed.

| Change | Key Dependencies | Notes |
|---|---|---|
| `hypnos-fatigue-phases` | `hypnos` (shipped), `soma-forward-model-fatigue` | No JAX; fatigue trigger + five-phase structure + oscillator freq hook; **lands Phase 4 independently** |
| `hypnos-consolidation` | `hypnos-fatigue-phases`, `nous-pymdp-swap`, `phantasia-dreamerv3`, `mnemos-replay` | NAR burst removal; phase-3 associative replay; **abliteration-probe welfare veto** (hard gate, welfare-load-bearing) |

---

## Phase 5 — Structural, evaluation, and self-model

**Go/no-go:** `oscillatory-layer` touches BaseModule and salience — land after
all modules exist (post Phase 3). `sidecar-observers` activates incrementally.
`eidolon-self-inference` and `state-encryption` are independent of each other;
`state-encryption` should land after `phantasia-dreamerv3` and `sidecar-observers`
to cover those paths, but is not a hard blocker on either.

| Change | Key Dependencies | Notes |
|---|---|---|
| `oscillatory-layer` | `module-pattern` (shipped), `cognitive-cycle`/`syneidesis`; **new:** `snnTorch` (CPU, optional) | Ships disabled; PLV in `metadata['coherence']`; `set_frequency` hook for Hypnos Phase 1 |
| `sidecar-observers` | `evaluation-sidecar` (shipped); each observer activates as its source lands | 8 observers; `redact_content` default on replay; welfare + prediction-error + Nous policy observers added |
| `individuation-boundary` | `evaluation-sidecar` (shipped), `adapter-ties-dare-merge` (✓) | Permutation-test instrument; evidence for Guardians only |
| `eidolon-self-inference` | `eidolon` (shipped) | Observation-driven self-model population; disabled by default; no raw speech persisted |
| `state-encryption` | none (structural); best landed after `phantasia-dreamerv3` + `sidecar-observers` | AES-256-GCM at rest; names all cognitive state files in SECURITY.md; fork/merge bundle encryption |
| `vox-prosodic-mirroring` | `vox` (shipped), `audition-forward-model` | Prosody mirroring; identity-preserving |

---

## Changes carried forward from prior feature branches

| Change | Status | Action needed |
|---|---|---|
| `drives-to-behavior` | ✓ Complete (merged) | No action; drive→behavior loop closed |
| `condition-language-organ` | Drafted (not yet a feature branch) | Needs OpenSpec change dir + branch; sequences after Lingua swap |

---

## Per-phase go/no-go summary

| Phase | Label | Gate condition |
|---|---|---|
| 1 | Forward models + rename | Unit suite green; no runtime regression |
| 2 | Memory, executive, affect | Phase 1 complete; `mnemos-replay` round-trip tested |
| 3 | New modules (JAX stack) | Phase 2 complete; JAX CPU-only confirmed; each module isolated |
| 4 | Hypnos split | `hypnos-fatigue-phases`: Phase 1 only. `hypnos-consolidation`: Phase 3 complete + abliteration probe present |
| 5 | Structural + evaluation | Phase 3 complete; `oscillatory-layer` post all-modules; `state-encryption` post Phantasia + sidecar |
