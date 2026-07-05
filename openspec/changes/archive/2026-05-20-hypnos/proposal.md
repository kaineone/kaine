## Why

`docs/kaine-paper.md` §3.5 names Hypnos as the maintenance module
that "manages scheduled non-interruptible rest windows with five
consolidation phases: memory review and pruning in Mnemos, belief
revision in Nous, affective reset in Thymos, temporal recalibration
in Chronos, and voice alignment if Lingua is present." Build prompt
§6.1 is identical and emphasizes the structural defense against
model collapse (Shumailov et al. 2024): "the training signal comes
from deterministic template renderings rather than the LLM's own
outputs."

Hypnos is the only Phase 6 module — landing it closes the
maintenance group and ships `v0.6-maintenance`.

## What Changes

- Introduce `kaine.modules.hypnos` package split four files:
  - `scheduler.py` — `RestScheduler` tracking when the next sleep
    is due. `try_defer()` extends rest until a configured maximum
    deferral window passes; after that, sleep starts even mid-
    activity (the paper's "sovereignty commitment, not a performance
    optimization").
  - `phases.py` — pure-function phase implementations for memory
    consolidation (calls Mnemos.consolidate_now), belief revision
    (calls a NARS step burst via Nous's process), affective reset
    (Thymos.affective_reset), temporal recalibration (Chronos
    cursor + drift reset). Each phase is async and returns a
    `PhaseResult` dataclass; failures in one phase are logged and
    don't stop the others.
  - `voice_alignment.py` — `DPOPairBuilder` reads Lingua's
    intent-expression JSONL and produces preference pairs (chosen =
    `faithful_rendering`, rejected = `generated_text`). `Trainer`
    protocol + `FakeTrainer` (test stand-in that always rejects with
    "no training backend") + `UnslothDPOTrainer` skeleton that
    lazy-imports `unsloth` for QLoRA+DPO and writes a new LoRA
    adapter to `state/hypnos/adapters/<timestamp>/`. The training
    signal is the deterministic faithful_rendering — model-collapse
    defense per Shumailov et al. is structural.
  - `module.py` — `Hypnos(BaseModule)` orchestrating the five phases
    in sequence. `enter_sleep()` is the public entry. Once started
    it does NOT yield control to non-Hypnos work until all phases
    complete (the build prompt's "Non-interruptible once begun").
- `[hypnos]` block in `config/kaine.toml`: schedule (interval in
  seconds), max deferral seconds, Nous step burst size, per-phase
  timeouts, voice alignment config (LoRA rank, learning rate, DPO
  beta, max_samples, capability_loss_threshold).
  `modules.hypnos = false`.
- Tests use Fake collaborators for Mnemos/Nous/Thymos/Chronos. An
  opt-in test (`KAINE_HYPNOS_RUN_REAL_TRAINING=1`) exercises a tiny
  end-to-end Unsloth DPO run.

## Capabilities

### New Capabilities

- `hypnos`: five-phase sleep orchestrator. Owns the rest scheduler
  with max-deferral guarantee, the phase pipeline, the DPO pair
  builder, and the trainer protocol used for voice alignment.

### Modified Capabilities

None — Hypnos calls into existing module APIs that already exist
(Mnemos.consolidate_now, Thymos.affective_reset, NARProcess.send/step,
faithful renderer).

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `mnemos`, `nous`,
  `thymos`, `chronos`, `lingua` (intent-expression log path),
  `faithful-renderer`. All shipped.
- **Repo:** adds `kaine/modules/hypnos/*.py`, `tests/test_hypnos_*`,
  updates `pyproject.toml` (packages list), `config/kaine.toml`,
  gitignored `state/hypnos/`.
- **Optional dep:** `unsloth` for the real DPO training path —
  listed in `[project.optional-dependencies]` `training` extra so
  the default install stays small.
- **No runtime impact** on the cycle. Hypnos is registered in code
  paths but not auto-added to ModuleRegistry; first boot decides
  whether to schedule the first sleep.

After this change Phase 6 closes and `v0.6-maintenance` is tagged.
