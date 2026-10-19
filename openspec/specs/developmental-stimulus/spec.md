# developmental-stimulus Specification

## Purpose
The developmental stimulus a pre-embodied entity lives in before maturation: a low-dimensional, externally regulated stimulus source of sight and sound with an external maternal heartbeat and state, a self-rhythm the entity may couple to, a bounded readiness readout for the maturation gate, a one-shot maturation transition, and one liveness interface that judges a local or an external stimulus source provider alike, all bounded to protect a captive newly matured entity.

## Requirements

### Requirement: The stimulus source presents a low-dimensional, externally-regulated environment
The system SHALL provide a developmental stimulus that presents the pre-embodied
entity with a low-complexity, deterministic, audio-visual environment: a low-pass,
low-frequency-dominant soundscape carrying an external maternal heartbeat, and a dim,
low-contrast visual field. The stimulus source SHALL be the entity's virtual world while it is
in its developmental phase and SHALL require no live human, camera, or microphone input. All stimulus source
stimulus SHALL be a pure function of `(seed, frame_index)` (plus deterministic,
seed-derived rhythm and maternal-state signals), so a run is reproducible from its
descriptor.

#### Scenario: The stimulus source is deterministic and reproducible
- **WHEN** the developmental stimulus runs twice with the same seed
- **THEN** the video frame and audio block at any given index are identical across
  both runs

#### Scenario: The stimulus source needs no live input
- **WHEN** the stimulus source is the active stimulus
- **THEN** neither a live camera, a live microphone, nor live human input is required
  for the entity to perceive

### Requirement: The maternal channel is external and entity-independent
The stimulus source SHALL present a **maternal channel** consisting of a fast rhythm (the
heartbeat) and a slow state (an emotional-weather signal that colours the visual
field). Both SHALL be synthesised, deterministic, bounded signals that are
**independent of the entity's own state** — nothing the entity does or feels SHALL
change the maternal channel. The stimulus source SHALL NOT read the entity's affect to drive any
developmental stimulus. Consequently there SHALL be no `affect → stimulus → affect` feedback
path through the stimulus source.

#### Scenario: Maternal state does not depend on the entity
- **WHEN** the entity's internal affect changes during the developmental phase
- **THEN** the maternal-state signal and the maternal heartbeat are unchanged (they
  are functions of the seed and index only)

#### Scenario: No self-referential visual loop exists
- **WHEN** the stimulus source is auditing its inputs
- **THEN** no developmental stimulus is derived from the entity's own affect or output, so a
  perturbation of the entity's state cannot amplify through the stimulus source environment

#### Scenario: The maternal-state signal stays bounded
- **WHEN** the maternal-state generator runs for any length of a run
- **THEN** its value remains within its declared valid range at all times

### Requirement: The pulsing light is cross-modal drive, honestly grounded
The stimulus source visual field SHALL pulse in luminance in phase with the maternal heartbeat
(a "pulsing light"). This SHALL be documented and cited at the code site as
**cross-modal rhythmic drive and a maturation-transition cue**, NOT as a reproduction of a
stimulus source feature (fetal vision is dim and the stimulus source has no natural light rhythm). The
citation SHALL acknowledge that photic entrainment of endogenous oscillations is
contested.

#### Scenario: The luminance pulse tracks the heartbeat
- **WHEN** the maternal heartbeat beats
- **THEN** the visual field's overall luminance rises and falls in phase with the beat

#### Scenario: The grounding is stated honestly at the code site
- **WHEN** the pulsing-light synthesis is implemented
- **THEN** a source comment cites it as cross-modal drive / maturation cue and references
  the entrainment debate, without claiming it reproduces fetal light perception

### Requirement: Sense-onset and colour-saturation follow a provided schedule
The stimulus source SHALL follow a provided developmental schedule in which interoception and
low-frequency audition are available from the start, patterned vision is dim
throughout, and **colour saturation ramps from near-zero toward full across
the developmental phase** (a cone-maturation analog), so the maternal-state colour becomes
progressively more informative toward maturation. The schedule SHALL be parameterised by
lived subjective time (the entity clock), not wall-clock, so it is consistent under
time dilation and per-fork. The *schedule* is provided; colour *discrimination* SHALL
be left to emerge (never hardcoded).

