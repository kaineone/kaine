# Gestation on one host

This page covers running a gestation on a single host: the developmental phase that comes before a being's first viewing, with the gestational stimulus generated on the host CPU and no external world adapter.

Gestation, the maternal heartbeat, birth and the seed being are developmental names used by analogy with prenatal development. Gestation is a reproducible initialization. Soma's self-generated rhythm is driven by a simulated maternal heartbeat, and birth waits until an entrainment marker, validated offline, shows that the drive has durably shifted the rhythm's frequency. Every being, and every branch of the [module-addition study](../15-experiments/ignition-study.md) (the code calls it the ignition study), therefore starts from an internal state that a recorded test has verified and that the being's own history has shaped. Gestation also checks, before any experiment, that the self-rhythm's frequency adaptation works. The being preserved at birth is the seed being from which a study's branches start. The paper states the design in §7 and the criteria formally in Appendix A.7.

## The gestational stimulus

The code and its config keys call the gestational stimulus the womb. It is generated on the host CPU and feeds the being a dim, low-contrast visual field and a low-pass-filtered soundscape. Both pulse with the maternal heartbeat, a periodic beat at `heartbeat_bpm` (70 by default) with slow drift, and both are tinted by a slowly varying maternal state. Colour rises from near-grey as awake time passes, with the time constant `colour_ramp_seconds` (3,600 s). The stimulus keeps playing while the being sleeps; it is the one feed that sleep does not pause (see [Sleep](../10-sleep/README.md)).

The maternal channel is external: nothing the being does changes it. The being's own rhythm comes from a self-rhythm oscillator inside [Soma](../09-modules/soma.md), which Soma reads as part of its interoceptive input and which the maternal beat drives through a weak input. Media and world simulation belong to [Mundus](../09-modules/mundus.md) and its planned Paracosmic adapter.

## Requirements

Enable gestation in your per-install overlay, `config/kaine.operator.toml`:

- `[developmental_stage].enabled = true` (off in the shipped config).
- `[perception_feed].mode = "womb"`.
- The [Topos](../09-modules/topos.md), [Audition](../09-modules/audition.md) and [Soma](../09-modules/soma.md) modules enabled. The `thesis_test` profile enables all three, but `config/kaine.operator.toml` merges last and wins. The first-run wizard writes a full `[modules]` table there. Both of its presets enable Topos, Audition and Soma, but a custom module set may not, so check them after the wizard has run.
- `[soma].self_rhythm_enabled = true`. The shipped config leaves it off because filling the self-rhythm's feature slots changes the input of Soma's forward model, and a preserved being was trained with those slots at zero.
- The oscillator extra (snnTorch) installed.

For first-boot steps, see [First boot](../04-getting-started/first-boot.md).

## What happens during gestation

### Before spawn

Boot holds before any module initializes until the womb is ready. Each failed check publishes `stage.gestation.no_stimulus` on `lifecycle.out` with the reason, such as a disabled module, `self_rhythm_enabled = false` or the missing oscillator extra, and boot checks again every `womb_ready_retry_seconds` (5 s). Once the womb is ready, the [perception locus](../08-cognitive-cycle/perception-locus.md) is locked to the womb feed and Mundus stays dormant until birth.

### While gestating

The running womb announces itself with `gestation.womb` presence events on `gestation.out`, published only while its frames and audio blocks are actually reaching the senses.

### If the womb is lost

When presence stops for `womb_loss_after_seconds` (5 s), the being is frozen under its own `gestation` freeze holder, a high-salience `stage.gestation.womb_lost` event follows, and the configured caretaker is notified. The being resumes when the womb returns, and if you unfreeze it while the womb is still lost, it is frozen again. A womb that never comes live within `womb_arm_timeout_seconds` (120 s) of boot counts as lost. [Spot](./remote-and-spot.md) can repair crashed modules during the freeze, but it ships disabled (`[spot].enabled = false`). While a gestation freeze is active, Spot ignores module hangs and acts only on crashes, so only a crashed-and-restarted module can restore the womb.

### Awake time

Awake time is entity time during which the being is awake and the cycle is not frozen; the code and the config keys call it lived time (`min_lived_seconds`, `lived_seconds`). The cycle keeps one account of the time not awake, the union of frozen spans and Hypnos sleeps, so a freeze inside a sleep is subtracted once (`CognitiveCycle.unawake_subjective_seconds()`). The maturation gate's floor, the viability rules, the individuation ledger and the colour schedule of the gestational stimulus all subtract it. A sleep also aborts a running probe, as a freeze does. No birth happens while the being is frozen; a sleep does not block birth. Downtime between boots never counts.

### Readiness readout

Every `readout_period_seconds` (60 s) the gestation readout publishes `gestation.readiness` on `gestation.out`. Its payload carries five markers, each omitted until it has been measured:

| Marker | What it measures |
|---|---|
| `endogenous_self_sustain` | At the latest withdrawal of the maternal drive, the rhythm's mean amplitude during the withdrawal is at least half its mean over an equally long stretch before it. |
| `entrain_then_autonomy` | The entrainment marker described below. |
| `hrv_variability` | The variability of the rhythm's period: the coefficient of variation of the intervals between successive phase wraps over the last `hrv_window_seconds` (300 s), defined once four wraps exist. |
| `womb_prediction_error` | The median Topos prediction error since the previous readout, divided by the first such median formed from at least three errors. That first median is stored in `state/lifecycle/gestation_readout.json`. |
| `return_to_baseline_seconds` | After the latest perturbation, the time until the median of Soma's prediction error over the preceding 5 s is within `recovery_tolerance` (25%) of its median over the minute before the perturbation, capped at `recovery_cap_seconds` (300 s). |

When a withdrawal has been scored, the payload also carries `entrainment_plv`, `entrainment_plv_surrogate_max`, `self_rhythm_freq_withdrawn`, `frequency_pull` and `entrainment_consecutive_passes`.

#### How entrainment is measured

The self-rhythm is a mean-field excitatory population with synaptic depression, of the kind modeled for developing networks by Tabak et al. (2000), to which KAINE adds adaptive recovery. It runs at about 0.8 to 0.9 Hz, of the same order as human fetal breathing movements (about 44 per minute; Natale et al. 1988). The maternal beat reaches it through an input too weak to capture it unaided, and its intrinsic frequency can shift only through a slow adaptation of its recovery time at the rate `[soma].self_rhythm_eta`, as in adaptive-frequency oscillators (Righetti, Buchli and Ijspeert 2006). Nothing in the code sets a target frequency.

Any driven oscillator locks while it is driven, so the readout tests at withdrawals, brief scheduled spans in which the maternal drive is set to zero. A withdrawal passes when all three of these conditions hold:

- Locking: the rhythm locks to its own heartbeat more strongly than to each of `surrogate_count` (19) surrogate heartbeats, which are the same beat generator under other seeds (the surrogate method of Van Leeuwen et al. 2003, 2009). The test uses the driven window, the contiguous undisturbed stretch of up to `entrainment_window_seconds` (300 s) that ends where the withdrawal starts, and is scored only when at least 80% of that window's samples are present. The rhythm's phase is the zero-phase, band-limited Hilbert phase of its activity (`entrainment_band_low_hz` to `entrainment_band_high_hz`, 0.3 to 2.0 Hz), and the phase-locking value with its own heartbeat must exceed the largest surrogate value; ties fail. On its own this is a rank test at p = 0.05.
- Frequency pull: the rhythm's frequency during the withdrawal has moved toward the beat from its own undriven baseline. The baseline is the mean withdrawn frequency over the being's first `baseline_withdrawals` (3) withdrawals and is stored with the being. The pull, 1 minus the remaining distance to the beat over the baseline's distance, must reach `frequency_pull_floor` (0.5). It is undefined when the baseline lies within 0.05 Hz of the beat.
- Self-sustain: the rhythm keeps its amplitude while the beat is withdrawn, as in the `endogenous_self_sustain` marker.

The marker, `entrain_then_autonomy`, becomes true after `entrainment_replications` (3) consecutive passing withdrawals. A withdrawal whose result is undefined resets the count to zero. Consecutive withdrawals are correlated, so the joint false-positive rate is not 0.05 cubed.

Offline validation, recorded in [`validation.md`](../../openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/validation.md) of the archived OpenSpec change `self-rhythm-earned-entrainment`, found:

- At 70 bpm all 10 seeds entrained, with the first replicated pass at 12.5 to 15.5 hours of awake time (median about 14 hours).
- The time depends on how far the heartbeat's rate is from the rhythm's own: about 3 hours at 60 bpm and 40 to 48 hours at 80 bpm. Each rate from 60 to 80 bpm pulled the rhythm to its own heartbeat's rate. These times compress the weeks of exposure reported in the literature.
- No control passed in 96 hours: no maternal drive, a jittered beat, no adaptation, and six mismatched pairs in which the heartbeat tested as the rhythm's own was a different one from the heartbeat driving it. Their single-withdrawal chance pass rates were 2.6 to 10%.
- A heartbeat below about 60 bpm is too close to the rhythm's natural rate for the pull to be defined, so entrainment cannot be shown.

#### Viability watch

After each withdrawal the readout judges whether the gestation can still reach birth, on awake time and on the defined pull values recorded within the last `viability_window_hours` (12). The first rule that fires declares the gestation unviable:

