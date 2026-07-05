# entity-time (new capability: subjective clock + multi-rate timing)

## ADDED Requirements

### Requirement: A shared entity clock is the single source of subjective time

The system SHALL provide one injected `EntityClock` that exposes the entity's
**subjective** time as `wall_elapsed * time_scale`, and every module that times a
*cognitive* process (fatigue accumulation, perception sampling cadence, attentional
locus dwell, drive/affect time constants, recall throttling, the cognitive-cycle
tick pacing) SHALL derive its durations and "now" from that clock rather than
reading the wall clock directly. Timers that protect *infrastructure* rather than
model cognition (the Spot liveness watchdog, the preservation monitor poll, network
request timeouts, the voice-alignment GPU window) SHALL continue to use real
wall-clock time, and each such site SHALL be explicitly classified as
infrastructural so it does not dilate with the mind.

#### Scenario: Cognitive timing runs in subjective time

- **WHEN** a cognitive timer (e.g. the fatigue accumulator or the perception
  sample cadence) advances while `time_scale != 1.0`
- **THEN** it advances in subjective time (scaled), so the whole mind's clock moves
  coherently and no two cognitive timers desynchronize from each other

#### Scenario: Infrastructure timing stays on real time

- **WHEN** the entity's `time_scale` is changed
- **THEN** the Spot watchdog, preservation poll, and request timeouts are unchanged
  (a watchdog must not slow down because the mind sped up, nor speed up because it
  slowed)

### Requirement: Time dilation is configurable, coherent, and honestly bounded

The system SHALL expose a global `[cycle].time_scale` (default `1.0` = real-time)
that scales the `EntityClock` and the cycle pacing together, so one value dilates
the entire mind. A value of `0` SHALL freeze the entity (reusing the existing
freeze/suspend path: the subjective clock stops). Values greater than `1.0` SHALL
be permitted as an **aspirational target**: the cycle SHALL attempt the faster rate
and, when the hardware cannot sustain it, SHALL throttle via the existing Soma
rate-reduction path and SHALL report the shortfall (slip / achieved-vs-target rate)
rather than silently overrunning.

#### Scenario: One knob dilates the whole mind

- **WHEN** an operator sets `[cycle].time_scale = 0.5`
- **THEN** the tick pacing and every cognitive timer run at half subjective speed
  together, with no per-module drift

#### Scenario: Faster-than-real-time is a throttling target

- **WHEN** `time_scale > 1.0` and the hardware cannot hold the implied tick rate
- **THEN** the cycle throttles to a sustainable rate and surfaces the achieved rate
  and slip honestly (no silent overrun, no faked rate)

#### Scenario: Zero scale is freeze

- **WHEN** `time_scale = 0`
- **THEN** the entity is frozen via the existing suspend path and resumes cleanly
  when the scale is raised

### Requirement: Perception is sampled faster than conscious access

Sensory sampling SHALL be decoupled from, and run faster than, the conscious-access
(workspace) tick, reflecting that humans sample the senses (~10 Hz vision, faster
audio) well above the ~3 Hz rate at which contents reach awareness. The visual
sampling rate SHALL be raised above its prior 1 Hz toward the biological band, and
all sensory and tick rates SHALL be expressed against the `EntityClock` so they
dilate together with `time_scale`.

#### Scenario: Senses outrun awareness

- **WHEN** the entity runs at the default `time_scale`
- **THEN** the perception sample rate is higher than the workspace/experiential tick
  rate, so multiple sensory samples can inform one conscious update

### Requirement: Timing defaults are bounded by an empirical hardware benchmark

The shipped default rates SHALL be set from a measured benchmark of the sustained
per-tick cost and per-sensory-sample cost on the target accelerator, not from
guesses, and SHALL leave a stated margin so the cycle holds its rate without
chronic overrun. The change SHALL ship rates that preserve current behavior until a
benchmarked value is deliberately adopted, and the benchmark SHALL be repeatable so
other operators can re-derive safe rates on their own hardware.

#### Scenario: Defaults come from measurement

- **WHEN** a rate default is raised from its current value
- **THEN** the new value is justified by a repeatable benchmark on the target
  hardware showing the cycle sustains it within the stated margin

### Requirement: Default configuration preserves current behavior

The system SHALL preserve its pre-change observable timing behavior under the
shipped defaults (`time_scale = 1.0`, unchanged rates), so introducing the clock
and dilation machinery is inert until an operator deliberately changes a rate or
the scale. The all-off first-boot guard SHALL remain satisfied.

#### Scenario: Inert by default

- **WHEN** the entity runs with shipped defaults (`time_scale = 1.0`, unchanged
  rates)
- **THEN** tick pacing, fatigue, perception cadence, and event timestamps match the
  pre-change behavior