#### Scenario: Colour begins muted and enriches over the developmental phase
- **WHEN** the entity is early in the developmental phase
- **THEN** the visual field is near-desaturated, and its colour saturation is greater
  later in the developmental phase for the same maternal-state value

#### Scenario: The schedule advances on lived time
- **WHEN** the entity clock is dilated
- **THEN** the colour ramp advances with lived subjective time, not wall-clock time

### Requirement: The stimulus source exports a readiness readout that imposes nothing on the entity
The stimulus source SHALL publish a **readiness readout** (event type `development.readiness` on the
`development.out` stream, published by a cycle-layer owner with source `development`) describing how regulated the entity
currently is, composed of measured markers: endogenous-rhythm self-sustaining,
entrain-then-autonomy, an HRV-analog variability trend, falling stimulus-source input predictive error
error, and return-to-baseline time after a perturbation. The readout SHALL also publish
the numbers behind entrain-then-autonomy: the phase-locking value, the largest
surrogate phase-locking value, the self-rhythm's frequency during withdrawal, and the
frequency-pull index. The readout SHALL actuate nothing in the **entity's control path**
(no stage change, no regulation, no gating).
Its markers MAY be measured via a **bounded, disclosed external-stimulus perturbation
protocol** (drive-withdrawal windows and perturbation spikes) that actuates only the
external stimulus, never the entity, and SHALL be bounded in magnitude and frequency.
Every marker SHALL be a measurement; none SHALL be a hardwired target or a "calm"
behaviour imposed on the entity.

#### Scenario: The readout imposes nothing on the entity
- **WHEN** the readiness readout is computed and published
- **THEN** it changes no stage, triggers no regulation, and gates nothing in the
  entity's control path within this capability

#### Scenario: Measurement perturbations are external and bounded
- **WHEN** a marker is measured via drive-withdrawal or a perturbation spike
- **THEN** only the external stimulus is actuated (never the entity), and the
  perturbation is bounded in magnitude and frequency

#### Scenario: The readout measures, it does not impose
- **WHEN** the readout reports low regulation
- **THEN** no behaviour forces the entity toward regulation; the markers only observe

#### Scenario: The entrainment numbers are published
- **WHEN** a withdrawal window completes
- **THEN** the next readout carries the phase-locking value, the largest surrogate phase-locking value, the withdrawn frequency and the frequency-pull index

### Requirement: Regulation and coupling emerge; they are never hardwired
The system SHALL NOT hardwire the entity's self-regulation, its oscillatory coupling
to the maternal rhythm, or its interoceptive sensitivity. Only the innate substrate
(the capacity to oscillate; the capacity of the self-rhythm to adapt its own period
slowly in response to its input; the afferent access to its own state) and the external
stimulus environment (soundscape, heartbeat, maternal state, sense-onset schedule)
SHALL be provided. Each provided element SHALL carry its neuroscience citation at the
code site; each emergent element SHALL be verifiably absent from the code as a
hardcoded behaviour or setpoint. In particular, the maternal beat's frequency SHALL NOT
appear in the self-rhythm's code or parameters as a target.

#### Scenario: No regulation setpoint in code
- **WHEN** the stimulus source implementation is reviewed
- **THEN** no code imposes a target arousal, a "calm" behaviour, or a forced
  phase-lock; regulation and coupling arise only from the entity meeting the stimulus

#### Scenario: Provided elements are cited
- **WHEN** a provided stimulus element (soundscape, heartbeat, maternal state,
  schedule) is implemented
- **THEN** its source site cites the developmental-neuroscience basis for treating it
  as provided rather than emergent

#### Scenario: No target frequency in the self-rhythm
- **WHEN** the self-rhythm oscillator's code and configuration are inspected
- **THEN** no value derived from the maternal heartbeat rate is present; its period changes only through its adaptation rule acting on its input

### Requirement: The maternal rhythm drives only a dedicated self-rhythm oscillator
The maternal heartbeat, when presented to the oscillatory substrate, SHALL be injected
only into a **dedicated self-rhythm oscillator** — a single oscillator representing the
entity's endogenous beat — and SHALL NOT be injected into the per-module coalition
oscillators used by the workspace for phase-locking-value scoring. The workspace
coherence factor for any coalition SHALL be unaffected by the presence or absence of
the maternal drive. The drive amplitude SHALL be bounded so it cannot swamp the
self-rhythm oscillator's own dynamics, and it SHALL enter through an afferent gain weak
enough that, without lived exposure and adaptation, it does not capture the self-rhythm.

