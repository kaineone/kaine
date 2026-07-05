# Tasks — freeze-run-annotation

## 1. Spec
- [x] 1.1 Author `proposal.md`.
- [x] 1.2 Author `specs/spot-supervisor/spec.md` (ADDED requirements + scenarios).

## 2. Spot publishes spot.incident
- [x] 2.1 Add `tick_index_provider` parameter to `Spot.__init__` (optional
  callable; default `None`).
- [x] 2.2 Add `_publish_incident(record)` helper that copies the allowlisted
  operational fields from a transition record, adds `poll_index` (always) and
  `tick_index` (when the provider yields one), scrubs free-text via
  `scrub_paths`, and publishes a `spot.incident` event via `_publish`.
- [x] 2.3 Emit `spot.incident` at detect, freeze, snapshot, restart, escalate —
  IN ADDITION to the unchanged `spot.status` / `spot.log` and the unchanged
  durable incident_log writes.

## 3. Tick↔poll bridge
- [x] 3.1 Wire a `tick_index_provider=lambda: cycle.tick_index` into the Spot
  construction in `kaine/cycle/__main__.py`.

## 4. Research observer captures spot.incident
- [x] 4.1 Align the `spot.incident` taxonomy entry's allowed fields with the
  real incident_log field names (incident_id, transition, module, fault_class,
  freeze reason/duration, snapshot id/size, restart path/outcome/latency/restore,
  escalate outcome, poll_index, tick_index).
- [x] 4.2 Confirm the `spot.incident.*` prefix match still routes to that entry.

## 5. Tests
- [x] 5.1 `tests/test_spot_incident_annotation.py`: spot.incident published per
  transition with the right fields; spot.status/spot.log still published; tick +
  poll position present; path scrubbing.
- [x] 5.2 Extend `tests/test_research_event_log.py`: research observer captures
  spot.incident into a record with incident_id; run_id present when a run context
  is set (set + reset in the test); paths scrubbed.

## 6. Validate
- [x] 6.1 `openspec validate freeze-run-annotation --strict` passes.
- [x] 6.2 `pytest -k "spot or incident or research_event"` green.
