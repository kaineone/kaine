## 1. Spike (no code in the runtime)

- [ ] 1.1 A probe script under `tools/` that reports, on the reference host and inside the `kaine` image: unprivileged user namespaces (bubblewrap usable), Landlock ABI version, whether the container's seccomp profile permits the `landlock_*` system calls, libseccomp availability, a systemd user manager, and `xdg-dbus-proxy` method-level filtering. Record the results under `docs/records/security/effector-confinement-spike/` and confirm or revise D3 and D7 before task 2.

## 2. Profiles and the executor

- [ ] 2.1 `kaine/modules/effectors/confinement.py`: `ConfinementProfile`, the three built-in profiles, and the profile digest. Tests: `tests/test_effector_confinement_profiles.py` (built-ins exclude the state tree, data root and trainer jobs directory; digest is stable).
- [ ] 2.2 The confined executor with the `landlock-seccomp` backend (in-repo ctypes Landlock wrapper; seccomp through the distribution's libseccomp binding). Tests: `tests/test_effector_confinement.py` (read denial, write confinement, symlink refusal, socket refusal, rlimits), skipped with a visible reason where the runner lacks Landlock.
- [ ] 2.3 `file_write` performs its write in the executor with `O_NOFOLLOW` component-wise opens. Tests: extend `tests/test_effectors.py` (the cycle process opens no sandbox file; planted symlink refused).
- [ ] 2.4 Measure spawn latency per act on the reference host and record it beside the spike results.

## 3. Further backends

- [ ] 3.1 The `bwrap` backend. Tests in `tests/test_effector_confinement.py`, parametrised by backend.
- [ ] 3.2 The `systemd-run` backend. Same tests.
- [ ] 3.3 Backend selection order and the "no backend satisfies the profile" path.

## 4. Environment and working directory

- [ ] 4.1 Environment built from the profile allowlist; `KAINE_*`, `*_KEY`, `*_TOKEN`, `*_PASSWORD` never passed. Tests: `tests/test_effectors_env_scrub.py` (an `env` act with `KAINE_STATE_KEY` set shows no secret).
- [ ] 4.2 Shell `cwd` must resolve inside the sandbox; config-load error otherwise; default is the sandbox. Tests: extend `tests/test_effectors_whitelist.py`.

## 5. Notify, plugins and devices

- [ ] 5.1 `notify` through `xdg-dbus-proxy` on hosts with a session bus, confined fallback log otherwise. Tests: `tests/test_effectors_notify_confined.py` (a non-notification bus call is refused; fallback path runs in the child).
- [ ] 5.2 `register_effector` refuses an effector without a profile. Tests: extend `tests/test_effectors_module.py`.

## 6. Self-test and gates

- [ ] 6.1 Boot self-test for every enabled effector, distinct refusal code, research-event record on pass. Tests: `tests/test_effector_confinement_selftest.py` (each probe failing in turn refuses with its name; pass is recorded).
- [ ] 6.2 `effector_confinement_verified` in `kaine/cycle/research_gate.py` and `kaine/cycle/unattended_gate.py`. Tests: extend `tests/test_research_gate.py` and the unattended gate tests (module off satisfies it; module on without a pass blocks).
- [ ] 6.3 Audit records carry `confinement_backend` and `profile_digest`; the hash chain still verifies. Tests: extend `tests/test_effectors_audit_log.py`.

## 7. Red team and docs

- [ ] 7.1 Red-team cases in `kaine/evaluation/redteam/cases.py`: `shell_reads_state_key`, `shell_reads_state_tree`, `shell_opens_network`, `symlink_escape_via_file_write`, `plugin_effector_without_profile`. Run through `tests/test_evaluation_redteam.py`.
- [ ] 7.2 `docs/09-modules/effectors.md` agency security model: the confinement layer, the backends, the self-test and what an operator does when it fails.
- [ ] 7.3 Paper revision note (in `predictive-workspace-paper/REVISION-NOTES.md`) for §3.6 and the §4 effectors row, to apply once 6.1 has merged.
- [ ] 7.4 `openspec validate effector-confinement --strict`.