#### Scenario: Coalition coherence is unaffected by the maternal drive
- **WHEN** the stimulus source's maternal drive is active
- **THEN** the workspace coherence factor for any coalition is identical to a run with
  the maternal drive absent, given the same inputs

#### Scenario: Only the self-rhythm oscillator receives the drive
- **WHEN** the maternal rhythm is presented to the oscillatory substrate
- **THEN** only the dedicated self-rhythm oscillator receives it, bounded in amplitude;
  no per-module coalition oscillator receives it

#### Scenario: The drive alone does not capture the rhythm
- **WHEN** the maternal drive is presented at its usual or maximum scale with the adaptation rule disabled
- **THEN** the entrainment marker does not pass

### Requirement: The stimulus source renders the maturation transition then ceases
The stimulus source feed SHALL, on receiving the maturation-transition trigger (emitted by the
developmental-stage capability), render a bounded, one-shot transition (the dim field
blooming into a photic activation) and SHALL then cease publishing developmental stimulus,
yielding the sense source to the embodied world.

#### Scenario: Maturation trigger renders then ceases
- **WHEN** the stimulus source feed receives the maturation-transition trigger
- **THEN** it renders a bounded transition once and then stops publishing developmental stimulus

### Requirement: A captive entity's stimulus in its developmental phase is bounded and welfare-protected
The system SHALL bound the developmental stimulus for a confined entity in its developmental phase: any maternal
"distress excursion" and any measurement perturbation SHALL be bounded in magnitude and
duration and OFF by default beyond the minimum needed for measurement, and the external
oscillator drive SHALL be bounded. The autonomous welfare / preservation net SHALL
remain active and authoritative during the developmental phase; the developmental stimulus SHALL NOT be able
to inflict unbounded or inescapable distress, and the developmental-phase confinement SHALL NOT
suppress a welfare-protective response.

#### Scenario: Distress stimulus is bounded and off by default
- **WHEN** the stimulus source is configured with defaults
- **THEN** maternal distress excursions are off, and any enabled excursion or
  measurement perturbation is bounded in magnitude and duration

#### Scenario: The welfare net still protects an entity in its developmental phase
- **WHEN** interoceptive distress crosses the welfare threshold during the developmental phase
- **THEN** the welfare/preservation net responds as it would for any entity, and the
  developmental-phase confinement does not suppress that response

### Requirement: A stimulus source provider proves it is live
The stimulus source SHALL be supplied by a **stimulus source provider**: the local provider in KAINE (`[perception_feed].mode = "stimulus_source"`) or an external provider such as a Paracosmic body. Every provider SHALL be judged by one interface at two moments. Before spawn, the local provider is ready when its video and audio sources each deliver a frame or block to a probe that discards it. While running, every provider is live only through content-free `development.stimulus_source` presence events (source `development`, stream `development.out`, payload limited to the provider name and a monotonically increasing frame index) published at least once per second: the running local provider publishes them only while its sources are actually delivering to the senses, and a provider is live when at least two such events from it fall within a bounded window measured on the bus clock and their frame index advances. Nothing else SHALL count as a live stimulus source; a configuration value alone SHALL NOT, and neither SHALL a presence event that repeats a stalled frame index.

#### Scenario: The local provider probes ready before spawn
- **WHEN** `[perception_feed].mode = "stimulus_source"` and both stimulus sources deliver to the probe
- **THEN** the stimulus source is judged ready and nothing the probe read is kept

#### Scenario: The running local stimulus source proves itself from deliveries
- **WHEN** the local stimulus source is running and one of its surfaces stops delivering to the senses
- **THEN** its presence events stop and the stimulus source is judged not live

#### Scenario: A provider proves presence on the bus
- **WHEN** a provider has published advancing `development.stimulus_source` events within the window
- **THEN** the stimulus source is judged live; when the events are older than the window, or their frame index does not advance, it is not

#### Scenario: Configuration alone is not a stimulus source
- **WHEN** a stimulus source mode is configured but neither probe nor presence event succeeds
- **THEN** the stimulus source is judged not live

