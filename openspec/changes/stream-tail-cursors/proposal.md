## Why

The interoception module's sleep cursor starts at "0" (kaine/modules/interoception/module.py:248), so at every boot it replays the whole sleep history: each past `sleep.sleep.completed` calls `_fatigue.reset()` and `_regulation.reset()`, possibly after the checkpoint restore, and after a crash mid-sleep a replayed `sleep.sleep.started` without its completion leaves it believing it is asleep. #371 fixed the same cursor in the vision and audition modules only. A duplicate-work audit counted about 20 hand-written tail seeds.

## What Changes

- One shared helper seeds a stream cursor at the stream's tail at start. The interoception, vision and audition sleep consumers use it, and so do the other hand-written tail seeds where they mean the same thing.\n- Interoception no longer replays past sleeps at boot: fatigue and regulation keep their restored state, and the module is awake after a crash mid-sleep unless a sleep is actually running.\n- Consumers that must read history (backfills) are left as they are, and say so.

## Capabilities

### Modified Capabilities

- `interoception`: every module's stream consumer starts at the stream tail through one shared helper

## Impact

- stream-tail-cursors0
- Behaviour: stream-tail-cursors1
