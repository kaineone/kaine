# Each boot refusal gets its own exit code

## Why

The researcher docs promise a distinct exit code for each boot gate, but two codes were shared:
- `5` meant both "the research safety net is not live" and "the organ content gate found a mute organ".
- `3` meant both "the evaluation config is invalid" and "individuation is misconfigured".

An operator or a process wrapper reading the exit status could not tell those refusals apart. The mapping of the boot path for the phase refactor (W5) found both.

## What changes

- The organ content gate exits with `ORGAN_GATE_REFUSED_EXIT = 9`.
- The individuation refusal exits with `INDIVIDUATION_REFUSED_EXIT = 10`.
- The researcher exit-code table and the first-boot guide list the new codes.
- A test checks that every boot refusal code is distinct, that the cycle never returns a literal 5, and that every code is in the table.

## Impact

- **Behaviour:** the mute-organ refusal now exits 9 instead of 5, and the individuation refusal 10 instead of 3. Nothing in the repository, its scripts or its units keys on those values.
- **Research:** none. No study is running.