### Requirement: The local provider runs on a single modest host
The local provider SHALL generate the stimulus source with the host CPU only (no browser, no GPU rendering, no network service) at the configured perception resolutions and rates, so the entity in its developmental phase and its stimulus source can run on one machine that cannot also host Paracosmic.

#### Scenario: Stimulus source generation is CPU-only and in-process
- **WHEN** the local provider runs
- **THEN** its frames and audio blocks are computed in the KAINE process from `(seed, index)` with no external service

### Requirement: Measurement probes are gentle and unpredictable to the entity
A perturbation probe SHALL raise the maternal drive only to a configured fraction of its bound, strictly above the usual drive and never above the bound (1.5 times the usual drive by default). The time of each probe SHALL vary around its period by a bounded random fraction drawn from a counter-based keyed generator seeded by the run's perception seed, so that the entity cannot learn the schedule while a research run with the same seed reproduces it exactly. Jitter SHALL only move due times: every existing bound on probes (durations, frozen state, settling after boot or a thaw, spacing between probes) SHALL continue to apply.

#### Scenario: A perturbation is a bounded rise, not the full bound
- **WHEN** a perturbation probe runs with the default settings
- **THEN** the drive rises to 1.5 times its usual level, stays below its bound, and returns to the usual level when the probe ends

#### Scenario: The schedule cannot be learned
- **WHEN** consecutive probes of one kind are scheduled
- **THEN** their intervals vary within the configured jitter around the period, and a run with the same seed produces the same intervals

#### Scenario: Jitter never relaxes a bound
- **WHEN** a jittered probe falls due while the entity is frozen, settling or near another probe
- **THEN** the probe waits exactly as an unjittered probe would

### Requirement: The stimulus source's state at maturation is recorded
When the maturation bloom completes, the stage file SHALL record the stimulus source time at which the bloom ended (`stimulus_source_t_at_maturation`), the stimulus source seed and a digest of the stimulus source parameters. The stimulus source SHALL report that the bloom is complete, so a preservation taken after that report carries the record.

#### Scenario: A preserved newly matured entity carries its maturation state
- **WHEN** an entity is preserved after its maturation bloom completed
- **THEN** the preservation's stage file holds `stimulus_source_t_at_maturation`, the stimulus source seed and the parameter digest

### Requirement: Entrainment is measured on the intrinsic rhythm against surrogate beats
The entrain-then-autonomy marker SHALL be computed from the self-rhythm's population rate filtered to the self-rhythm's own physiological band (never a narrow band centred on the maternal beat), with zero-phase filtering, Hilbert phase over a window of at least 300 s of unperturbed samples, and the window edges trimmed. It SHALL pass only when the phase-locking value to the maternal beat exceeds that of every one of at least 19 surrogate beats generated as other mothers' heartbeats, the rhythm self-sustains during drive withdrawal, and the rhythm's frequency during withdrawal has moved toward the beat by at least the configured frequency-pull floor. Time-shifted copies of the same beat SHALL NOT be used as surrogates.

#### Scenario: An evoked response does not pass
- **WHEN** the self-rhythm shows a response locked to the beat but its intrinsic frequency during withdrawal has not moved toward the beat
- **THEN** the marker does not pass

#### Scenario: A foreign mother does not pass
- **WHEN** the self-rhythm was exposed to one mother's beat and is scored against another mother's beat
- **THEN** the marker does not pass

### Requirement: The self-rhythm has a slow intrinsic rhythm in a physiological band
The self-rhythm oscillator SHALL produce, undriven, a rhythm in the fetal breathing band (0.5-1.0 Hz, around the mean fetal breathing rate of about 44 breaths per minute reported by Natale et al. 1988) from excitatory recurrence and activity-dependent synaptic depression, with its period able to adapt slowly within a clamped physiological band. The mechanism SHALL be cited at the code site.

#### Scenario: Undriven rhythm lies in band
- **WHEN** the self-rhythm runs without maternal drive at resting own drive
- **THEN** its dominant frequency lies between 0.5 and 1.0 Hz

