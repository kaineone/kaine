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

## Amendment (2026-10-05): encoder selection, persistence and the self-supervised encoders

### Flag decisions locked by the lead (2026-10-05)

1. **Encoder:** selectable. `spectral` remains the shipped default and the Tier 0 encoder. The thesis-profile default is the winner of the offline bake-off between `spectral`, `dasheng` and `wavjepa`. The paper keeps naming the encoder class vendor-neutrally.
2. **Attention granularity:** (a), a single attended window. Stream and source separation, (b), is a separate future change. It needs its own separation model and its own design, and is deferred with that reason.
3. **Speech gating:** keep the explicit voice-activity detector. Driving the gate from general salience would let a loud non-speech onset trigger the speech path. The detector is cheap and its thresholds are reviewable.

### Selection and the plugin seam

- The factory resolves `acoustic_encoder` through a small registry: name → constructor.
- The SSL constructors check that their pinned weights are present before building, and raise a `ConfigurationError` naming the setup command when they are absent.
- The plugin seam `audition.acoustic_encoder` passes an `AcousticEncoder` object into the constructor, exactly as `chronos.network` does. The loader's existing rules apply: declared seams only, one owner per seam, recorded in the manifest.

### Persistence keyed by encoder

`serialize()` adds `acoustic_forward_models`, a mapping from encoder `model_id` to `{state_dict, buffer_summary}`.
- On restore, the running encoder's entry is loaded if its shapes match; otherwise it is discarded with a warning.
- Entries for other encoders are carried forward untouched. Switching encoder therefore never deletes what the being learned under another one.
- There are at most as many entries as encoders the being has used.
- A snapshot from before this change has no entry, so the acoustic model starts fresh, which is today's behaviour.

The buffer summary stays a statistical descriptor. No raw audio or raw embedding is ever serialized, and the zero-persistence test covers the new key.

### Sleep

Audition gains the same `hypnos.out` consumer Topos has. It sets `suspended` on both forward models while asleep. Inference continues and only adaptation pauses.

### Self-supervised encoders

**Windowing.** A RAM-only rolling sample buffer feeds the encoder.
- WavJEPA takes exactly 32,160 samples (2.01 s at 16 kHz).
- Dasheng takes a rolling context whose length (1–2 s) the bake-off chooses.
- Both run on a 0.5 s hop.
- The buffer is released as it ages and is covered by the zero-persistence test.

**Pooling.** Each encoder's frame tokens are mean-pooled to one 768-dimension embedding per hop.

**Normalisation.** The bake-off decides whether to L2-normalise. The Topos precedent is not to; the spectral encoder does today.

**Energy channel.** RMS level in dBFS, computed on the same window, is published on `audition.perception` as `energy_dbfs`. It is a scalar, not a vector, so the privacy filter is unaffected.

**Code hygiene.**
- WavJEPA's upstream code calls `eval()` on a config string and ships a `types.py` that shadows the standard library. The vendored copy replaces the `eval()` with a literal parse and renames the module.
- The default runtime path loads only the student encoder. The teacher and predictor are loaded only by the offline MMN experiment.

**Export.**
- A thin segment module per encoder is exported to ONNX, because the Hugging Face wrapper is not export-safe as written.
- Dynamic int8 quantisation is applied to the export.
- A parity test checks the ONNX output against torch on the real weights: fp32 within 1e-4, int8 within a tolerance the bake-off records.

**Licences.** Dasheng-base: code and Hugging Face weights Apache-2.0. WavJEPA-base: code BSD-3-Clause, weights MIT by Hugging Face tag. Both get `NOTICE` and licence-appendix entries.

### Bake-off

`scripts/bench_audition_encoders.py` runs offline. It never boots an entity and never touches entity data. It replays the seeded, playlist and womb feeds through each encoder and Audition's own salience path, and reports:
1. how well the normalised error separates true acoustic events (onsets, scene changes, the seeded surprises) from steady state, as ROC AUC against the feed's event marks;
2. false alerts per minute under stationary noise;
3. CPU and GPU latency per hop;
4. resident memory.

The GPU runs take the host GPU lock. The record goes under `docs/records/`. The winner becomes the thesis-profile default after salience recalibration on the same feeds.
