# A gestation that cannot reach birth is stopped early, and its data is kept with a note

## Why
The 2026-10-01 module-ignition study spent about 30 hours in a gestation that could never reach birth. Only the 96 h budget would have ended it, and then the study would have halted on a failed step. The operator asked for a watcher that catches this early and stops the run. Their policy for an entity that does not complete gestation: stop it without a preservation bundle, and keep its data with a note on the issue.

The earned-entrainment change (`self-rhythm-earned-entrainment`) publishes the numbers behind entrainment at each withdrawal: PLV, surrogate maximum, withdrawn frequency and frequency pull. Its offline validation shows how viable and unviable gestations differ:
- **Viable** (60–80 bpm, 12 seeds): frequency pull rises steadily from the start. Even the slowest (80 bpm) reaches a median pull of 0.19–0.23 by 18–24 h and 0.47–0.52 by 36–48 h. The first replicated pass comes at 3–48 h.
- **Unviable** (no plasticity, no drive, full drive without plasticity, jittered beat): pull stays flat at or below 0.08 with no upward trend.

Research impact: **behaviour (study procedure).** A gestation judged unviable ends early with outcome `failed:gestation_unviable`, instead of running to its budget.

## What changes
- **Verdict.** The gestation owner keeps each withdrawal's entrainment numbers and judges viability after every withdrawal. The rules are evaluated on un-paused lived (subjective) time, excluding sleep and freezes, as in the validation runs; thresholds are config keys with these validated defaults:
  - **R0, measurement missing:** after 6 h, no withdrawal has produced a conclusive entrainment measurement. Something structural is wrong; this is what happened in the 2026-10-01 module-ignition study.
  - **R1, no learning:** at 24 h, with no replicated pass, the median pull over the last 12 h is below 0.12 and its trend is not rising (slope ≤ 0.002 per hour).
  - **R2, learning too slow:** at 48 h, with no replicated pass, the median pull over the last 12 h is below 0.3.
  - **R3, deadline:** at 60 h, no replicated pass.
  - Scored against all 55 offline validation conditions (`validation/viability_rules.py`), no viable gestation is flagged, and every dead one is flagged at 24–27 h. R3 leaves about 12 h of margin over the slowest viable case (80 bpm, 41–48 h).
- **Publication.** On the first unviable verdict, the owner publishes `gestation.viability` on `gestation.out` and writes `state/lifecycle/gestation_viability.json`, with the rule, the lived time and the evidence. The verdict actuates nothing in the entity; it is a measurement, like the readout.
- **The study runner** polls that file during a gestation step. On an unviable verdict it:
  - stops the cycle with a graceful SIGTERM, with no preservation request (operator policy);
  - records `failed:gestation_unviable` with the evidence;
  - writes `ENDED-NOTE.md` into the step directory (the issue, the rule, the evidence, and where the measurement is documented);
  - halts the study for the operator.

  Nothing is deleted.
- **A single switch,** `[perception_feed.womb.readout].viability_watch` (default on), turns the watcher off for experiments that need the full budget.