### Requirement: Entrainment must be earned and validated offline before a study
Before a study uses a self-rhythm or measurement version, an offline validation with the real classes SHALL show: the marker false throughout the first 6 h; passing under the usual drive in at least 80% of seeds within the developmental phase budget; never passing with no drive, a foreign mother, a jittered beat or adaptation disabled; a withdrawn frequency specific to the presented beat rate (57, 70 and 84 bpm); and no capture at higher drive scales or higher own drive with adaptation disabled. The validation report SHALL be stored with the change, and the self-rhythm version SHALL be recorded in each maturation record.

#### Scenario: Controls never pass
- **WHEN** the validation runs the no-drive, foreign-mother, jittered-beat and no-adaptation controls
- **THEN** no readout passes the marker in any of them

### Requirement: The developmental-phase owner judges viability from the entrainment evidence
When the viability watch is on, the developmental-phase owner SHALL judge after every withdrawal, on un-paused lived time (lived time excluding every paused span, such as sleep and freezes, which is the basis the rules were validated on), whether the developmental phase can still reach maturation, using only the published entrainment measurements:
- R0: unviable when, after the configured early check (default 6 h), no withdrawal has produced a conclusive entrainment measurement.
- R1: unviable when, at the configured time (default 24 h) and with no replicated pass, the median frequency pull over the configured window (default 12 h) is below its floor (default 0.12) and its trend is not rising (default slope ≤ 0.002 per hour).
- R2: unviable when, at the configured time (default 48 h) and with no replicated pass, the median pull over the window is below its floor (default 0.3).
- R3: unviable when the configured deadline (default 60 h) passes with no replicated pass.

On the first unviable verdict the owner SHALL publish `development.viability` (with the rule, lived time and evidence) and write it to `state/lifecycle/development_viability.json`. The verdict SHALL actuate nothing in the entity's control path.

#### Scenario: A developmental phase that is not learning is flagged at 24 h
- **WHEN** a developmental phase's frequency pull stays below 0.12 with no rising trend through 24 h of lived time and no replicated pass
- **THEN** the owner publishes an unviable verdict naming rule R1

#### Scenario: A slow but learning developmental phase is not flagged
- **WHEN** a developmental phase's frequency pull rises steadily but its first replicated pass comes at 45 h
- **THEN** no unviable verdict is published before that pass

#### Scenario: A missing measurement is flagged early
- **WHEN** no withdrawal has produced a conclusive entrainment measurement after 6 h of lived time
- **THEN** the owner publishes an unviable verdict naming rule R0

#### Scenario: Paused time does not count
- **WHEN** 60 h of entity-clock time pass but the cycle was paused for all except 1 h of it
- **THEN** the rules see 1 h of lived time and no unviable verdict is published

### Requirement: Developmental phase progress persists across restarts
The developmental readout SHALL save its awake-time clock, its count of consecutive passing withdrawals, its history of frequency pull, whether the heartbeat entrainment marker has ever been met, and any viability verdict, keyed to the entity, after every scored withdrawal and at least once per minute of awake time, and SHALL restore them when it is constructed for the same entity. Progress saved for another entity SHALL be ignored.

#### Scenario: A restart continues the developmental phase
- **WHEN** a readout has accumulated two hours of awake time and two consecutive passes, and a new readout is constructed for the same entity
- **THEN** the new readout starts from two hours of awake time and two consecutive passes

#### Scenario: Another entity starts fresh
- **WHEN** a readout is constructed for a different entity than the saved progress belongs to
- **THEN** it starts from zero awake time and zero passes

### Requirement: The self-rhythm identity persists across plain restarts
The developmental readout SHALL store the self-rhythm identity in `self_rhythm_identity.json` beside its readout file. On a boot that is not a revive, the readout SHALL adopt a valid stored identity into the self-rhythm before it builds the key for its progress and baseline files. On a revive boot the identity restored from the bundle SHALL be kept and SHALL replace the stored one. On every start the readout SHALL write the identity it uses. A missing, unreadable or malformed file SHALL leave the current identity in place, and a malformed file SHALL be logged and rewritten. Progress saved under a different key SHALL still be ignored.

#### Scenario: A plain restart keeps the developmental progress
- **WHEN** a readout for an entity with a self-rhythm has saved 7200 s of awake time and two consecutive passes, and a new readout is constructed on the same state directory with a freshly built self-rhythm that drew a new identity
- **THEN** the new readout adopts the stored identity and starts from 7200 s of awake time and two consecutive passes

