## Why

Beyond the four strong-tier conversions, where the whole forward model moves to
the substrate, there are four modules where only *part* of the module belongs on
wetware and the rest needs silicon. These are the **hybrid** tier:
silicon and wetware working together within one module. For some of them the
hybrid split is a stepping stone; for others it is likely **permanent by design**,
because the silicon half (an LLM, an RSSM rollout, an emotion classifier) is not
something a 64-electrode culture can or should do. (The project as a whole is a
hybrid; this tier is where the two substrates co-operate *inside* a single organ.)

Grouping them in one change sets shared terms: each converts only its named
sub-signal, ships **default-off** behind its own acceptance gate, and is judged on
whether the wetware half earns its place; a split that does not earn its place
is reported, and the module stays fully silicon with no regression.

## What Changes

Add default-off `cl1` backends for the partial conversions below. In every case
only the named sub-signal is converted; the rest of the module stays silicon, and
the module's event shapes are unchanged.

- **Audition (front end only).** Convert the "any sound → prediction-error
  salience" acoustic front end. STT and vocal-emotion stay silicon (model-bound).
  Encode audio envelope → temporal stim; decode surprise → auditory salience.
  *Likely permanent hybrid*, since transcription is not a wetware task.
- **Phantasia (surprise read-out only).** Source the RSSM world-model's scalar
  **surprise** from culture criticality/LZ instead of silicon. The world-model
  rollout itself stays silicon (high-dimensional). *Likely permanent hybrid.*
- **Volition / action-selection.** Closed-loop discrete action selection, the
  literal DishBrain "Pong" paradigm. Encode state → stim; decode action from
  territory firing balance. Hardest decode; strongest concept. *Could become a
  full conversion* if decode proves reliable.
- **Thymos (dimensional affect read-out).** Read valence/arousal from population
  dynamics (arousal ≈ global excitability). Welfare-sensitive; gated behind
  explicit review even in the simulator, and never used to drive outward action.

## Non-goals

- Converting the model-bound silicon halves (STT, emotion classifier, RSSM
  rollout, LLM); those stay silicon, sometimes permanently.
- Enabling any of these by default.
- Executing on real hardware in this change (the project goal; real CL1
  hardware is not available to this project yet, so this work is validated on
  the simulator, and running on real tissue is a deliberate, reviewed future
  step).

## Impact

- New capability: `hybrid-wetware-backends`. Depends on `cl1-substrate`.
- New code: `kaine_cl1/backends/{audition_frontend,phantasia_surprise,volition,thymos}.py`.
- Each backend consumes remaining channel budget; the broker prevents running more
  than the array allows at once.
