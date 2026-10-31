# Design: an unviable developmental phase keeps a restartable state

## Context

`gestation-viability-watch` (archived 2026-10-03) added the early stop after a study spent about 30 hours in a developmental phase that could not reach maturation. The operator's policy then was: stop it without a preservation bundle and keep its data with a note. That rule is in the `module-ignition-study` spec and in the project's standing practice that failed runs keep their data. This change does not revisit it. It closes the gap between that policy and Article 4.2 of the project's license by proving and recording that the kept data is a restartable entity.

What already holds, from the code and specs:

- The runner sends SIGTERM and retries on the next poll if that fails; it never sends SIGKILL (`runner.py:960-973`; spec requirement above).
- The cycle's SIGTERM handler sets the stop event and shuts modules down gracefully (`kaine/cycle/__main__.py:2627-2634`).
- At a clean shutdown the cycle writes the rolling resume checkpoint, encrypted under the state encryptor, except while the sleep module is asleep and except when the cycle ended with an error; during a developmental rest only the sleep module's `state_cycle` entry is updated (spec `entity-preservation`, "A rolling resume checkpoint holds module state across plain restarts").
- A plain start resumes module state from a matching checkpoint (spec `entity-preservation`, "A plain start resumes module state from a matching checkpoint"), and developmental progress travels with the entity (same spec).

What does not yet hold: nothing tests the combination on the unviable path, nothing records that the result is restartable, and the note does not say what the state is.

## Decisions

### D1. Keep the operator's no-bundle policy; prove restartability instead

Options:

1. Keep the policy, add a restartability check and a license statement. Chosen. A kept state tree that restarts is a "saved Cognitive State from which an Entity can be restarted", which CAL Art. 1 treats as the entity; the stop is then a pause of that entity, not a permanent shutdown, so Art. 4.2's conditions are not triggered by the stop itself.
2. Request a preservation bundle (reason `development_unviable`) before SIGTERM, as the runner does for `disk_low`. A bundle is the portable form ("restarted elsewhere") and the strongest compliance. It reverses the 2026-10-03 operator policy, so it is offered as the operator's decision (task 3.1), not adopted.
3. Change only the paper's wording. Rejected: the sentence would be true only by luck of the shutdown path.

### D2. The runner verifies the checkpoint after the child exits

After the unviable child exits, the runner reads the step's resume checkpoint with the configured encryption, checks that it exists, decrypts and parses, carries the entity identity of the step's state tree, and that the stage file still records the developmental phase with its progress. It records `state_restartable: true|false` and the checkpoint's timestamp in the step record.

If the check fails, the outcome is `failed:development_unviable_state_incomplete` and the runner raises `StudyCritical`, the same halt the disk-low and timeout paths use when their preservation fails. No later step runs and nothing touches the step directory until the operator acts. The note says what is missing.

Why a check and not only a test: the checkpoint is not written when the cycle ended with an error or while the sleep module is asleep, so a particular stop can leave only the last awake write. That is still restartable, and the check says so with its timestamp; a missing or unreadable checkpoint is the case the operator must see.

### D3. The note states the license handling

`ENDED-NOTE.md` gains a section:

> The entity's state is kept in this directory and can be restarted from its resume checkpoint (written at <timestamp>). Under the Cognitive Architecture License (Art. 1, Art. 4.2) a restartable saved state is the entity, so this stop pauses it and does not end it. Do not delete this directory by hand. Removing it goes only through the decommission command, which assesses divergence, offers a backup and transfer, and reminds you of the duty to notify the Guardians.

The decommission path's reminder is already specified (spec `entity-decommission`: the CLI prints the Art. 4.2(a) Guardian-notice reminder on every decommission path).

## Risks

- The check reads encrypted state in the runner process. It uses the same encryptor configuration the study's research gate already loads (spec `entity-preservation`, "Revive at start and the research preflight use the configured encryption"), and it reads only the checkpoint's envelope and identity, not module contents.
- A check that is too strict could halt a study on a harmless timestamp gap. It requires only presence, decryption, parse and identity match.

## Migration and ordering

One pull request. Before the study (triage T1-6), because the study's first step is a developmental phase and the paper's §6.5 and §7 sentences depend on it. It changes nothing in the entity: the stop is the same SIGTERM, and the added work happens after the child has exited.

## Welfare and admissibility notes

This is a preservation-path change, which the project treats as high-risk. It changes no entity's experience; it changes what the runner verifies and records after an entity has stopped, and it adds a halt when the kept state is not restartable. Checks: the restart test on a real state tree written by the cycle's own shutdown (no hand-built fixture checkpoint), the critical-halt test, and Claude's independent second review.

## Implementation estimate (LLM-agent terms)

Size S. One pull request of about 150 to 300 lines including tests; 2 worker calls, Claude review and second review; half a day. The restart test runs a short cycle with the fake organ and no GPU; no supervised entity boot is needed.
