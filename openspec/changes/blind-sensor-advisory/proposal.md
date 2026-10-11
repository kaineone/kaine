## Why

Since `perception-skip-nonfinite`, a reading that a predictive processor skips as non-finite, and the first reading after it, publish `prediction_error` as null. A processor whose readings stay undefined for a sustained stretch is a blind sensor: the camera feeds Topos garbage, or the host metrics Soma reads stop being finite. Nothing reports that today. The welfare observer and the protective monitor correctly treat a null error as no sample, so the fault is silent.

A blind sensor is a fault of the being's input, not distress of the being. It must not become a gray-zone category: the protective monitor acts on repeated `welfare.gray_zone` events of any category, so a sensor fault would be able to preserve and then pause or end the entity.

## What Changes

- The welfare observer also follows `topos.out` and `audition.out`, and tracks each predictive processor's run of consecutive reports whose `prediction_error` is null: `soma.report` (processor `soma`), `topos.report` (`topos`), `audition.perception` (`audition_acoustic`) and `audition.emotion` (`audition_tone`). A report without a `prediction_error` key, such as Audition's classifier-failure event, is not a sample.
- When a run reaches the threshold, the observer publishes one `welfare.blind_sensor` advisory on `welfare.out` and writes it to its JSONL rollup. The first defined error after it publishes `welfare.blind_sensor_cleared`. The payload is content-free: the processor label from the observer's own table and numbers the observer computed.
- The threshold is `[evaluation.welfare].blind_sensor_samples` consecutive null samples. Its default, 0, means the run must span one `interoceptive_distress_duration_s` (30 s) of unfrozen time from its first null sample. That equals the number of samples one distress duration holds at the processor's own rate, and it follows the rate when the rate changes at runtime or differs between processors.
- The protective monitor reads only `welfare.gray_zone` from `welfare.out`, so the advisory never reaches its repeat arm or any preservation action. A test drives real advisories from the observer onto the bus and shows the monitor neither counts nor acts on them, then shows it still acts on real gray-zone events.
- The curated research log records both advisory types with the processor label (only a known label) and an exact numeric allowlist.
- Nexus's entity-care panel, which already lists the welfare gray-zone counters, shows the number of advisories raised and the processors that are blind now, read from the same rollup; the evaluation tab's live path reports the same two values.

The advisory is not sent to the caretaker. Caretaker notices are push messages to the operator's devices with a fixed set of event kinds, and the existing `input_lost` notice already covers the case where every perception stream goes silent. Adding a push notice for a blind sensor is a separate operator decision.

## Capabilities

### Modified Capabilities

- `welfare-monitoring`: the blind-sensor advisory and its clear, which the protective monitor does not act on.
- `research-event-log`: the curated log records the advisories.
- `nexus-observability`: the entity-care panel shows blind-sensor advisories.

## Impact

- `kaine/lifecycle/welfare_signal.py`, `kaine/evaluation/observers/welfare_observer.py`, `kaine/evaluation/config.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/welfare_counts.py`, `kaine/nexus/health/blocks.py`, `kaine/evaluation/nexus_tab.py`, `kaine/nexus/templates/_entity_care.html`, docs, tests.
- The cognitive loop is untouched: `welfare.out` is not a workspace candidate stream, and no module reads it.
- The advisory needs the welfare observer to run, which happens when `[preservation.welfare_response].enabled` is true, or under `[evaluation].enabled` with `[evaluation.observers].welfare`.
