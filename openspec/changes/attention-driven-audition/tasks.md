# Tasks — attention-driven general auditory perception

This change is **design-first**: this pass delivers the proposal, design, and spec
deltas only. No audition or perception code is written here. Implementation is
**phased** and gated on the lead's review of the design and on the host benchmark
confirming the acoustic-encode budget fits the tick.

**No pretend processes.** General auditory perception MUST NOT ship enabled until
the acoustic encoder, the change/prediction-error salience over the embedding, and
the arousal-modulated attention genuinely run and are benchmarked. Until then the
shipped path is the existing speech pipeline; selecting the general path before it
is real fails honestly rather than faking acoustic salience.

## 0. Operator decisions — OPEN (lead's formal call; Phase 1 shipped a provisional realization of each)

_Left unchecked: these are the lead's decisions, not code. Phase 1 shipped a
provisional realization of each (noted below); the formal lock is still the
lead's, unlike foveation's operator decisions which the operator locked with a
date._

- [ ] 0.1 Audio encoder: which frozen self-supervised general audio encoder (see
      design §Flags 1) — selection criteria recorded; concrete model is a host
      choice, named vendor-neutrally in the paper.
      _Phase-1 realization: a download-free default `SpectralAcousticEncoder`
      (`kaine/modules/audition/acoustic.py:SpectralAcousticEncoder`) plus an
      `AcousticEncoder` protocol so a stronger frozen SSL encoder plugs in; the
      concrete SSL model remains the lead's/host's choice._
- [ ] 0.2 Attention granularity: single attended window first, stream/source
      separation later? (Flag 2)
      _Phase-1 realization: a single arousal-modulated attended window
      (`acoustic.py:arousal_to_window`, `module.py:_perceive_acoustic`), the
      design's likely-(a)-first; source separation (b) is Phase 2 (task 2.1),
      still the lead's call to green-light._
- [ ] 0.3 Speech gating: keep the voice-activity detector to route the STT+emotion
      specialization, or drive it from the general salience/attention signal?
      (Flag 4)
      _Phase-1 realization: an explicit voice-activity heuristic
      (`acoustic.py:detect_speech`, gated in `module.py:process_audio`); whether
      to drive the gate from the general salience signal instead is still open._

## 1. Phase 1 — general acoustic front end + salience + arousal-modulated window

- [x] 1.1 Add a frozen general audio encoder collaborator to Audition: each
      captured window → acoustic embedding; memory-only, released as it ages
      (zero-persistence guard stays green). Fake encoder for tests, like vision.
- [x] 1.2 An acoustic forward model over the embedding + a recurrent auditory
      buffer; salience = change + normalized prediction error over the embedding,
      covering any sound (not the emotion/timing/energy feature vector). Keep the
      buffer a statistical descriptor (mean/variance), never raw audio/embeddings.
- [x] 1.3 A workspace→Audition arousal seam (provider/callback, no workspace
      import, like the affect / topos-arousal seams); arousal sets the auditory
      attentional window (distinct affective→perceptual coupling; sign tunable).
- [x] 1.4 A single arousal-modulated attended window over the input; publish a
      content-free attended-stream/salience descriptor (which stream, how salient
      — never audio) on `audition.out`.
- [x] 1.5 Speech as a specialization: a voice-activity/speech detector routes
      detected-speech segments to the existing STT + vocal-emotion path (→ Lingua),
      off the general perceptual path; the general path perceives the rest.
- [x] 1.6 Config: a general-audition toggle under `[audition]`, off by default;
      encoder id, buffer/window sizes, arousal→window mapping, speech-gate mode.
- [x] 1.7 Host-benchmark the acoustic-encode (+ speech path on speech only) cost
      against the tick budget; gate enabling on it. Report a NULL/regression
      result honestly.

## 2. Phase 2 — auditory scene analysis

_Deferred — gated on the lead's review + the Phase-1 host benchmark, and mirrors
the still-unbuilt foveation Phase 2 (its `2.1` attention schema is likewise
unchecked). Not implemented here to avoid a pretend process (no separation/schema
is shipped as a stub)._

- [ ] 2.1 Stream/source separation: attend one sound among several (the true
      analog of foveation, "attend one thing among many").
      _Blocked/deferred: gated on OPEN operator decision 0.2 (single window vs
      source separation); design §Flags 2 calls (b) "heavier" and a later phase.
      Building it now would preempt the lead's call._
- [ ] 2.2 An attention schema for sound: publish a predicted next attended stream,
      content-free, for the self-model and diagnostics.
      _Deferred: "predicted next attended stream" presupposes multiple separated
      streams (depends on 2.1); with the Phase-1 single window there is one stream
      and the schema is degenerate. The vision analog (foveation task 2.1) is also
      unbuilt._

## 3. Phase 3 — spatial hearing + embodiment tie-in

_Deferred — design §Flags 5 marks localization a later phase; mirrors the
still-unbuilt foveation Phase 3–4._

- [ ] 3.1 Auditory localization: a content-free direction ("where" for a sound),
      the analog of the fovea's coordinates.
      _Blocked: localization needs ≥2-channel capture (interaural time/level
      differences); the capture path is mono (`LiveMicConfig.channels = 1`,
      `[audition].capture_channels = 1`). Producing a direction from mono audio
      would be a pretend process._
- [ ] 3.2 Route the auditory attention direction into the shared "attention /
      gaze direction decoupled from the body" control the foveation change names,
      so screen gaze, camera gaze, and sound direction share one mechanism.
      _Blocked: depends on 3.1, and on the vision side first wiring the fovea into
      the shared gaze control. The control surface now exists
      (`kaine/modules/mundus/control_surface.py` `gaze_yaw`/`gaze_pitch`), but
      foveation's own routing task (foveation `4.1`) is still unchecked, so there
      is no established shared seam to join yet._

## 4. Docs / paper

- [x] 4.1 Update `docs/modules/audition.md` with the general-perception path once
      implemented. — `docs/modules/audition.md` now documents the shipped Phase-1
      general path: the `general_audition` toggle + arousal-window/change-threshold
      config, the `audition.perception` content-free event, the encode → salience →
      arousal-window → speech-gate flow and the arousal seam
      (`set_arousal_provider`), `acoustic.py` in Key Files, the acoustic tests, and
      an explicit "later phases deferred" note.
- [ ] 4.2 The paper's §3.4 Audition framing is reframed to general auditory
      perception (speech as a specialization) under the same review pass that
      motivated this change; keep design vs shipped honest (paper change, not code).
      _Not actionable in this repo: the paper is not present in this public
      repository (no `.tex` / paper source / §3.4 here). Flagged, not ticked —
      this is a paper-only change to be made where the paper lives._
