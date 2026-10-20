# A.7 entrainment validation at the 12-hour band span (2026-10-20)

## What was run

The archived harness of the earned-entrainment change (`openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/validation/proto_r.py`) and its archived run specifications (`runs/valF_v2_main.json`, `valC_true.json`, `valF_v3_controls.json`, `valC_controls.json`, `valF_v4_specificity.json`), 96 simulated hours each, on this branch's code with `[perception_feed.stimulus_source.hearing].maturation_seconds = 43200`. `validation/runval.py` runs the harness unchanged on the current classes: it maps the harness's pre-rename module, class and clock-method names onto `stimulus_source_drive`, `stimulus_source_signal`, `StimulusSourceParams` and `stimulus_source_seconds`, reading the old names from the rename table in `kaine/legacy_names.py`. `validation/rep3.py` counts replicated passes (three consecutive passing withdrawals), the criterion the paper reports.

The self-rhythm's drive is the real `MaternalDriveProvider`, which reads the heartbeat phase alone; the hearing band filters the stimulus audio only, so the band span is not an input of this harness. The re-run therefore checks that the validation still holds on the current classes with the new span in force, and the expected result is the archived one.

## Result against the paper's stated outcomes (A.7)

| Paper's outcome | Result | Holds |
| --- | --- | --- |
| All 10 seeds entrain at 70 bpm, typically by 14 hours | All 10 pass with replication; first replicated pass 12.5 to 15.5 h (median 13.75 h); withdrawn frequency 1.16 to 1.17 Hz against a 1.17 Hz beat | yes |
| Each rate from 60 to 80 bpm tracks its own heartbeat and locks in 3 to 48 hours | 60 bpm 3.0 to 7.5 h, 66 bpm 5.5 to 7.5 h, 72 bpm 16.0 to 19.5 h, 80 bpm 41.0 to 47.5 h; withdrawn frequency 0.98 to 0.99, 1.10, 1.20 and 1.32 to 1.34 Hz against beats of 1.00, 1.10, 1.20 and 1.33 Hz | yes |
| No control passes: no maternal drive, a jittered beat, no plasticity | Never a single pass in 96 h (no drive, jittered beat, eta 0 three times, eta 0 at drive scale 1) | yes |
| Six pairs scored against another heartbeat: single withdrawals pass by chance in 2.6 to 10 percent, never three in a row | Never three in a row; single passes 4.2, 10.0, 2.6, 3.2, 4.7 and 5.8 percent | yes |

These are the archived figures: 70 bpm first replicated pass 12.5 to 15.5 h with a median of about 14 h, the controls never passing, and foreign-pair single passes of 2.6 to 10 percent.
