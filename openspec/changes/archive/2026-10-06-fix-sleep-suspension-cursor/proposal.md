# Sleep suspension reaches Chronos and Topos

## Why

Chronos and Topos are meant to stop adapting their forward models while the entity sleeps. Each learns about sleep by following `hypnos.out` for `hypnos.sleep.started` and `hypnos.sleep.completed`. Both start that cursor at the literal `"$"` and read with a non-blocking `XREAD`. A non-blocking read from `"$"` never returns anything, so the cursor never moves and neither module ever sees a sleep event. As a result, every run so far kept training Chronos's forward head and Topos's forward model through sleep.

Audition hit the same defect while gaining sleep suspension (#371), and fixed only its own loop by seeding the cursor from the stream tail. The bus still accepts the call that cannot work, so the next consumer can write the same bug.

## What changes

- **The bus refuses the read that cannot work.** `read_entries`, `read` and `read_entries_block` raise `ValueError` for a `"$"` cursor when no block time is given, and the message names the stream and points to `last_entry_id`. A blocking read from `"$"`, which Redis serves correctly, is unchanged.
- **Every consumer starts from the stream tail.**
  - Chronos and Topos seed their `hypnos.out` cursor from `bus.last_entry_id` in `initialize`, before their loops start.
  - Audition's private tail helper is replaced by the same bus call.
- **The sweep.** Every cursor under `kaine/` that starts at `"$"` was checked:
  - the module workspace cursor, Eidolon's speech cursors, Chronos's user-input cursors and the Nexus bridge already resolve `"$"` first;
  - the workspace subscribers resolve it inside `subscribe_workspace`;
  - only the two `hypnos.out` cursors were broken.

## Impact

- Code: `kaine/bus/client.py`, `kaine/modules/chronos/module.py`, `kaine/modules/topos/module.py`, `kaine/modules/audition/module.py`.
- **Research impact.** Every earlier run trained Chronos's forward head (when it was on) and Topos's forward model during sleep. From this change on, both hold still while the entity sleeps, as designed. Forward-model prediction-error baselines from earlier runs are not comparable.
