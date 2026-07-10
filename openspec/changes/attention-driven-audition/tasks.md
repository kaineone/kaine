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

## 0. Operator decisions — OPEN (decide before Phase 1 build)

- [ ] 0.1 Audio encoder: which frozen self-supervised general audio encoder (see
      design §Flags 1) — selection criteria recorded; concrete model is a host
      choice, named vendor-neutrally in the paper.
- [ ] 0.2 Attention granularity: single attended window first, stream/source
      separation later? (Flag 2)
- [ ] 0.3 Speech gating: keep the voice-activity detector to route the STT+emotion
      specialization, or drive it from the general salience/attention signal?
      (Flag 4)

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

- [ ] 2.1 Stream/source separation: attend one sound among several (the true
      analog of foveation, "attend one thing among many").
- [ ] 2.2 An attention schema for sound: publish a predicted next attended stream,
      content-free, for the self-model and diagnostics.

## 3. Phase 3 — spatial hearing + embodiment tie-in

- [ ] 3.1 Auditory localization: a content-free direction ("where" for a sound),
      the analog of the fovea's coordinates.
- [ ] 3.2 Route the auditory attention direction into the shared "attention /
      gaze direction decoupled from the body" control the foveation change names,
      so screen gaze, camera gaze, and sound direction share one mechanism.

## 4. Docs / paper

- [ ] 4.1 Update `docs/modules/audition.md` with the general-perception path once
      implemented.
- [ ] 4.2 The paper's §3.4 Audition framing is reframed to general auditory
      perception (speech as a specialization) under the same review pass that
      motivated this change; keep design vs shipped honest (paper change, not code).
