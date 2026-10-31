## Why

The only welfare datum from a test boot is boredom's indicator crossing at 2.7 awake hours and staying over its bar (paper §6.5). In the first configuration nothing the entity does changes its stimulus after the developmental phase, so the four-film programme of the module-ignition study is a fixed exposure that every viewing repeats. Each run should therefore report each drive's deprivation share and open crossings as a preset welfare check with a stop rule, in place before the study, so that a programme that deprives the entity is seen after the first viewing and not after the twentieth.

The pieces exist but are not joined:

- the welfare observer writes cumulative `affect_welfare` records (deprivation shares, uncontrolled shares, open crossings, sleep-reset ends, negative valence, interest) to its sink, and a final one at stop;
- `welfare-indicator-response` adds indicator values and response records;
- the study runner records each step's outcome and any welfare freeze, but no exposure figure, and starts the next step as soon as the previous one completes.

## What Changes

- At the end of every research run the cycle writes one content-free exposure record, `state/welfare/exposure.json`: awake seconds; per deficit the deprivation share, uncontrolled share, open crossings and sleep-reset ends; the negative-valence share; curiosity's interest share; and per A.4 indicator the largest value reached, the number of crossings, the rests requested and the freezes placed. A run that cannot write it logs the failure at error level.
- The study runner copies the record into the step's record as `welfare_exposure`, and the analysis prints a per-viewing exposure table beside the ignition measures.
- Stop rule: the runner does not start the next step after a step whose exposure record is missing or unreadable, or shows any indicator crossing, until the operator acknowledges it with `python -m kaine.research.ignition_study ack-welfare`. The acknowledgement records the operator's decision (continue, or stop the line) in the study record; it never edits the entity or its state.
- The calibration tool lists each pilot run's exposure record beside its statistics, and the preregistration states the stop rule.

## Capabilities

### New Capabilities

### Modified Capabilities

- `welfare-monitoring`: every research run ends with an exposure record.
- `module-ignition-study`: the step record carries the viewing's exposure; the study holds for review after a viewing with an indicator crossing.

## Impact

- Code: `kaine/cycle/__main__.py` (write at shutdown, from the welfare observer's tally and the monitor's indicator counts), `kaine/research/ignition_study/runner.py`, `__main__.py` (`ack-welfare`), `analysis.py`, `kaine/experiment/calibrate.py` (listing only).
- Tests: the exposure writer, the runner's hold and acknowledgement, the analysis table.
- Docs: the study chapter, `docs/17-research-data/README.md`.
- Paper: §6.2 can say each viewing's exposure is reported, §6.5 that the study holds for review after a viewing whose indicators crossed.