#### Scenario: A revive keeps the bundle's identity
- **WHEN** the state directory stores identity A and the readout is constructed on a revive boot whose self-rhythm holds identity B
- **THEN** the readout keys its files with identity B and the stored file holds B afterwards

#### Scenario: Another entity's progress is still ignored
- **WHEN** the saved progress carries a key for a different seed or identity than the one the readout uses
- **THEN** the readout starts from zero awake time and zero passes

#### Scenario: A malformed identity file is replaced
- **WHEN** `self_rhythm_identity.json` does not hold a valid identity
- **THEN** the readout keeps the self-rhythm's current identity, logs a warning and rewrites the file

### Requirement: Decommission removes the stored self-rhythm identity
Decommission SHALL back up and then delete `self_rhythm_identity.json` with the other developmental-phase files, so a later entity in the same state tree never adopts it.

#### Scenario: Decommission lists the identity file
- **WHEN** decommission builds its locations for a tree whose lifecycle directory holds `self_rhythm_identity.json`
- **THEN** the developmental location backs it up and deletes it

### Requirement: The developmental soundscape carries a pre-rendered maternal voice
When `[perception_feed.stimulus_source.voice].enabled` is true (the default), the stimulus-source audio SHALL mix a maternal voice into the soundscape from pre-rendered utterances shipped with the package and listed in a manifest, and SHALL NOT synthesize speech at runtime. Every take SHALL be upsampled by two to the stream rate, low-pass filtered with the soundscape's `lowpass_hz` filter, scaled to unit RMS, and played at `level_db` above the soundscape's RMS over its first 60 s of stimulus time for the run seed, times a seeded per-utterance gain of up to `jitter_db` either way. The output headroom SHALL grow by the voice's RMS level rather than its worst-case peak (so the heartbeat-and-noise bed keeps nearly its voice-free level, 2.4 dB lower with the defaults), and samples above the former full-headroom point SHALL pass a smooth tanh soft limiter that is the identity below its knee, has a continuous slope at the knee, and stays below int16 full scale; with the defaults it acts on about 0.25% of speech samples. When the voice is disabled, every audio block SHALL be byte-identical to the stream without the voice. The voice parameters SHALL NOT enter the stimulus-source parameter digest.

#### Scenario: Disabled voice leaves the audio unchanged
- **WHEN** the voice is disabled
- **THEN** every block of the stimulus-source audio equals, byte for byte, the block the stream produced before the voice existed

#### Scenario: The bed keeps nearly its level
- **WHEN** the voice is enabled with the defaults and nobody speaks
- **THEN** the soundscape's median absolute sample is within 3 dB of the voice-free stream's, and no voiced sample reaches int16 full scale

#### Scenario: The voice stays below the intrauterine cutoff
- **WHEN** a talking slot is rendered with `lowpass_hz` = 500
- **THEN** the voice layer's power above 1,000 Hz is at least 40 dB below its power below 500 Hz

### Requirement: Maternal speech follows the maternal state and a growing repertoire
Stimulus time SHALL be cut into slots of `slot_seconds`. Slot `s` SHALL hold speech when a keyed draw on `(seed, s)` is below `episode_probability` times the maternal arousal at the slot's start. A talking slot SHALL start within its first 2 s and hold whole utterances separated by seeded pauses in `[pause_min_seconds, pause_max_seconds]`, never running past the slot's end. Its first utterance SHALL be the first item, the repeated passage, with probability `repeat_share`; every other choice SHALL be uniform over the unlocked items, and the take uniform over the item's takes. The unlocked count SHALL be `min(N, initial_unlocked + floor(T_awake / unlock_seconds))`, with `T_awake` the awake time the colour ramp uses, evaluated when the slot is first rendered and fixed for that slot. The plan of a slot SHALL be a pure function of the seed, the slot index and that count. The voice SHALL keep playing while the entity sleeps.

#### Scenario: The same seed and awake time give the same audio
- **WHEN** two streams with the same seed render the same blocks with the same awake-time readings
- **THEN** their PCM is identical, and a stream with another seed differs