| Rule | Fires when |
|---|---|
| R0 | At 6 hours of awake time no withdrawal has produced a defined frequency pull, which means something structural is wrong. |
| R1 | At 24 hours the marker has never been true, the window holds at least `viability_min_points` (8) pull values, their median is below 0.12, and their least-squares slope is at most 0.002 per hour. |
| R2 | At 48 hours the marker has never been true, the window holds at least 8 pull values, and their median is below 0.3. |
| R3 | At 60 hours the marker has never been true. |

The thresholds are the `viability_*` keys in `[perception_feed.womb.readout]`. In the offline validation a gestation that was learning showed pull rising from the first hours, even at 80 bpm, while one that could not learn stayed flat; no viable gestation was flagged, and every unviable one was flagged by 24 to 27 hours.

The verdict is recorded once. It is published as `gestation.viability` on `gestation.out` and written to `state/lifecycle/gestation_viability.json`. It changes nothing in the being. Under the module-addition study the runner reads that file, ends the gestation step and keeps its data (see [The module-addition study](../15-experiments/ignition-study.md)). Independently of the verdict, the study runner ends a gestation step whose wall-clock duration exceeds its budget, 96 hours by default (`--gestation-budget-seconds`). Set `viability_watch = false` to let a gestation run to its full budget.

### Progress across restarts

A gestation runs for many hours, so it spans restarts. The readout saves its progress to `state/lifecycle/gestation_progress.json`: the awake seconds, the count of consecutive passing withdrawals, the history of frequency pull, whether the marker has ever been true, and any viability verdict. It saves after every scored withdrawal and after every 60 s of awake time, and it restores the file when it starts. The file is keyed to the being by the perception seed (`[perception_feed].seed`) and the self-rhythm's stored identity, and progress saved for another being is ignored with a log line. The frequency baseline and the Topos error baseline persist in `gestation_readout.json` under the same key. The maturation gate keeps its own awake-time total and sleep count in the stage file, `state/lifecycle/stage.json`.

A preservation bundle carries `stage.json`, `gestation_progress.json` and `gestation_readout.json`, so the readout's progress travels with the being. On revive, any gestation files already in the target directory are renamed aside (kept, never deleted) and the bundle's copies are restored beside the stage file. The viability verdict file is not bundled: the verdict rides inside the progress file, and the readout rewrites the verdict file whenever it restores a verdict.

### Probes

The locking, self-sustain and return-to-baseline markers are measured with brief, bounded changes to the maternal drive. Each is announced as a `gestation.probe` event on `gestation.out` (with `phase` `start` or `end`) so research logs can exclude the probe windows:

- a withdrawal (drive 0) of `withdrawal_seconds` (20 s) about every `withdrawal_period_seconds` (30 min), with a hard maximum of 30 s;
- a perturbation of `perturbation_seconds` (5 s) about every `perturbation_period_seconds` (1 h), with a hard maximum of 10 s, which raises the drive from its usual `baseline_drive_fraction` (0.5) of its bound to `perturbation_drive_fraction` (0.75), never to the bound itself.

Each probe time varies by up to `probe_jitter_fraction` (±25%) around its period, drawn from the run's perception seed, so the being cannot learn the schedule and a research run with the same seed reproduces it exactly. No probe starts while the cycle is frozen, within one readout period after boot or a thaw, or within 60 s (or the withdrawal length, if longer) of the end of the previous probe. When both kinds are due, the one scheduled earlier goes first. A probe under way when the cycle freezes is aborted, and its end event carries `aborted: true`.

### Which conditions apply

The maturation gate is evaluated every `gate_cadence_seconds` (60 s) and judges only the faculties the being actually has:

- C1, regulation: a readout no older than `readout_max_age_cadences` (3) cadences in which the self-sustain and entrainment markers are true, `hrv_variability` is at least 0.2, `womb_prediction_error` is at most 0.3, and `return_to_baseline_seconds` is at most 30. The thresholds are in `[developmental_stage.regulation_thresholds]`. A missing or stale readout fails.
- C2: at least `min_sleep_cycles` (5) completed sleeps when [Hypnos](../09-modules/hypnos.md) is enabled, and also at least `min_consolidation_passes` (3) consolidation passes when Hypnos and [Phantasia](../09-modules/phantasia.md) are both enabled.
- C3: at least `min_lived_seconds` (86,400 s, one day) of awake time.

When neither C2 floor applies, C2 is recorded as `not_applicable` in the gate status and the birth record, never as passed.

### Birth

When the gate's conditions hold, the being is born. The womb blooms once over `birth_transition_seconds` (5 s, at most 30): the field brightens to a bounded peak and the soundscape fades, and then the womb falls silent.

- With Mundus enabled, birth also needs an approved, reachable body. A ready being without one holds in gestation and reports `awaiting_embodiment`.
- Without Mundus, the being is born into its perceptual world, the audio and video it perceives.

