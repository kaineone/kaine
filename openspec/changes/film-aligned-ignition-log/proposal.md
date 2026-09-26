# Proposal — `film-aligned-ignition-log`

## Why

The module-ignition study compares, viewing by viewing, what reaches the entity's workspace while it watches the same programme. That comparison needs each broadcast placed at a point in the film. Two things prevent it today:

- **Nothing records where in the film a broadcast happened.** The playlist clock (`PlaylistClock` in `kaine/modules/topos/feed.py`) knows the item and offset, but only the item title and order reach the bus, and only when a Topos or Audition event is in the coalition. The trajectory recorder is off by default, stamps records with its own write time, and rebuilds each coalition member with `timestamp=now`, so members lose their own ids and times.
- **The film does not wait for the entity.** A cycle freeze closes capture, but the clock keeps running, so on resume the video jumps forward and the audio re-seeks: the frozen span of the film is skipped. Hypnos's replay window pauses the clock, but the pause is a single boolean. If a freeze and a replay overlap, the first to resume releases the other's pause.

Film position must never reach the entity: modules read the workspace broadcast from the bus (`kaine/modules/base.py`), so a position added to the broadcast payload would tell the entity where it is in the film. The stamp has to be taken in-process, at the cycle layer, and written only to the research record.

## What changes

- **Programme pauses are held per holder.** `PlaylistClock.pause(holder)` / `resume(holder)`: the clock is paused while any holder holds it, and elapsed time accumulates only while none does. Hypnos uses holder `hypnos`; the existing no-argument calls keep working as holder `default`.
- **A freeze pauses the programme.** While the cycle is paused, by any freeze holder, the playlist clock is held under holder `freeze`, so the film resumes where the entity left it.
- **An ignition log.** A cycle-layer observer, called in-process right after each successful workspace broadcast, writes one JSONL record per broadcast:
  - run id and sequence number;
  - tick index;
  - the broadcast's bus entry id;
  - wall and monotonic time of the broadcast;
  - the programme position at that instant: item index, order, title, offset in seconds, and whether the clock was paused;
  - the audio feed's own position, when it reports one, so drift between picture and sound is measurable;
  - salience scores and inhibition;
  - each coalition member's entry id, source, type, salience and original timestamp.

  No payloads are written, so no content is persisted. The log goes through the encrypting JSONL sink and ships disabled (`[ignition_log].enabled = false`). It is never on the bus and no module receives it.

## Impact

- Modified: `kaine/modules/topos/feed.py` (holder pauses), `kaine/modules/hypnos/module.py` (holder `hypnos`), `kaine/cycle/__main__.py` (freeze pause, observer wiring), `kaine/cycle/engine.py` (an optional broadcast observer).
- New: `kaine/cycle/ignition_log.py`, config section `[ignition_log]`.
- Default behaviour is unchanged apart from freezes now pausing the programme, which is a correctness fix for anyone using playlist mode.