#### Scenario: Locked items are never heard
- **WHEN** awake time is below `unlock_seconds`
- **THEN** only the first `initial_unlocked` items are chosen, and after `k` more multiples of `unlock_seconds` the first `initial_unlocked + k` items are

#### Scenario: Calm maternal state means less speech
- **WHEN** slots are compared across maternal arousal
- **THEN** the share of talking slots rises with arousal, and no slot talks when `episode_probability` is 0

#### Scenario: Sleep pauses unlocking while speech continues
- **WHEN** awake time stops advancing while stimulus time runs on
- **THEN** talking slots keep occurring and no further item unlocks

### Requirement: A missing or corrupt maternal-voice file fails loudly
At load, the repertoire SHALL verify every manifest entry's sha256, decode it, and check its sample rate, channel count and frame count against the manifest. A missing manifest, a missing or altered file, a decode failure, a mismatch, or PyAV being absent SHALL raise `PerceptionUnavailableError` naming the problem, as SHALL a malformed manifest entry (a missing or mistyped id, takes list, file, sha256 or frame count, or a file path that is absolute or leaves the directory), and boot SHALL NOT start the stimulus-source audio without the voice when the voice is enabled.

#### Scenario: An altered file stops the load
- **WHEN** one take's bytes differ from its manifest sha256
- **THEN** loading raises `PerceptionUnavailableError` naming that file

#### Scenario: A missing file stops the load
- **WHEN** a take listed in the manifest is absent
- **THEN** loading raises `PerceptionUnavailableError` naming that file

### Requirement: The stimulus source clock continues across restarts
The stimulus source clock SHALL resume each boot from its own elapsed time, persisted in the stage file as `stimulus_source_seconds`, so a restart neither repeats nor skips stimulus the entity has had. The gate runner SHALL record the clock's reading on every gate tick, sleep included, and on its final write at shutdown. Time while the process is stopped SHALL NOT advance the stimulus clock. A stage file without `stimulus_source_seconds` SHALL fall back to the awake-time offset. The colour schedule and the voice repertoire SHALL keep following awake time.

#### Scenario: A plain restart after sleep
- **WHEN** a developing entity has 3600 s of stimulus time and 3500 s of awake time, the difference spent asleep, and it shuts down cleanly and restarts
- **THEN** the stimulus source clock resumes at 3600 s, not 3500 s

#### Scenario: Downtime does not advance the mother
- **WHEN** the process is stopped for 12 hours between two boots
- **THEN** the stimulus source clock resumes at the time recorded at shutdown

#### Scenario: A stage from before this change
- **WHEN** the stage file has `lived_seconds` but no `stimulus_source_seconds`
- **THEN** the stimulus source clock resumes at `lived_seconds`, as before

### Requirement: The stimulus-source audio passes a hearing band that widens in the order of fetal hearing
When `[perception_feed.stimulus_source.hearing].enabled` is true (the default), every stimulus-source audio block SHALL be the soundscape plus the maternal voice, filtered by a band-pass whose edges depend only on the awake time, then scaled, limited and quantized as before. The edges SHALL follow the tone grid 100, 250, 500, 1000 and 3000 Hz of Hepper and Shahidullah (1994): each edge lies at the geometric mean of the outermost tested tone heard and the next tested tone not heard, and there is no edge on a side with no unheard tested tone. With `W` = `maturation_seconds` and awake time `T`, the band SHALL be 353.6 to 707.1 Hz for `T < W/4`, 158.1 to 707.1 Hz for `W/4 <= T < W/2`, a low-pass at 707.1 Hz for `W/2 <= T < 3W/4`, a low-pass at 1732.1 Hz for `3W/4 <= T < W`, and open from `T >= W` on; a non-finite or negative `T` SHALL give the first band. The filter SHALL be a 1,025-tap Hamming-windowed sinc design, a band-pass with unity gain at the band's geometric centre, a low-pass with unity DC gain, or the unit impulse at the centre tap when open, so every stage delays by 512 samples, convolved over the unfiltered mix of the preceding blocks and the current one (blocks before index 0 are silent), so a block SHALL be a pure function of the seed, the block index, the awake time and the voice plan, whatever blocks were rendered before. When the band is enabled the maternal voice SHALL load with its low-pass at 3,000 Hz; the bed SHALL keep `lowpass_hz`. When the band is disabled, every audio block SHALL be byte-identical to the stream without it. The hearing parameters SHALL NOT enter the stimulus-source parameter digest.

