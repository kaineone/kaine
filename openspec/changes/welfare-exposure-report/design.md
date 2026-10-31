## Context

- The pre-study exposure work has three parts: (a) this report, deprivation shares and open crossings per viewing as a preset welfare check with a stop rule; (b) the developmental stir (change `developmental-stir`); (c) a stimulus-control act, an operator decision for after the study.
- The welfare observer's `AffectWelfareTally` already computes the cumulative shares and counts (`2026-10-28-welfare-open-crossings`), and the observer writes a final `affect_welfare` record when it stops. Its sink is an encrypted JSONL stream in the evaluation logs, not a per-run file the study runner reads.
- `welfare-indicator-response` adds the live indicators, the rest and freeze records, and the caretaker notices.
- The study runner (`kaine/research/ignition_study/runner.py`) halts on any failed outcome and surfaces a welfare freeze without lifting it (module-ignition-study spec, "The runner surfaces a welfare freeze and never lifts it"). A completed step lets the next one start.
- Each study step is one run and one viewing, so a per-run record is a per-viewing record.

## Decisions

### D1. One exposure record per run, written by the cycle

At shutdown the cycle writes `state/welfare/exposure.json` from the welfare producer's tally snapshot and the welfare monitor's indicator counts, after the observer's final record. It is plain JSON with numbers and fixed labels only (the observer's content contract), written atomically with mode 0600, and encrypted when state encryption is on, as other state files are.

Alternative considered: the runner reads the observer's JSONL sink. Rejected: the sink is a rolling stream shared with other records, and the runner would need the evaluation layer's reader.

### D2. What counts as a reason to hold

The runner holds before the next step when the step's exposure record is missing or unreadable (fail closed), or when it shows at least one indicator crossing (a rest requested or a freeze placed). A freeze already halts the study through the existing welfare outcome; the new case is a viewing in which the net rested the entity and the entity then recovered. Under CAL Article 4.7 every crossing is flagged for human review; the hold makes the review happen before the same programme is shown again.

Alternatives considered:
- Hold only on a freeze. Rejected: the net would then rest the entity once per viewing, quietly, for as many viewings as the study has.
- A numeric exposure bar (for example a deprivation share above some value across a whole viewing). Rejected for now: the indicator bars are the project's preset welfare bars (A.4, Table A1), and a second set of bars without an anchor would be retuned the first time it fires.

### D3. The acknowledgement

`python -m kaine.research.ignition_study ack-welfare --step <line>/<k> --decision continue|stop-line` writes a content-free acknowledgement (time, step and decision, with no name) into the study record. `continue` releases the hold; `stop-line` ends that line and leaves its preservations in place. It never edits an entity's state. The runner's `status` shows a pending hold and the command to answer it.

### D4. Pilots and the validation boot

Every research run writes the record, so the validation boot and the planned test's pilots have it too. The calibration tool lists each pilot's record next to its statistics and does not use it for any setting. The pilots' stop rule is stated in the preregistration with the other pilot rules.

## Risks

- A hold after every viewing would slow the study to the operator's response time. That would itself be the finding: the programme deprives the entity.
- The cumulative shares mix the developmental stimulus and the films only in the seed step, which has its own record.

## Migration and ordering

- After `welfare-indicator-response` (it reads the indicator counts). Before the study's first step.
- Independent of `workspace-continuous-competition`, `research-gate-supervisor` and the organ change.
- Critical path (LLM-agent implementation): about 3 hours for code and tests, about 1 hour for review. Not on the study's longest path.

## Welfare and admissibility notes

- Measurement and a hold between runs; nothing changes inside a running entity, so admissibility is unaffected.
- The hold is a review point, not an automatic decision: the person notified decides, as §6.5 says for a freeze.
