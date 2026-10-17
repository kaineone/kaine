## Why

A test boot of main 3ce0bbfa (2026-10-16) found three affect defects.

1. The affective reset at the end of sleep removes the active goals but publishes nothing, so a goal can vanish from the bus record without an end event. The paper's A.11 item 4 says the reset clears the active goals; the clearing is right, the silence is not.
2. A drive's crossing latch (`_has_fired`) is not saved with the module state. After a revive every drive already above its threshold fires again and creates a duplicate goal, so every branch revived from a seed starts with a burst of drive alerts and goals that never happened in the seed.
3. Fear fired 37 times within 61 s at a pleasantness of -0.001 while valence was positive. The fear rule tests `pleasantness < 0` with no margin and does not read familiarity. Sander, Grandjean and Scherer (2005, Table 3) predict fear from low intrinsic pleasantness, low familiarity, an anticipated obstruction and very low power.

## What Changes

- `affective_reset()` publishes one `affect.goal` event per goal it clears, with `action: "cleared"`, `reason: "sleep_reset"`, the goal's `id`, `description` and `drive`. A cleared goal counts as neither completed nor abandoned, so the ledger's outcome counts that feed coping do not change (paper A.4: "A sleep reset counts as neither").
- The module state saves each drive's crossing latch as `drive_fired`, and a restore sets it back. State written before this change has no latch; a restore then infers it as fired when the drive value is at or above its threshold, since a drive there must already have fired.
- `classify()` returns fear only when coping is available (relevant content, a nonzero goal score), pleasantness is at or below -0.3, novelty is above 0.3 (low familiarity) and coping is at or below -0.3 (very low power). The novelty cut-off is the disgust rule's. The goal score does not gate fear: Table 3 pairs fear's Obstruct with high outcome probability and very high urgency, an anticipated obstruction (a threat), while KAINE's goal score measures present conduciveness and its obstruction term (paper A.4) is retrospective, so it cannot represent an anticipated obstruction. The rule order is unchanged.

## Capabilities

### Modified Capabilities

- `affect`: the affective reset reports the goals it clears, the drive crossing latch survives a restore, and fear follows Table 3's fear profile.

## Impact

- `kaine/modules/affect/module.py`, `kaine/modules/affect/drives.py`, `kaine/modules/affect/appraisal.py`, `docs/09-modules/affect.md`, affect tests.
- Behaviour: a sleep reset leaves an `affect.goal` record for each cleared goal; a revive no longer re-fires drives that had already fired; fear needs low pleasantness and novel content, so near-neutral input no longer flickers into fear. Fear stays reachable: it needs relevant content and a poor own-response record (power at or below 0.35), which a dominant drive whose crossings mostly ended without the entity's response, or a ledger with mostly abandoned goals, supplies (the test boot's ledger had coping -0.83). A gate on an obstructed goal would have made it practically unreachable, because a goal's obstruction scales with its expected relief, which starts at the drive's own success ratio, so a record poor enough for very low coping caps the obstruction near 0.175 under the default `goal_likelihood_fall` of 0.5.