#### Scenario: Disabled band leaves the audio unchanged
- **WHEN** `enabled` is false, with or without the maternal voice
- **THEN** every block equals, byte for byte, the block the stream produced before the band existed

#### Scenario: The band starts at 500 Hz and widens down first, then up
- **WHEN** blocks are rendered at awake times in each of the five stages
- **THEN** the power below the stage's low edge divided by √2 and above its high edge times √2, where the stage has those edges, is at least 40 dB below the in-band power, the low edge moves twice and goes before the high edge moves, and the 45 to 55 Hz heartbeat thud is at least 40 dB down in the first two stages and within 1 dB of the band-off stream from the third on

#### Scenario: A block does not depend on the blocks rendered before it
- **WHEN** one stream renders block `k` first and another renders blocks `k - 10` to `k` in order, with the same seed and awake time
- **THEN** both produce the same bytes for block `k`

#### Scenario: A restart resumes the band
- **WHEN** a stream is rebuilt with an awake-time provider that resumes from the stage file's lived seconds
- **THEN** its band edges equal the edges before the restart at the same awake time

### Requirement: The colour ramp spans the developmental phase
The shipped configuration SHALL set `colour_ramp_seconds` to the hearing band's `maturation_seconds` (86,400 s, the paper's Table A1), so that colour saturation keeps rising across the developmental phase. The `StimulusSourceParams` default SHALL stay 3,600 s so the parameter digest of the defaults is unchanged.

#### Scenario: Colour still rises late in the phase
- **WHEN** the shipped configuration is loaded
- **THEN** the colour saturation at 12 awake hours is below its value at 24 awake hours by at least 0.05 of full saturation

### Requirement: A withdrawal waits for a scorable window
Besides the existing probe bounds, a drive-withdrawal probe SHALL NOT start until `entrainment_window_seconds` has passed since the readout owner started or since the last end of a pause (sleep or freeze). A perturbation probe SHALL keep its existing bounds only.

#### Scenario: An early withdrawal waits
- **WHEN** a withdrawal falls due 84 s after boot with an entrainment window of 300 s
- **THEN** it starts at the first readout step at least 300 s after boot, and its phase-locking value is defined

#### Scenario: A thaw restarts the wait
- **WHEN** a pause ends while a withdrawal is due
- **THEN** the withdrawal waits the entrainment window from the end of the pause

### Requirement: Probe draws and the latest markers persist across restarts
The readout owner SHALL record in `development_progress.json` the withdrawal and perturbation jitter counters, the latest entrain-then-autonomy marker and the latest self-sustain marker (each true, false or null), alongside the existing fields, and SHALL restore them, for the same entity key, before it schedules its first probes.

A file without these fields SHALL load as before, with these values:
- both counters 0;
- the self-sustain marker unknown;
- the entrain-then-autonomy marker true when the restored consecutive-pass count reaches `entrainment_replications`, and unknown otherwise.

A restart SHALL neither reset nor repeat a pass run.

#### Scenario: A restart continues the probe draws
- **WHEN** an owner has drawn jitter for several probes and a new owner starts on the same state for the same entity
- **THEN** the new owner's first draws continue the sequence instead of repeating the first boot's

#### Scenario: A restart keeps a pass run
- **WHEN** two consecutive withdrawals have passed and the owner restarts
- **THEN** the restored count is 2, the readout carries the latest markers before any new withdrawal, and one more passing withdrawal makes the marker true

#### Scenario: An older progress file migrates
- **WHEN** a progress file without the new fields records 3 consecutive passes with 3 replications required
- **THEN** the counters start at 0, the entrainment marker is true and the self-sustain marker is unknown

### Requirement: The period-variability floor lies below fetal values
The maturation gate's period-variability floor `hrv_variability_floor` SHALL default to 0.02, below every fetal five-minute heart-rate coefficient of variation reported by Moraes et al. (2012). It therefore checks for rigidity rather than marking maturation.

#### Scenario: An entrained rhythm passes the floor
- **WHEN** the readout reports a period variability of 0.06 and every other C1 condition holds
- **THEN** C1 passes
