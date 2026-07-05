## 1. Config — `config/kaine.toml`

- [x] 1.1 Add `[spot.incident_log]` table beneath `[spot]` with `enabled = true` and `path = "state/cycle/incidents"`. Comment that retention purge is unconditionally disabled for this sink and that the block is dormant while `[spot].enabled = false`.

## 2. Config parsing — `kaine/cycle/spot.py`

- [x] 2.1 Add `IncidentLogConfig` dataclass (`enabled: bool`, `path: str`) with a `from_section` classmethod that validates known keys only (consistent with `SpotConfig.from_section`).
- [x] 2.2 Extend `SpotConfig` with `incident_log: IncidentLogConfig` field; parse the `incident_log` sub-table in `SpotConfig.from_section`.
- [x] 2.3 Add `poll_index: int = 0` counter to `Spot.__init__`; increment at the top of each `_poll_once` call.
- [x] 2.4 Add `incident_id: str | None = None` field to `_Incident`; generate a UUID4 on first detect (when `incident.incident_id` is None).

## 3. Exception capture — `kaine/cycle/spot.py`

- [x] 3.1 In `Spot.assess()`, at the point where `t.exception()` is currently read and discarded (line 144), capture the exception into a per-task local variable. Return it alongside the `"dead"` / `"hung"` / `"alive"` assessment via a named tuple or dataclass `AssessResult(state, exception_repr)`.
- [x] 3.2 Update all callers of `assess()` in `_poll_once` to unpack `AssessResult` and pass `exception_repr` into the detect record.

## 4. Health metrics — `kaine/cycle/spot.py`

- [x] 4.1 In `_poll_once`, after calling `self.assess(module)`, call `module.health()` when the state is not `"alive"` and store `heartbeat_age_s`, `tasks_failed`, `tasks_total` for use in the detect record. Guard with `try/except` (health is documented as never-raises, but Spot must never crash on its own instrumentation).

## 5. Path scrubbing — `kaine/cycle/spot.py`

- [x] 5.1 Implement `_scrub_path(text: str) -> str` — a regex substitution that replaces absolute path tokens (`/home/...`, `/root/...`, `/Users/...`, `C:\...`) with `<PATH>`. Emit `log.debug` when any substitution occurs. Used only on `exception_repr` before write.

## 6. Incident log sink lifecycle — `kaine/cycle/spot.py`

- [x] 6.1 In `Spot.__init__`, if `config.incident_log.enabled`, construct an `AsyncJsonlSink` with `dir_path=config.incident_log.path`, `name="incidents"`, `retention_days=0`. Store as `self._incident_sink`.
- [x] 6.2 In `Spot.run()`, call `await self._incident_sink.start()` before the poll loop (if sink is not None).
- [x] 6.3 In `Spot.run()`, after the loop exits (whether by stop_event or exception), call `await self._incident_sink.stop()` to flush pending writes.

## 7. `_write_incident_record` helper — `kaine/cycle/spot.py`

- [x] 7.1 Implement `async def _write_incident_record(self, record: dict) -> None` that adds `ts` (ISO-8601 UTC) if not present, then calls `await self._incident_sink.write(record)`. If `self._incident_sink` is None, returns immediately (no-op). Guards the write with a bare `except Exception` and `log.warning` so a broken sink never crashes Spot.

## 8. Transition record emission — `kaine/cycle/spot.py`

- [x] 8.1 **detect**: emit record in `_poll_once` after `assess()` returns non-alive and after `incident_id` is assigned. Fields: `ts`, `incident_id`, `module`, `transition="detect"`, `fault_class`, `exception_repr` (scrubbed), `heartbeat_age_s`, `tasks_failed`, `tasks_total`, `poll_index`.
- [x] 8.2 **freeze**: emit record immediately after `control_state.freeze(...)` call in `_poll_once`. Fields: `ts`, `incident_id`, `module`, `transition="freeze"`, `reason` (the string passed to freeze), `source="spot"`, `fault_type` (the fault_class from detect).
- [x] 8.3 **snapshot**: emit record after the `_snapshot(...)` call in `_poll_once`. Wrap the `ForkManager.snapshot()` call to measure `duration_ms`, read `byte_size` from the returned snapshot bundle path stat, and collect `modules_serialize_errored` from the snapshot metadata. Fields: `ts`, `incident_id`, `module`, `transition="snapshot"`, `snapshot_id`, `byte_size`, `modules_serialized_ok`, `modules_serialize_errored`, `encrypted` (StateEncryptor.enabled), `duration_ms`, `label`.
- [x] 8.4 **restart**: emit record after `_restart_module(name)` and the post-restart `assess()` call. One record per attempt. Fields: `ts`, `incident_id`, `module`, `transition="restart"`, `attempt`, `max_attempts`, `path` ("light"|"heavy"), `outcome` ("recovered"|"failed"), `latency_ms`, `last_good_restored`, `post_assess`.
- [x] 8.5 **escalate**: emit record in `_escalate()` after `escalation_state.write_escalation()` completes and before `_on_halt` is called. Fields: `ts`, `incident_id`, `module`, `transition="escalate"`, `attempts`, `final_snapshot_id`, `outcome="halted"`.

## 9. `AsyncJsonlSink` no-purge guard — `kaine/evaluation/sink.py`

- [x] 9.1 In `_enforce_retention`, verify the existing `if self._retention_days <= 0` short-circuit is correct (it is, per current code), and add a comment making explicit that `retention_days=0` is the "no-purge" signal used by the incident log. No logic change required; this is a documentation + awareness task to prevent a future refactor from silently removing the guard.

## 10. Tests

- [x] 10.1 `tests/test_spot_incident_log.py`: construct a minimal Spot with a fake module that fails; assert that all five transition records appear in the sink's output. Check `incident_id` is shared, `ts` is ISO-8601 UTC, `fault_class` matches the simulated fault, and `exception_repr` contains `<PATH>` instead of any real path.
- [x] 10.2 `tests/test_spot_incident_log.py`: hung module detect record — assert `exception_repr` is `null`.
- [x] 10.3 `tests/test_spot_incident_log.py`: escalation path — assert escalate record appears with `outcome="halted"` and `final_snapshot_id` matches the snapshot record's `snapshot_id`.
- [x] 10.4 `tests/test_async_jsonl_sink.py`: assert `_enforce_retention` with `retention_days=0` leaves files older than 30 days on disk.
- [x] 10.5 `tests/test_kaine_toml.py`: assert `[spot.incident_log].enabled` is `true` and `[spot].enabled` is `false` in the shipped TOML.
- [x] 10.6 Full test suite green before PR.

## 11. Spot module-level doc update — `kaine/cycle/spot.py`

- [x] 11.1 Update the module docstring to mention the incident log: append a paragraph describing the durable JSONL record written at each lifecycle transition and noting that it survives reboots, unlike `escalation.json`.
