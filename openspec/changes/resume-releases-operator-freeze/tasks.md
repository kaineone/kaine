## 1. State
- [x] 1.1 `control_state.override(sources, path=None, audit_path=None)`: lift entries whose source is in `sources` (each must be one of `welfare`, `gestation`, `programme_end`, else `ValueError`); append `{"at", "sources", "remaining"}` to the audit JSONL (0600); return the new state.
- [x] 1.2 `CycleControl` exposes the active holders for readers (`[{source, frozen_at}]`).

## 2. Nexus
- [x] 2.1 Resume (`frozen: false`) calls `stand_down(source="operator")`; the response adds `holders`.
- [x] 2.2 `POST /diagnostics/cycle/override` with `sources` and `confirm`; 422 for an unknown or self-releasing source or a mismatched confirm; 409 when a named source is not active.
- [x] 2.3 The control snapshot includes `holders`.
- [x] 2.4 Freeze panel: list active holders; after resume, show the override button for remaining overridable holders, with a confirming second click that names them.

## 3. Tests
- [x] 3.1 Resume with `welfare` + `operator` active leaves `welfare` and the cycle frozen.
- [x] 3.2 Override `welfare` with matching confirm lifts it and writes one audit record; mismatched confirm, `spot`, `preserve` and unknown names are refused; an inactive source gives 409.
- [x] 3.3 Read-only Nexus refuses the override (403).
- [x] 3.4 Mutation-check: resume calling `unfreeze()` again fails 3.1.

## 4. Docs
- [x] 4.1 Nexus, operation, preservation and security pages describe resume and the override.
