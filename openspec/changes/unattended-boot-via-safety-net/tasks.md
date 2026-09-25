## 0. Prerequisites

The operator chose on 2026-09-25 to build now. The code ships opt-in and inert; 0.1 and 0.2 gate *enabling* the unattended unit for a real entity, not building it.

- [ ] 0.1 Before enabling on a real entity: the research phase has ended, confirmed by the operator.
- [ ] 0.2 Before enabling on a real entity: Spot has run enabled on supervised boots; at least one injected module failure was handled end to end (detect, freeze, snapshot, restart, release, incident record) and one escalation drill completed; the operator has reviewed the incident logs and signed off.
- [ ] 0.3 Before section 7: the quadlet units no longer hard-code `%h/projects/kaine` (change `quadlet-install`), so the unattended unit does not inherit that path.
- [x] 0.4 Until every condition is built, an unattended boot refuses and names each unbuilt condition; no partial gate can admit a boot.

## 1. Mode selection

- [x] 1.1 Resolve `unattended` from `KAINE_CYCLE_UNATTENDED=1` or `[cycle].supervision_mode = "unattended"` in `kaine/cycle/__main__.py`, env over config; validate the config key's allowed values.
- [x] 1.2 Refuse with exit 1 before any gate when more than one mode selector is active (operator-present flag, research selection, unattended selection).
- [x] 1.3 Dispatch: research → research gate (exit 5, unchanged); unattended → unattended gate (exit 6); otherwise operator-present (exit 2, unchanged).
- [x] 1.4 Unit tests: env-only, config-only, env over config, each conflicting pair, default path unchanged.
- [ ] 1.5 Test that an unattended boot initializes no experiment registry or admissibility machinery.

## 2. Shared net (conditions 1–5)

- [x] 2.1 Extract the five-condition evaluator from `kaine/cycle/research_gate.py` into a shared function; the research gate keeps its messages and exit code.
- [x] 2.2 Existing research-gate tests pass unmodified.

## 3. Spot selftest (condition 6)

- [x] 3.1 Add the config checks: enabled, `max_restart_attempts >= 1`, escalation path writable, incident log writable (canary append, then removed).
- [x] 3.2 Add the Spot selftest (`kaine/cycle/spot_selftest.py`; Spot gains injectable control and escalation paths): scratch Spot from the same `[spot]` section, synthetic probe module, induced failure, bounded window (default 10 s, configurable), scratch directory removed in every outcome.
- [x] 3.3 Distinct reasons: "not enabled", "no restart ladder", "escalation path not writable", "incident log not writable", and the failing selftest step or "timed out".
- [x] 3.4 Tests: healthy pass; each config failure; freeze step broken; restart step broken; timeout; no entity module imported (import-hook assertion); scratch directory gone afterwards.
- [x] 3.5 In unattended mode, watch Spot's supervision task; on exit other than shutdown, run Spot's escalation (the caretaker notice for it is task 4.9). Tests for unattended (escalates) and operator-present (unchanged).

## 4. Caretaker notifier (condition 7)

- [ ] 4.1 `[caretaker]` config: `install_label`, `channels` (`desktop`, `http` with URL and optional token name), `reminder_interval_s` (default 14400, minimum 900), `input_loss_after_s` (default 60); validation rejects unknown keys and public HTTP destinations.
- [ ] 4.2 Desktop channel over the session D-Bus (freedesktop Notifications); accepted means a notification id is returned.
- [ ] 4.3 HTTP channel: resolve the host at send time and refuse unless every resolved address is loopback, RFC 1918, `fc00::/7` or `100.64.0.0/10`; connect to the checked address while keeping the hostname for TLS verification; token from `config/secrets.toml`; accepted means 2xx; short timeout.
- [ ] 4.4 Content-free notice builder with a fixed field set (install label, time, event kind, condition results, Nexus address); a test asserts the field set and that no entity content can reach it.
- [ ] 4.5 Gate condition 7: sent last, only when 1–6 and 8 passed; passes if at least one channel accepts; the refusal names each channel and its error.
- [ ] 4.6 Best-effort refusal notice on exit 6 that never changes the exit code.
- [ ] 4.7 Reminders until acknowledged; unacknowledged starts never alter the entity.
- [ ] 4.8 Nexus: standing banner while unacknowledged; acknowledge POST behind the operator session; acknowledgement written to the event log; tests for auth, banner and reminder stop.
- [ ] 4.9 Running notices: Spot escalation, supervision lost, welfare-protective response, input loss, and a boot that fails after admission; failed sends are logged and never stop the entity.
- [ ] 4.10 Tests: no channel configured; all channels fail; one of two accepts; public address refused at config time; hostname resolving to a public address refused at send time; token never logged.

