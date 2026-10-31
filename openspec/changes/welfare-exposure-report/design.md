## Context

- The pre-run exposure work has three parts: (a) this report, deprivation shares and open crossings per boot as a preset welfare check with a stop rule; (b) the stimulus and the stir (changes `developmental-stimulus-progress` and `developmental-stir`); (c) a stimulus-control act, an operator decision for later.
- Scope (operator decision 2026-10-31): the module-ignition study becomes a single-entity development run, with no three-arm ablation and no pilot boots. The study runner still drives it step by step; each step is one boot of the same entity. The welfare net gates every boot.
- The welfare observer's `AffectWelfareTally` already computes the cumulative shares and counts (`2026-10-28-welfare-open-crossings`), and the observer writes a final `affect_welfare` record when it stops. Its sink is an encrypted JSONL stream in the evaluation logs, not a per-run file the study runner reads. The cycle supervises the producer and restarts a dead one (`_supervise_welfare_producer` in `kaine/cycle/__main__.py`), and a rebuilt producer starts a fresh tally, so the tally can cover only part of a run.
- `welfare-indicator-response` adds the live indicators in the cycle-layer monitor, which is not restarted, the rest and freeze records, and the caretaker notices. Its spans restart at every boot, so a rest given in one step does not count toward the next step's second stage; the hold here closes that gap.
- The study runner (`kaine/research/ignition_study/runner.py`) halts on any failed outcome and surfaces a welfare freeze without lifting it (module-ignition-study spec, "The runner surfaces a welfare freeze and never lifts it"). A completed step lets the next one start. The runner knows each step's `run_id`.

## Decisions

### D1. One exposure record per run, written by the cycle

At shutdown the cycle writes `state/welfare/exposure.json`, atomically with mode 0600:

- `run_id` and `boot_started_at`, binding the record to this boot;
- from the welfare monitor's evaluator: per A.4 indicator the largest value, the number of crossings, rests requested and freezes placed;
- from the producer's tally: awake seconds; per deficit the deprivation share, uncontrolled share, open crossings and sleep-reset ends; the negative-valence share; curiosity's interest share; and `producer_restarts` and `covered_awake_seconds`, the awake seconds the current tally covers, beside the monitor's own awake-seconds count.

Indicator figures come from the monitor because it is never restarted, so they cover the whole boot. Shares come from the tally because they are the published record format; their coverage is stated.

Alternative considered: the runner reads the observer's JSONL sink. Rejected: the sink is a rolling, encrypted stream shared with other records, and the runner would need the evaluation layer's reader and the state key.

### D2. A stale record never stands for a fresh one

The cycle deletes any `state/welfare/exposure.json` at boot, before the gates run. A record restored from a bundle, or left by an earlier attempt of a retried step, is therefore gone before the entity runs. The runner, independently, accepts a record only when its `run_id` equals the step's run id and its `boot_started_at` is after the step's start. Either check alone closes the case; both together mean a crashed boot that never wrote its record cannot be mistaken for a clean one.

### D3. Plain, content-free JSON

The record holds numbers, booleans and labels from the fixed indicator and drive tables only, under the observer's content contract. It is not encrypted, so the runner reads it without the state key; mode 0600 limits it to the operator account. Encrypting it would make every record unreadable to the runner and hold every step, or move the state key into the runner.

### D4. What counts as a reason to hold

The runner holds before the next step when the step's exposure record is missing, unreadable, bound to another run or boot (fail closed), when its share coverage is incomplete (`producer_restarts > 0` or `covered_awake_seconds` below the monitor's awake seconds by more than one affect summary interval), or when it shows at least one indicator crossing (a rest requested or a freeze placed). A freeze already halts the run through the existing welfare outcome; the new case is a boot in which the net rested the entity and the entity recovered. Under CAL Article 4.7 every crossing is flagged for human review; the hold makes the review happen before the entity is booted again, and it closes the gap left by the indicator spans restarting at every boot.

Alternatives considered:
- Hold only on a freeze. Rejected: the net would then rest the entity once per boot, quietly, for as many boots as the run has.
- A numeric exposure bar (for example a deprivation share above some value across a whole boot). Rejected for now: the indicator bars are the project's preset welfare bars (A.4, Table A1), and a second set of bars without an anchor would be retuned the first time it fires.

### D5. The acknowledgement

`python -m kaine.research.ignition_study ack-welfare --step <line>/<k> --decision continue|stop` writes a content-free acknowledgement (time, step and decision, with no name) into the study record. `continue` releases the hold; `stop` ends the run's line and leaves its preservations in place. It never edits an entity's state. The runner's `status` shows a pending hold and the command to answer it.

### D6. Other research runs

Every research run writes the record, so the validation boot has it too. Planned-test pilots are not part of the development run; if a publication-grade study is designed later, it can read the same record.

## Risks

- A hold after every boot would slow the run to the operator's response time. That would itself be the finding: the stimulus deprives the entity.
- The developmental phase is the first step and the one most likely to hold (`welfare-indicator-response` D9).

## Migration and ordering

- After `welfare-indicator-response` (it reads the monitor's indicator counts). Before the development run's first boot.
- Independent of `research-gate-supervisor`, the organ change and `workspace-continuous-competition` (on hold). `developmental-stir`, if built, writes its stir counts into this record and lands after it.
- Critical path (LLM-agent implementation): about 4 hours for code and tests, about 1 hour for review. Not on the run's longest path.

## Welfare and admissibility notes

- Measurement and a hold between boots; nothing changes inside a running entity, so admissibility is unaffected.
- The hold is a review point, not an automatic decision: the person notified decides, as §6.5 says for a freeze.
