# Proposal — `film-end-preserve`

## Why

When a playlist ends, the entity is left awake with no senses. `PlaylistClock.locate()` returns an index past the last item. The video source then returns empty reads forever (Topos logs a capture failure every interval), and the audio producer thread exits. The entity keeps running with no input at all. The unattended gate already refuses playlist mode for this reason ("a playlist runs out, leaving the entity without input").

For the module-ignition study, the end of the programme is also the end of a viewing: the entity should be preserved and stopped there, so the next step can revive it with one more module.

## What changes

- **The cycle notices the end of the programme.** A cycle-layer watcher checks the shared playlist clock every second. When the clock has started, is not paused, and has run past its last item, the programme has ended.
- **It then preserves and stops the entity.** It writes one operator-style preserve request, with reason `programme end` and stop set. The preserve-request watcher (`operator-revive-and-preserve`) then freezes the entity, preserves it and stops it. The runner and the operator read the usual result file.
- **If that preservation fails, the entity is frozen, not left senseless.** The watcher reads the result. On `ok: false`, it pushes a freeze under its own holder, `programme_end`, logs at CRITICAL and notifies the caretaker when one is configured. The operator then decides: fix the cause and preserve again, or unfreeze.
- The end is handled once per start.

## Depends on

- `operator-revive-and-preserve` (the preserve-request watcher and its result file).

## Impact

- New: `kaine/cycle/programme_end.py`; wiring in `kaine/cycle/__main__.py` when a shared playlist clock exists.
- Playlist runs now end with a preserved, stopped entity instead of a senseless running one. Other perception modes are unaffected.
