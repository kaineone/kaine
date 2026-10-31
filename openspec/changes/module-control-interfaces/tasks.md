## 1. Phase 1: declare (behaviour-neutral; may merge before the study's launch image)

- [ ] 1.1 Re-derive the coupling table in design.md from the code at the branch point (grep and AST over `kaine/boot/` and `kaine/cycle/`), and correct the table where it differs.
- [ ] 1.2 `kaine/boot/couplings.py`: one record per coupling with kind, caller, callee, method, protocol and reason; the protocols in the same module.
- [ ] 1.3 `ArousalSource` protocol; the workspace state modulator, vision and audition receive it instead of the affect module or a lambda over `dimensional_state()`. Test: `tests/test_arousal_source_parity.py` (a recorded tick sequence gives identical gains and apertures before and after).
- [ ] 1.4 `tests/test_control_coupling_inventory.py`: undeclared calls, non-literal `getattr` on registry objects, and stale records all fail with the call site named.
- [ ] 1.5 Generated interfaces page under `docs/08-cognitive-cycle/` with a docs check that fails when it is out of date; links from `docs/09-modules/affect.md` and `sleep.md`.
- [ ] 1.6 A replacement-module test: a minimal affect module implementing only the declared protocols and a conforming `affect.state` runs a tick (`tests/test_replacement_module_protocols.py`).

## 2. Phase 2: the affective reset as a command (after the module-addition study; welfare second review)

- [ ] 2.1 Sleep publishes `sleep.affective_reset.requested`, waits for `affect.affective_reset.done` with `[sleep].affective_reset_timeout_s`; the registry no longer passes the affect object to sleep. Tests: extend `tests/test_sleep_module.py` (acknowledged, timed out, cancelled sleep).
- [ ] 2.2 Affect consumes the request once per id and acknowledges. Tests: extend `tests/test_affect_module.py` (duplicate id runs once; reset during a supervisor restart is acknowledged after the restart or times out cleanly).
- [ ] 2.3 Offline replay on recorded sleeps: post-sleep affect state from the method path and the command path match exactly. Record under `docs/records/validation/affective-reset-command/`.
- [ ] 2.4 Inventory record for the reset moves from `command` (direct) to the bus; pin test updated.

## 3. Phase 3: payload contracts

- [ ] 3.1 Contract models beside each producer for every published event type; producers' tests validate emitted payloads (`tests/test_payload_contracts_producers.py`).
- [ ] 3.2 Consumer field declarations for the workspace scorer, action selection, research-event observer, welfare observer and every module consumer; `tests/test_payload_contracts.py` cross-checks them.
- [ ] 3.3 `[bus].validate_payloads` (`off` default, `warn`, `enforce`) in `kaine/bus/client.py` and config validation. Tests: extend `tests/test_bus_client.py`.
- [ ] 3.4 Measure publish latency under `warn` and `enforce` on the reference host; record it, so any later paper wording that says "validated" can cite the cost.
- [ ] 3.5 `openspec validate module-control-interfaces --strict`.

## 4. Follow-up (separate change)

- [ ] 4.1 Propose moving sleep's episodic-memory, world-model and sequence-reset commands to command events once `world-model-content-prediction` and the memory workstream have settled those modules' interfaces.
