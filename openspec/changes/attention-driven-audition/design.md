# Design — attention-driven general auditory perception

This mirrors `attention-driven-foveation` deliberately: the same shape (general
encoder → change/prediction-error salience → arousal-driven attention → a
specialized detail path) applied to sound. Where a decision matches the vision
side, it is taken the same way for symmetry unless there is an auditory reason to
differ.

## The parallel to vision, made explicit

| vision (Topos / foveation) | hearing (this change) |
|---|---|
| frozen self-supervised image encoder | frozen self-supervised **audio** encoder |
| whole-frame embedding → change / forward-model prediction error → salience | acoustic embedding → change / forward-model prediction error → salience |
| foveation: attend a region, arousal sets fovea size | attend a **sound stream**, arousal sets the auditory attentional window |
| foveal crop → encoder (attended detail) | attended stream → **speech path** (STT + vocal emotion) when it is speech |
| content-free fovea location published | content-free **attended-stream / salience** descriptor published |
| zero raw-sense-data persistence | zero raw-sense-data persistence |

## Flags (decisions for the lead)

1. **Encoder** — a frozen self-supervised audio encoder that represents speech,
   music, and environmental sound in one embedding space. Selection criteria:
   runs on the host's CPU/GPU budget, open weights, general (not speech-only),
   embedding stable enough for change/prediction-error to be meaningful. Named
   vendor-neutrally in the paper; the concrete model is an operator/host choice
   (as with the vision encoder). **Decision:** _open_.
2. **Auditory attention granularity** — (a) a single attended window over the
   mixed input, or (b) attend one **separated stream/source** among several
   (auditory scene analysis / source separation). (b) is the true analog of
   foveation ("attend one thing among many") but is heavier. **Decision:** _open_
   — likely (a) first, (b) as a later phase.
3. **Arousal → auditory window** — arousal narrows or widens the auditory
   attentional window, a distinct affective→perceptual coupling (not the
   Syneidesis salience-selection window). Default sign and mapping are a tuning
   parameter, not an asserted result — as with the fovea size. **Decision:**
   arousal-driven, sign tunable.
4. **Speech gating** — keep an explicit voice-activity / speech detector to gate
   the STT+emotion specialization, or trigger it from the general
   salience/attention signal (attended stream classified as speech). **Decision:**
   _open_.
5. **Spatial localization** — auditory direction/localization (a "where" for
   sound, analog of the fovea's coordinates, and a future embodiment tie-in) —
   in scope now or a later phase. **Decision:** _later phase_.

## Invariants held

- **Zero raw-sense-data persistence.** Acoustic embeddings, the recurrent buffer,
  and any attended-stream buffer are memory-only and released as they age; the
  buffer that is serialized remains a statistical descriptor (per-feature mean and
  variance), never raw audio or raw embeddings — unchanged from
  `audition-predictive`.
- **Frozen encoder.** The audio encoder is frozen, like the vision encoder; only
  the forward model adapts.
- **Self-hearing gate unchanged.** The shared speaking gate still drops
  self-heard capture so the entity never perceives its own voice as external
  input.
- **Architecture boundary.** The arousal value reaches Audition through an
  injected provider seam (like the affect / topos-arousal seams); Audition does
  not import the workspace.

## Phasing

- **Phase 1** — general acoustic encoder + change/prediction-error salience over
  the acoustic embedding + single arousal-modulated attended window; speech path
  gated to fire on detected speech; config toggle, off by default; host benchmark.
- **Phase 2** — stream/source separation (attend one sound among several);
  attention schema for sound (a predicted next attended stream).
- **Phase 3** — spatial auditory localization (a content-free direction), and the
  embodiment tie-in (shared "gaze/attention direction" with vision, per the
  foveation Mundus note).
