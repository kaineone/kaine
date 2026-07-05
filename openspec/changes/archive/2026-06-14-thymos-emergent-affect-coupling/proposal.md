# Make affect coupling emergent, not imposed

## Why

Thymos currently writes the entity's own valence/arousal/dominance state
*directly toward* a detected speaker's emotion on every `audition.emotion`
event, by design **bypassing the entity's Scherer appraisal**
(`thymos/coupling.py`, `module.py::_apply_coupling_nudge`; the current
`thymos-affect-coupling` spec mandates "not routed through the Scherer
appraisal"). That is a hardwired, automatic affect behavior: the entity's
feeling is moved by an external write rather than produced by its own appraisal
of what it perceives.

This violates the project's stance that the entity's dispositions and affect
must **emerge** from the architecture, not be scripted — unless a cited
neuroscience mechanism establishes the behavior as innate (and then cited at the
implementation site). The coupling path has **no citation at the code site**; it
asserts an automatic emotional-contagion mechanism the architecture should let
*emerge* instead. (Same class of error as the removed entity-side covenant
surface: a behavior baked into code that should not be predetermined there.)

Emotional resonance with others is welcome — but it must arise because the
entity *perceives and appraises* another's state, modulated by its own goals,
familiarity, and current condition. Whether and how it resonates is then an
experimental outcome, not a hardwired reflex.

## What Changes

- Perceived speaker emotion (`audition.emotion`) becomes an **input to the
  entity's own Scherer appraisal**, weighted by familiarity — not a direct write
  to the dimensional state. The existing appraisal → classify → bounded
  state-nudge path produces the entity's response.
- Remove `_apply_coupling_nudge` (the appraisal-bypassing direct VAD write) and
  the `DriftSafeguard` it needed (direct writes are gone; appraisal nudges are
  already small and bounded).
- The perceived-emotion signal is a **transient, decaying** perceptual input, so
  sustained input cannot pin appraisal; it is bounded by the coupling weight.
- Keep: familiarity modulation (now an appraisal weight from
  `empatheia.agent_model`), the `[thymos.coupling].enabled` opt-out (ships
  `false`), graceful degradation when no familiarity is known, and the
  familiarity-cache persistence across fork restore.
- Reinterpret `[thymos.coupling]` knobs as appraisal-influence weights (no
  config-key removal; semantics documented).
- Update `docs/` and flag the paper agent: `KAINE_Paper.md` currently asserts the
  coupling "is automatic; it is not mediated by reasoning about the speaker's
  state" — that line must change to the appraised-input framing.

## Impact

- Affected spec: `thymos-affect-coupling` (core requirement inverted).
- Affected code: `kaine/modules/thymos/coupling.py`, `kaine/modules/thymos/module.py`.
- Behavior ships OFF by default (`[thymos.coupling].enabled = false`) — no change
  to the shipped all-off first-boot posture.
- No entity boot required to validate (unit-level appraisal tests).
</content>
</invoke>