## 5. Input check (condition 8)

- [ ] 5.1 Config check: mode in `live`/`seeded`/`screen`, and `topos` or `audition` enabled; reasons "no input" (off), "playlist ends" (playlist), "no perceiving module".
- [ ] 5.2 Reuse `kaine.preboot.check_perception` for `seeded` and `screen`.
- [ ] 5.3 Add a live-device probe: open the configured camera and microphone, read one frame and one block, release, drop the data; nothing written.
- [ ] 5.4 Input-loss watcher during unattended runs, notifying after `input_loss_after_s` without stopping the entity.
- [ ] 5.5 Tests: each refusal reason; live device absent; the probe writes nothing (filesystem write recorder from `tests/zero_persistence.py`); input-loss notice sent and entity still running.

## 6. Exit code and refusal output

- [x] 6.1 Confirm exit 6 is unused, then add `UNATTENDED_GATE_EXIT_CODE = 6` beside the existing gate constants.
- [ ] 6.2 Refusal output: one `N: name — reason` line per failed condition on stderr; results also written to the boot journal and, when logging is active, the event log.
- [x] 6.3 Refusal matrix tests: each of 1–8 broken alone → exit 6 naming exactly that condition; all broken → all named.
- [x] 6.4 Regression tests: research failure → 5 with its old message; operator-present failure → 2 with its old message.
- [x] 6.5 Test that no skip, force or override switch lets a failing unattended boot through.

## 7. Opt-in unit file

- [ ] 7.1 Add `quadlet/kaine-cycle-unattended.container`: `KAINE_CYCLE_UNATTENDED=1`, `[Install] WantedBy=default.target`, `Conflicts=kaine-cycle.service`, `Restart=no`, same mounts and dependencies as the shipped unit plus the session bus socket for the desktop channel; header comment explains the gate and that power-loss restarts need an `http` channel.
- [ ] 7.2 Leave `quadlet/kaine-cycle.container` unchanged; a packaging test asserts it has no `[Install]` and no unattended selector.
- [ ] 7.3 A packaging test asserts the install scripts never copy or enable the unattended unit.
- [ ] 7.4 Run `systemd-analyze --user verify` on the generated units when systemd is available in the test environment.

## 8. Documentation

- [x] 8.1 `docs/for-researchers.md`: add the exit-6 row to the refusal table; rows 2 and 5 unchanged.
- [ ] 8.2 `docs/operations.md`: an "Unattended starts" section — when to use it, the eight conditions, setting up a caretaker channel (desktop, self-hosted HTTP), acknowledging in Nexus, enabling the opt-in unit, and what a refusal looks like.
- [ ] 8.3 Every page that lists `KAINE_CYCLE_*` variables or exit codes includes `KAINE_CYCLE_UNATTENDED` and exit 6.
- [ ] 8.4 A docs-consistency test asserts rows 2, 5 and 6 exist in the refusal table and rows 2 and 5 match their previous text.

## 9. End-to-end acceptance

- [ ] 9.1 Healthy fixture install in unattended mode: all eight conditions pass, a start notice reaches a local test endpoint, the cycle starts, no research machinery initializes.
- [ ] 9.2 Each condition broken alone on the fixture: exit 6, the condition named, a refusal notice sent, the entity loop never starts.
- [ ] 9.3 Research and operator-present boots behave exactly as before.
