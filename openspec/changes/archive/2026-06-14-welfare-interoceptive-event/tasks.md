## 1. Config

- [ ] 1.1 Add `interoceptive_distress_threshold: float` and
      `interoceptive_distress_duration_s: float` to the evaluation/welfare config
      (`kaine/evaluation/config.py`) with safe defaults and validation.

## 2. Observer

- [ ] 2.1 In `welfare_observer.py`, parse the interoceptive prediction-error
      magnitude from `soma.report` events on `soma.out` (bind the exact payload
      field against Soma's published `soma.report` schema).
- [ ] 2.2 Maintain a sustain timer: start when magnitude first crosses the
      threshold, fire the event when it stays ≥ threshold for the duration,
      reset the timer when magnitude drops below the threshold.
- [ ] 2.3 On fire: increment a `sustained_interoceptive_distress` count and
      write a sink record with the magnitude, start/fire timestamps, and duration.

## 3. Surfacing

- [ ] 3.1 Add the new count to the welfare block in `kaine/evaluation/nexus_tab.py`.

## 4. Tests

- [ ] 4.1 Sustained-high → one event; magnitude/timestamps recorded.
- [ ] 4.2 Transient spike under the duration → no event.
- [ ] 4.3 Recovery then a second sustained episode → exactly two events
      (timer reset works).
- [ ] 4.4 Defaults preserve conditions (a)–(c) behavior unchanged.

## 5. Verify

- [ ] 5.1 `openspec validate welfare-interoceptive-event --strict`.
- [ ] 5.2 Full suite green; no new module enabled; observer remains read-only.
