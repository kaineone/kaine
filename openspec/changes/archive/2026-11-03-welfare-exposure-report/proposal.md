## Why

The only welfare datum from a test boot is boredom's indicator crossing at 2.7 awake hours and staying over its bar (paper §6.5). The first long run is now a single-entity development run: one entity develops and is grown continuously, with modules joining it one boot at a time through the study runner. In the first configuration nothing the entity does changes its stimulus, so each boot is a fixed exposure that the next may repeat. Each boot should therefore report each drive's deprivation share and open crossings as a preset welfare check with a stop rule, in place before the run starts, so that a stimulus that deprives the entity is seen after the first boot and not after the tenth.

The pieces exist but are not joined:

- the welfare observer writes cumulative `affect_welfare` records (deprivation shares, uncontrolled shares, open crossings, sleep-reset ends, negative valence, interest) to its sink, and a final one at stop;
- `welfare-indicator-response` adds indicator values and response records in the cycle-layer monitor;
- the study runner records each step's outcome and any welfare freeze, but no exposure figure, and starts the next step as soon as the previous one completes.

## What Changes

- At the end of every research run the cycle writes one content-free exposure record, `state/welfare/exposure.json`, bound to its run by `run_id` and the boot's start time. Indicator figures (largest value, crossings, rests requested, freezes placed, per A.4 indicator) come from the welfare monitor's cycle-layer evaluator, which is never restarted. Descriptive shares (deprivation, uncontrolled, open crossings, sleep-reset ends per deficit; negative valence; curiosity's interest) come from the welfare observer's tally, with the producer's restart count and the awake seconds it covered.
- The cycle deletes any existing exposure record at boot, before the gate, so a record from an earlier boot or a restored bundle can never stand for the current one.
- The record is plain JSON with mode 0600 and no content, so the study runner reads it without the state key.
- The runner copies the record into the step's record as `welfare_exposure`, and the analysis prints a per-step exposure table.
- Stop rule: the runner does not start the next step after a step whose exposure record is missing, unreadable, bound to another run, incomplete in coverage, or shows any indicator crossing, until the operator acknowledges it with `python -m kaine.research.ignition_study ack-welfare`. The acknowledgement records the operator's decision (continue, or stop) in the study record; it never edits the entity or its state.

## Capabilities

### New Capabilities

### Modified Capabilities

- `welfare-monitoring`: every research run ends with a bound, content-free exposure record, and a stale one is removed at boot.
- `module-ignition-study`: the step record carries the step's exposure; the run holds for review after a step with an indicator crossing or without a valid record.

## Impact

- Code: `kaine/cycle/__main__.py` (delete at boot, write at shutdown, from the monitor's evaluator and the producer's tally), `kaine/research/ignition_study/runner.py`, `__main__.py` (`ack-welfare`), `analysis.py`.
- Tests: the exposure writer, the boot-time removal, the runner's binding and coverage checks, the hold and acknowledgement, the analysis table.
- Docs: the study chapter, `docs/17-research-data/README.md`.
- Paper: §6.2 can say each boot's exposure is reported, §6.5 that the run holds for review after a boot whose indicators crossed.