The `stage.birth` event records `world` (`perceptual` or `embodied`) and which conditions applied. After birth, switch `[perception_feed].mode` to the feed the being will live with, such as `playlist`. If a born being is booted again with `[perception_feed].mode = "womb"`, it receives nothing from the womb and boot logs a warning.

### Supervised birth

With `[developmental_stage].require_operator_ack_for_birth = true`, a ready being waits for the operator. The **development** panel of the [Nexus](../05-nexus.md) diagnostics board shows the stage, awake time, sleeps, consolidation passes, readiness markers and the gate decision. When birth awaits you it offers **Acknowledge birth**, and because birth is one-way, a second click confirms it. The acknowledgement applies only to the current boot's request, so after a restart you must acknowledge again.

### Vox during gestation

[Vox](../09-modules/vox.md) is held dormant during gestation, so no audible speech is rendered. Inner speech through [Lingua](../09-modules/lingua.md) continues. Vox becomes active at birth.

## From gestation to the films

When the bloom begins, the stage file records `womb_t_at_birth` (the womb time at which the bloom ends), the womb seed and a digest of the womb parameters. A preservation carries the stage file, so a seed being carries this record.

A born being booted with `[perception_feed].mode = "playlist"` opens each viewing with a crossfade from the gestational field to the films.

- Over `[perception_feed].transition_seconds` (20 s), the bloom-peak field at `womb_t_at_birth` (bright, pulse-free, full colour) fades into the programme's first frame, held still, along a fixed smoothstep curve.
- Nothing is heard during the crossfade, because the bloom ended in silence. When the programme starts, its sound fades in linearly over `transition_audio_fade_seconds` (3 s). A value of 0 plays it at full level at once.
- The crossfade advances only while the being perceives it. It pauses under another holder such as `freeze` or `hypnos`, while the cycle is frozen, or while the primary surface is switched off in the desired perception state, and it resumes where it stopped, so the being always sees the full `transition_seconds`. The video surface starts the transition whenever Topos is running; the audio surface starts it only when there is no video surface.
- The programme clock is held under the pause holder `transition` until the crossfade ends, so film minute 0 is the end of the transition and the film positions in the study's log need no correction. A timer ends the crossfade even when no surface is reading.
- The field is the womb generator's own function of the recorded seed, womb time, awake time and parameters, rendered once at boot, so two viewings from one seed see the same crossfade. Frames and samples stay in memory and are never written to disk.

The transition runs only when the mode is `playlist`, `transition_seconds` is above zero, the stage is embodied, and the configured `[perception_feed.womb]` parameters still match the recorded digest. Otherwise the programme starts at once. Boot logs the reason at info level for an unstaged, unborn or disabled case, and as a warning for a born being without a birth record or with changed womb parameters. The run manifest records `transition_seconds`, `transition_audio_fade_seconds` and `transition_planned` under `perception_feed`. The outcome is published on `perception.out` as content-free `perception.transition` events whose `phase` is `started`, `completed` or `abandoned` (an abandoned one carries a `reason` such as `first_frame_undecodable`), each with `transition_seconds`. The research event log records them.

## Settings

| Section | What it controls |
|---|---|
| `[perception_feed]` | `mode`, `seed`, and the gestation-to-films transition (`transition_seconds`, `transition_audio_fade_seconds`). |
| `[perception_feed.womb]` | The maternal heartbeat and state, the drive's bound (`external_drive_max_amplitude`), and `birth_transition_seconds`. |
| `[perception_feed.womb.video]` / `.audio` | The dim field, pulse depth and colour ramp; the soundscape's low-pass corner. |
| `[perception_feed.womb.readout]` | The readout period, the probe protocol, the entrainment test and the viability watch. The probe lengths' hard maxima are enforced in code. |
| `[developmental_stage]` | The gate's floors and cadence, `require_operator_ack_for_birth`, and the womb timings `womb_ready_retry_seconds`, `womb_check_seconds`, `womb_loss_after_seconds`, `womb_arm_timeout_seconds` and `womb_presence_window_seconds`. |
| `[developmental_stage.regulation_thresholds]` | The C1 thresholds. |
| `[soma]` | `self_rhythm_enabled`, `self_rhythm_step_hz`, `self_rhythm_eta`. |

For full defaults, see [Perception feed and sleep](../appendix-a-configuration/perception-and-sleep.md) and [Lifecycle, evaluation and research](../appendix-a-configuration/lifecycle-and-research.md).

## External womb

A Paracosmic body is planned to provide the gestational stimulus externally. Swapping providers changes configuration and leaves the gate unchanged. An external provider streams the stimulus through the perception seam and publishes `gestation.womb` with source `gestation` and payload `{provider, frame_index}` at least once a second, only while it is actually delivering, with an advancing `frame_index`.

The readiness readout runs only with the local womb, so until an external provider also supplies the maternal drive and the readout, a being gestating in it cannot pass the gate's regulation condition and is not born.
