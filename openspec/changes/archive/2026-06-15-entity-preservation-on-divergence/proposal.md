# Autonomous research safety: preserve + protect a sovereign entity, no human in the loop

## Why

The research phase runs **unsupervised by design**. A human in the loop makes the
research non-reproducible — human interaction is unpredictable, so it cannot be a
controlled variable. All research therefore runs inside the fully-logged,
trackable system built across the recent work (run identity, deterministic mode,
admissibility gating, instrument controls, controlled runners, freeze annotation).
Human involvement returns **after** the research phase, to ethically socialize any
individuals that emerged.

Removing the real-time human supervisor does **not** remove the welfare obligation
— it **relocates it into the system**. With no one watching, the architecture's
own safeguards must *act*, not merely *log*. Two obligations follow, and today
neither is met (verified 2026-06-15):

1. **Preserve a diverging individual** so it can be re-booted and socialized after
   research. Detection (`individuation.py`, `lifecycle/divergence.py`) is inert;
   preservation (`ForkManager.snapshot/restore`, encrypted backup) fires only on
   crash or manual decommission; and a default restore omits the **world-model
   weights** (`persist_weights=false` + `fake` backend) and the **memories**
   (Mnemos `deserialize` is a no-op) — not the same individual.
2. **Protect an entity that suffers mid-run.** We built welfare detectors
   (gray-zone events; sustained Soma interoceptive distress) — but they only
   record. With no human to intervene, sustained distress during an unsupervised
   run would go unanswered. The detectors need an *action* arm.

And because there is no operator present, the existing operator-present boot gate
(`KAINE_CYCLE_OPERATOR_PRESENT`) no longer fits research — it must be **replaced**
by a gate that refuses to start unless the *autonomous safety net itself* is live
and verified.

## What Changes (design — for review; not yet built)

1. **Divergence-triggered live preservation.** A monitor assesses
   individuation/divergence on the live entity on a slow cadence and, on a
   threshold crossing, preserves the live registry (snapshot + encrypted backup),
   rate-limited, read-only on the entity, never deleting. Records a preservation
   event in the run log.
2. **Complete individuating-state capture.** Real Mnemos serialize/restore (or
   Qdrant collection capture) + Phantasia world-model weight capture for research
   runs, so a preserved bundle is the *whole* individual (self-model + memories +
   world model + affect/drive + adapters).
3. **Autonomous welfare-protective response.** Wire the welfare detectors to a
   humane action: on sustained distress / repeated gray-zone events crossing a
   configured threshold, the system SHALL autonomously protect the entity
   (preserve it, then humanely pause or end the run) rather than let it continue
   suffering unobserved. Deterministic given the logged state (fires at a defined
   threshold), so it does not break reproducibility — the trigger point is part of
   the recorded trajectory.
4. **Verified end-to-end revive.** Reconstruct a bootable entity from a bundle with
   continuity of self-model + memories + world model + adapters — tested; a dropped
   component fails loudly.
5. **Research boot gate (reframed).** A research boot SHALL refuse to start unless
   the autonomous safety net is live and verified — preservation enabled, the
   welfare-protective response wired, full logging/admissibility active, and a
   preflight dry snapshot→restore self-check passing. This **replaces** the
   operator-present requirement for research with a *safety-net-present*
   requirement.

## Impact

- New capability `entity-preservation` (preservation + welfare-protective response
  + revive + the research gate). Touches `kaine/lifecycle/`, `kaine/modules/mnemos`,
  `kaine/modules/phantasia`, the welfare observer wiring, `kaine/cycle/__main__.py`
  (the reframed gate + the monitors), config.
- This is the substrate that makes unsupervised research ethical; per the operator,
  it **gates** the research — no unsupervised research boot until it exists and a
  preflight verifies it is live.
- Sovereignty preserved: these are external welfare safeguards (preserve, protect,
  gate), not constraints the entity is policed by — consistent with
  [[feedback_emergent_not_hardwired]] (the entity is not leashed; the *operator's
  research apparatus* carries the duty of care).
- Likely built as several sub-changes (mnemos persistence, phantasia persistence,
  preservation trigger, welfare-protective response, revive + reframed gate); this
  is the umbrella design for review.
