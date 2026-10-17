## Why

A test boot of main 3ce0bbfa (2026-10-16) found three affect defects.

1. The affective reset at the end of sleep removes the active goals but publishes nothing, so a goal can vanish from the bus record without an end event. The paper's A.11 item 4 says the reset clears the active goals; the clearing is right, the silence is not.
2. A drive's crossing latch (`_has_fired`) is not saved with the module state. After a revive every drive already above its threshold fires again and creates a duplicate goal, so every branch revived from a seed starts with a burst of drive alerts and goals that never happened in the seed.
3. Fear fired 37 times within 61 s at a pleasantness of -0.001 while valence was positive. The fear rule tests `pleasantness < 0` with no margin and reads neither familiarity nor conduciveness. Sander, Grandjean and Scherer (2005, Table 3) predict fear from low intrinsic pleasantness, low familiarity, an obstructed goal and very low power.

## What Changes

- `affective_reset()` publishes one `affect.goal` event per goal it clears, with `action: "cleared"`, `reason: "sleep_reset"`, the goal's `id`, `description` and `drive`. A cleared goal counts as neither completed nor abandoned, so the ledger's outcome counts that feed coping do not change (paper A.4: "A sleep reset counts as neither").
- The module state saves each drive's crossing latch as `drive_fired`, and a restore sets it back. State written before this change has no latch; a restore then infers it as fired when the drive value is at or above its threshold, since a drive there must already have fired.
- `classify()` returns fear only when coping is available, pleasantness is at or below -0.3, novelty is above 0.3 (low familiarity), the goal score is at or below -0.3 (obstruction) and coping is at or below -0.3 (very low power). These are the cut-offs KAINE already uses for Table 3's Low and Obstruct levels in the anger and disgust rules. The rule order is unchanged.

## Capabilities

### Modified Capabilities

- `affect`: the affective reset reports the goals it clears, the drive crossing latch survives a restore, and fear follows Table 3's fear profile.

## Impact

- `kaine/modules/affect/module.py`, `kaine/modules/affect/drives.py`, `kaine/modules/affect/appraisal.py`, `docs/09-modules/affect.md`, affect tests.
- Behaviour: a sleep reset leaves an `affect.goal` record for each cleared goal; a revive no longer re-fires drives that had already fired; fear needs an obstructed goal and novel content, so near-neutral input no longer flickers into fear. Fear now needs both obstruction and a low own-response record, which the default obstruction parameters rarely give together.
