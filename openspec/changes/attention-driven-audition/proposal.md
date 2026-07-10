# Attention-driven general auditory perception

## Why

Hearing is currently **speech transcription for the language organ**, not
perception. Audition captures audio, runs speech-to-text and a vocal-emotion
classifier, and publishes a transcript (and a speaker's emotion) toward Lingua;
its only salience is a forward model over a speech-shaped feature vector
(emotion-class distribution plus utterance timing and energy). There is **no
general acoustic encoder** and **no representation of non-speech sound**. A door
slam, breaking glass, an alarm, music, a dog, footsteps approaching — none of it
is perceived: it is transcribed into empty or garbage text and assigned a
meaningless "vocal emotion." The entity cannot *notice an interesting sound*; it
can only parse a voice.

This is asymmetric with vision. Topos encodes the whole visual scene into an
embedding, scores change and forward-model prediction error over that embedding to
produce salience for *any* visual stimulus, and now foveates by attention and
arousal. Hearing has no analog. A KAINE entity should be able to **listen to its
surroundings for anything interesting**, the way it looks at a scene — voices are
one kind of salient sound, not the whole of hearing.

This change gives audition the perceptual front end vision already has, and the
attention mechanism foveation just added, applied to sound:

- a **general acoustic encoder** that represents *any* sound, not only speech;
- **acoustic salience** from change and forward-model prediction error over that
  representation, so a novel or sudden sound is salient regardless of whether it
  is a voice;
- **arousal-modulated auditory attention** — the audio analog of foveation — that
  lets the entity attend to a salient sound stream and narrows or widens the
  auditory window with arousal;
- **speech as a specialization**: transcription and vocal emotion fire when the
  attended stimulus is detected as speech, off the general perceptual path,
  instead of being the whole of it.

This is a **design-first** OpenSpec change. It specifies the mechanism; it does
not implement it. The lead reviews this design before any code lands. It
deliberately mirrors `attention-driven-foveation` — the same shape (general
encoder → change/prediction-error salience → arousal-driven attention → a
specialized detail path) applied to the auditory modality.

## What Changes

- **Audition gains a general acoustic front end.** A frozen self-supervised audio
  encoder (vendor-neutral, the way the paper treats the vision encoder) turns each
  captured audio window into an embedding that represents speech, music, and
  environmental sound alike. The embedding lives only in memory and is released as
  it ages out, exactly as the existing perception path guarantees — no raw audio
  or embedding is ever written to disk.
- **Salience becomes acoustic-general.** The forward model predicts the next
  acoustic embedding from a recurrent auditory buffer, and the change plus
  prediction error over that embedding set the salience of what the entity hears —
  so a sudden, novel, or surprising sound reaches the workspace whether or not it
  is speech. This replaces the speech-shaped feature vector (emotion + timing +
  energy) as the salience substrate; the speech features remain available on the
  speech path.
- **Auditory attention is arousal-modulated.** The entity attends to the most
  salient sound stream (the auditory analog of the fovea — stream/source
  selection rather than uniform processing), and arousal sets the breadth of the
  auditory attentional window (the same distinct visual/auditory coupling
  foveation uses for the fovea, grounded in the psychophysics of arousal and the
  breadth of attention). The attended-stream descriptor is published content-free
  (which stream, how salient — never the audio).
- **Speech is a triggered specialization, not the whole of hearing.** Capture is
  no longer confined to voice: the general path hears everything. When the
  attended/salient stimulus is detected as speech, the speech path (transcription
  → Lingua, vocal emotion) fires on that stream. Voices are a subset of
  interesting sounds; the language organ receives words when there are words,
  while the entity still hears the rest of the world.
- **The zero-raw-sense-data invariant is preserved.** The acoustic embedding, the
  buffer, and any attended-stream crop live only in process memory and are
  released as they age; nothing is written to disk, exactly as the existing
  perception path guarantees.

## Capabilities

### New Capabilities

- `auditory-perception`: a general acoustic encoder over each captured window;
  change and forward-model prediction-error salience over the acoustic embedding
  for any sound; arousal-modulated auditory attention (salient-stream selection
  and an arousal-set attentional window); and publication of a content-free
  attended-stream/salience descriptor. Memory-only, zero-persistence.

### Modified Capabilities

- `audition`: the module represents all captured sound as a general acoustic
  embedding and hears non-speech stimuli, rather than processing audio only as
  speech. Speech-to-text and vocal-emotion classification become a specialization
  triggered when the attended stimulus is detected as speech, published on the
  same `audition.out` stream; the self-hearing gate and event-type contracts are
  unchanged.
- `audition-predictive`: the auditory forward model predicts over the general
  acoustic embedding (not the speech-shaped emotion/timing/energy vector), so the
  prediction-error salience it produces covers any sound; the buffer remains a
  statistical descriptor and never stores raw audio or raw embeddings.

## Impact

- **Depends on:** `audition`, `audition-predictive`, `audio-input` (the capture
  path the embedding is derived from), `reproducible-perception` (the seeded/live
  feed), `thymos-affect-coupling` (the arousal value that sets the auditory
  window), `entity-time` (the cadence the salience updates on). All shipped.
- **Repo (at implementation time, not in this change):** would add a general
  audio encoder collaborator and an acoustic forward model to
  `kaine/modules/audition/`, extend `Audition.process_audio` (general encode →
  salience → attention → speech-gated STT/emotion), a workspace→Audition arousal
  seam (like the affect / topos-arousal seams), and config under `[audition]`.
  No entity is booted by this change.
- **Dependencies:** a frozen self-supervised audio encoder (a new optional
  `[audio]`-extra collaborator, lazy-imported; the build/test suite stays green
  without it via a fake, exactly as vision does). No new runtime service.
- **Encoder cost:** one acoustic encode per captured window replaces the current
  STT-and-emotion-on-every-window; the speech path now runs only on speech,
  which should be comparable or cheaper — but this MUST be confirmed on the host
  benchmark against the tick budget before enabling, not asserted.
- **Behavior:** the entity hears its whole auditory environment and can be drawn
  to non-speech events; hearing becomes active and attention-driven. Off by
  default behind a config toggle; the existing speech path remains the shipped
  behavior until the general path is benchmarked and enabled.

## Open questions (for the lead)

- **Encoder choice** — which class of frozen self-supervised audio encoder (kept
  vendor-neutral in the paper). The design records the selection criteria; the
  concrete model is an operator/host decision, as with the vision encoder.
- **Auditory "foveation"** — attend by *stream/source separation* (attend one
  sound among many) versus a simpler single-attended-window; and whether spatial
  auditory localization is in scope now or a later phase.
- **Speech detection** — keep the existing voice-activity path to gate the STT
  specialization, or drive the speech gate from the general salience/attention
  signal directly.
