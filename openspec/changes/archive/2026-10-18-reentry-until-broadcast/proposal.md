## Why

In the sixth test boot (main 7b5ed07c, `concern_reentry_s = 30`) the affect module published 237 re-entries at exact 30 s spacing, but only 36 (15%) were ever candidates on a broadcast tick; crossings reached 25% and affect state, vision and audition events about 49%. Silences of 141 to 262 s recurred seven times in an hour with curiosity and boredom at 0.83 to 0.90.

The cause is the publish phase. The module updates from `on_workspace`, right after a broadcast, and most updates are of that kind (about 5 per second against one per second from its own timer), so a due re-entry is usually published there and is read by the next cycle tick. That tick broadcasts only when the access rate exceeds half the processing rate (the access accumulator, `CycleEngine._advance_experiential`); otherwise its candidates are scored and discarded (paper 3.4, A.1). A replay of the boot's tick, broadcast, affect state and goal logs reproduces the losses (affect state 48.7% on broadcast ticks, goal-creating crossings 25%).

A current concern cues thought until the goal is met or dropped (Klinger 2013), and a cue the cycle discards has cued no thought, so the re-entry interval belongs between the times the concern is accessed. The paper (predictive-workspace-paper branch notes-reentry2, 3.5 and A.4) now says: while a goal is active and `D >= theta_D`, its drive event recurs, not as an alert, at intensity `D` each `P_Aff` until a broadcast accesses it, then `P_re` after that access.

## What Changes

- An active goal's drive event (its crossing, then each re-entry) stays pending until a broadcast accesses it: a coalition member of a broadcast that is not inhibited, with a score at or above the broadcast's `access_threshold`. The module checks this on every broadcast it receives.
- While pending, the event is republished (`affect.drive`, payload `{"drive", "value", "alert": false, "reentry": true}`, intensity `D`) on the module's own `P_Aff` timer updates, at most one copy per goal per update and only once the previous copy is at least `P_Aff / 2` old, so no unread copy is duplicated on the bus. A due re-entry is also published only on a timer update. Updates triggered by a broadcast never publish re-entries, since their events land on the following tick.
- After an access, the goal's next re-entry is due `P_re` later. Pending state stops on goal end (completed, abandoned, stalled, capped), on the sleep reset and on restore; nothing recurs while the drive is below threshold.
- Every published copy's entry id joins the drive entry ids (#533), so an intent about it is about a drive and the A.4 credit rule is unchanged.
- `concern_reentry_s = 0` keeps the module bit for bit identical to the build before re-entry (crossings only, no repeats, no access check).

The alternative of only publishing re-entries from the timer, without the repeat, leaves each event about a 49% chance and in the replay still gives six silences over 120 s per hour; repeating on every update, broadcast-triggered ones included, reaches the workspace but publishes about 6 copies per access, most of them into the same losing phase.

## Capabilities

### Modified Capabilities

- `affect`: a sustained concern's drive event recurs on the module's own updates until a broadcast accesses it, and the re-entry interval runs from that access.

## Impact

- `kaine/modules/affect/module.py`, `config/kaine.toml` (comment), `docs/09-modules/affect.md`, `tests/test_affect_concern_reentry.py`.
- Behaviour (replay of the sixth boot, 60.9 min main run): drive events reaching an accessed broadcast rise from 17% of concern episodes (15% measured) to 98%, at 50% of published copies and a median 0.8 s from publication; silences over 120 s fall from 9 (7 logged) to 0, longest gap 89 s.
