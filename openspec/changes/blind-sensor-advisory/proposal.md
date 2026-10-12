## Why

Since `perception-skip-nonfinite`, a reading that a predictive processor skips as non-finite, and the first reading after it, publish `prediction_error` as null. A processor whose readings stay undefined for a sustained stretch is a blind sensor: the camera feeds the vision module garbage, or the host metrics the interoception module reads stop being finite. Nothing reports that today. The welfare observer and the protective monitor correctly treat a null error as no sample, so the fault is silent. A processor that stops publishing altogether is reported only in part: the caretaker's `input_lost` notice fires only when every perception stream goes quiet at once, and only when the caretaker is enabled for an unattended run, so one silent sensor among working ones goes unreported.

Both are faults of the entity's input, not distress of the entity. They must not become gray-zone categories: the protective monitor acts on repeated `welfare.gray_zone` events of any category, so a sensor fault would be able to preserve and then pause or end the entity.

## What Changes

- The welfare observer also follows `topos.out` and `audition.out`, read from their tail when it starts so earlier history is never replayed, and ignores any report older than its own start. It tracks each predictive processor's reports: `soma.report` (processor `soma`), `topos.report` (`topos`), `audition.perception` (`audition_acoustic`) and `audition.emotion` (`audition_tone`). `audition.transcription` is not a sample: it carries the same tone-path error as the `audition.emotion` event for the same utterance, so it would count each utterance twice, and it carries the transcript, which the observer has no reason to read.
- **Blind sensor.** When a processor's run of consecutive null `prediction_error` reports reaches the threshold, the observer publishes one `welfare.blind_sensor` advisory on `welfare.out` and writes it to its JSONL rollup; the first defined error after it publishes `welfare.blind_sensor_cleared`. A report without a `prediction_error` key, such as Audition's classifier-failure event, is not a sample. The threshold is `[evaluation.welfare].blind_sensor_samples` consecutive null samples. Its default, 0, means the run must span one `interoceptive_distress_duration_s` (30 s), which equals the number of samples one distress duration holds at the processor's own rate and follows the rate when it changes. The span is measured both on the observer's unfrozen read clock and between the reports' own timestamps, and both must reach the duration, so neither a lagging observer that reads a backlog at once nor a freeze can raise it early.
- **Silent sensor.** A tracked processor that has published at least once and then publishes nothing for one `interoceptive_distress_duration_s` of unfrozen time raises `welfare.sensor_silent`; its next report publishes `welfare.sensor_silent_cleared`. `soma`, `topos` and `audition_acoustic` are tracked. `audition_tone` is not: it reports only when speech is heard, so a quiet room is a normal reason for it to publish nothing. A processor never seen since the observer started is not reported, since it may simply be disabled.
- All four advisory payloads are content-free: the processor label from the observer's own table and numbers the observer computed.
- **Restart.** When the observer starts it writes a reset line to its rollup. Readers treat it as clearing every processor's blind and silent state, and the observer rebuilds the state from live reports.
- The protective monitor reads only `welfare.gray_zone` from `welfare.out`, so no advisory reaches its repeat arm or any preservation action. A test drives real blind and silence advisories from the observer onto the bus and shows the monitor neither counts nor acts on them, then shows it still acts on real gray-zone events.
- Tracking runs after the stream's own handler and is wrapped, so a tracking failure never skips the interoception module's distress handling.
- The curated research log records all four advisory types with the processor label (only a known label) and exact numeric allowlists.
- The dashboard's entity-care panel, which already lists the welfare gray-zone counters, shows the advisories raised since the observer's last start and the processors that are blind or silent now. It derives each processor's state from its latest advisory or clear after the latest reset, reading the whole rollup with no line window, and decrypts encrypted rollup lines. The evaluation tab's live path reports the same values.

The advisories are not sent to the caretaker as push notices. Caretaker notices have a fixed set of event kinds and no clear, and adding one is a separate operator decision.

## Capabilities

### Modified Capabilities

- `welfare-monitoring`: the blind-sensor and silent-sensor advisories and their clears, which the protective monitor does not act on.
- `research-event-log`: the curated log records the advisories.
- `nexus-observability`: the entity-care panel shows the sensor advisories.

## Impact

- `kaine/lifecycle/welfare_signal.py`, `kaine/evaluation/observers/welfare_observer.py`, `kaine/evaluation/config.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/welfare_counts.py`, `kaine/nexus/health/blocks.py`, `kaine/evaluation/nexus_tab.py`, `kaine/nexus/templates/_entity_care.html`, docs, tests.
- The cognitive loop is untouched: `welfare.out` is not a workspace candidate stream, and no module reads it.
- The advisories need the welfare observer to run, which happens when `[preservation.welfare_response].enabled` is true, or under `[evaluation].enabled` with `[evaluation.observers].welfare`.
