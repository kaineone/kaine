# Resume releases the operator's own freeze; protective freezes need a named override

## Why
The cycle's freeze is a stack of holders: `operator`, `spot`, `welfare`, `preserve`, `gestation` and `programme_end`. Spot and preservation pop only their own entries. The Nexus "resume cycle" button, however, calls `unfreeze()`, which empties the whole stack. Any operator resume therefore also lifts a welfare-protective pause or a gestation freeze (taken when the womb is lost), usually without the operator knowing either was there. With Nexus open to the host, anything that can reach it can do the same.

The operator decided (2026-10-02) that resume releases only the operator's own freeze, and that welfare and gestation freezes need a separate, clearly labelled override that names what it overrides. Spot and preservation already release themselves.

Research impact: none for runs Nexus watches read-only (research runs). For operated entities, an operator resume no longer silently ends a welfare or gestation pause.

## What changes
- `POST /diagnostics/cycle/freeze` with `frozen: false` (the resume button) removes only `operator` entries (`stand_down(source="operator")`). If other holders remain, the cycle stays frozen and the response lists them.
- New `POST /diagnostics/cycle/override` with `{"sources": [...], "confirm": "<same names, comma-separated>"}` lifts only the named holders from the set that never release themselves: `welfare`, `gestation`, `programme_end`. `spot` and `preserve` are refused (they release themselves). A mismatched `confirm` is refused. Each override appends a content-free record (`at`, `sources`, `remaining`) to `state/cycle/override_audit.jsonl` and is logged at WARNING.
- The control snapshot (`GET /diagnostics/cycle/control`) includes the active `holders` (source and `frozen_at` only; reasons stay as they are today).
- The freeze panel shows which holders are active. When any non-operator holder remains after resume, it shows an "Override <names> freeze" button that needs a second confirming click naming the holders.
- `unfreeze()` remains for the cycle's own clean boot (a fresh start begins unfrozen); Nexus no longer calls it.

## Impact
- Code: `kaine/nexus/cycle_control.py`, `kaine/cycle/control_state.py` (an `override` helper that lifts named sources and writes the audit record), `kaine/nexus/templates/_diagnostics_sections.html`, `kaine/nexus/static/nexus.js`.
- Specs: `entity-preservation` (MODIFIED: who may lift a welfare pause), `nexus-dashboard` (ADDED).
- Docs: the Nexus chapter, day-to-day operation, preservation and security pages.
