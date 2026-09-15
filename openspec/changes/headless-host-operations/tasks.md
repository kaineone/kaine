## 1. Runbook authoring

- [x] 1.1 Create `docs/deployment-headless-host.md` with a purpose header (dedicating a Linux host to a continuously-running, unattended KAINE instance, 24/7) and exactly this section structure: 1 Make the performance profile persist; 2 Enable remote access — and prove it works (blocking); 3 Install the Python tooling the installer needs; 4 Configure swap — an OOM safety valve, not a hot path; 5 Container runtime and reboot survival; 6 Switch to headless — only after step 2 was verified; 7 Reach the dashboard over the private network; plus a final 'Verification checklist: after a power cut'. The runbook contains no `## Requirements` section — normative requirements live only in the change's spec delta.
- [x] 1.2 State scope and portability in the purpose header: the procedure applies to any Linux host being dedicated to a 24/7 KAINE instance; host-specific commands appear only inside subsections explicitly labelled `Worked example — Jetson Orin Nano Super (JetPack)`; and KAINE does not require a Jetson — the dual-GPU x86_64 workstation path remains the default and is unaffected by this runbook.
- [x] 1.3 Author step 1 (Make the performance profile persist): state the persistence rule — a 24/7 host must make its performance profile PERSIST and verify it post-reboot, never merely set it once (normative requirements live only in the spec delta, not in this runbook); worked example: `nvpmodel -q` reports MAXN_SUPER (mode 2) while `/etc/nvpmodel.conf` line 216 reads `< PM_CONFIG DEFAULT=1 >` (modes: 0=15W, 1=25W, 2=MAXN_SUPER), so the next reboot silently drops the host to 25W with no error and no log line; fix by setting `DEFAULT=2`; verify after reboot with `nvpmodel -q`.
- [x] 1.4 Author step 2 (Enable remote access — and prove it works) and mark it BLOCKING: `sudo systemctl enable --now ssh`; verify `systemctl is-enabled ssh` reports `enabled` and `systemctl is-active ssh` reports `active`; verify a real login from a second device (key-based auth recommended); include an explicit warning that step 6 MUST NOT be executed until this gate passes, because reversing the order costs physical access and requires a monitor-and-keyboard recovery trip.
- [x] 1.5 Author step 3 (Install the Python tooling the installer needs): a venv creation probe (`python3 -m venv /tmp/kaine-venv-probe && rm -rf /tmp/kaine-venv-probe`) must succeed, noting Ubuntu splits `ensurepip` into `python3-venv` so `python3 -m venv --help` succeeding is NOT evidence creation works (remedy: `sudo apt install python3-venv python3-pip`); and a PEP 668 note that the system Python is externally managed, so all KAINE dependencies are installed inside the venv only.
- [x] 1.6 Author step 4 (Configure swap — an OOM safety valve, not a hot path): create a swapfile on the host's fastest persistent storage (worked example: 32 GB on NVMe with 854 GB free — `fallocate` (or `dd` on CoW filesystems such as btrfs/ZFS), `chmod 600`, `mkswap`, `swapon`, `/etc/fstab` entry) and set `vm.swappiness=10` via `/etc/sysctl.d/` (e.g. `/etc/sysctl.d/90-kaine-headless.conf`); state the reasoning — zram buys capacity by spending CPU AND RAM to compress pages, the wrong trade when RAM is the scarce resource and the goal is keeping model weights resident, and NVIDIA's standard zram advice assumes slow eMMC — and note zram remains correct where persistent storage is slow; verify with `swapon --show` and `sysctl vm.swappiness`.
- [x] 1.7 Author step 5 (Container runtime and reboot survival): confirm `podman --version` reports >= 4.4 (worked example: host ships with Docker only; Ubuntu 24.04 `sudo apt install podman`, candidate 4.9.3); `sudo loginctl enable-linger <user>` for the user that runs the quadlet services (deployed per `quadlet/README.md`; worked example: `erik`); verify `loginctl show-user <user>` reports `Linger=yes`; unattended-reboot test — reboot, do not log in locally, then over SSH compare each quadlet unit's `ExecMainStartTimestamp` (`systemctl --user show <unit> -p ExecMainStartTimestamp`) against the boot time (`uptime -s`) to prove units started at boot, not at first login; state that without linger, rootless user units stay down until a human logs in, which defeats a 24/7 host after any power cut.
- [x] 1.8 Author step 6 (Switch to headless — only after step 2 was verified), sequenced strictly after the step 2 gate: `sudo systemctl set-default multi-user.target`; disable the display manager (worked example: `sudo systemctl disable --now gdm3`); reboot; verify `systemctl get-default` reports `multi-user.target`, `systemctl is-active gdm3` reports `inactive`, and SSH login still succeeds; state the rationale (worked example: the graphical stack consumes ~2–3 GB of the 8 GB unified-memory budget).
- [x] 1.9 Author step 7 (Reach the dashboard over the private network): state the proxy-in rule — keep services bound to loopback and proxy inbound; never widen a bind to `0.0.0.0` (normative requirements live only in the spec delta, not in this runbook); worked example: Tailscale is installed and running (node `kaine-one`) with tailnet HTTPS certs provisioned (`CertDomains: ['kaine-one.beardie-bleak.ts.net']`), so `sudo tailscale serve --bg 8088` proxies the tailnet to the existing loopback bind with no change to `config/kaine.toml` (`[nexus] host = "127.0.0.1"`) or `quadlet/kaine-nexus.container` (`PublishPort=127.0.0.1:8088:8088`); note the MagicDNS name persists even when the node's 100.x address changes; verify from a different tailnet device.
- [x] 1.10 Author the privacy guidance inside step 7: states that serving the dashboard over a tailnet makes it reachable from every device on that tailnet; requires `[nexus] dev_content_override = false` — naming what it gates (raw message text, beliefs, memory bodies, internal speech, affect reasons) — and `conversation_enabled = false` unless deliberately changed; includes a config inspection step.
- [x] 1.11 Author the final 'Verification checklist: after a power cut': a single ordered checklist mirroring steps 1–7 in execution order, with the step 2 gate marked as blocking, each step carrying its verification command and expected output, serving as the runbook's dated verification record.

## 2. Documentation integration

- [ ] 2.1 Link the runbook from `docs/README.md` in the operations/runbooks index with a one-line description covering performance-profile persistence, SSH-first remote access before going headless, venv-based Python tooling, swap, linger-based reboot survival, and dashboard reachability over the private network.
- [ ] 2.2 Link the runbook from `docs/operations.md` where ongoing operation is discussed, noting it is host-generic with a Jetson worked example and does not alter the default dual-GPU x86_64 workstation path.
- [ ] 2.3 Confirm both links resolve: `grep -n "deployment-headless-host" docs/README.md docs/operations.md` finds both entries and the target file exists at `docs/deployment-headless-host.md`.

## 3. Quadlet README correction

- [ ] 3.1 In `quadlet/README.md`, qualify the "recommended production path ... reboot survival" claim so it states that rootless systemd user units start at boot only when linger is enabled (`sudo loginctl enable-linger <user>`), and add enable-linger plus the `Linger=yes` verification to the README's setup steps so the instructions match the claim.
- [ ] 3.2 Sweep for residual unqualified claims (`grep -rniE "reboot|survive|boot" quadlet/ docs/`) and correct any other statement implying rootless services start at boot without linger.

## 4. Verification: portable procedure framing

Normative requirements for the portable-procedure framing live in the `headless-host-operations` capability spec.

- [x] 4.1 Confirm the purpose header contains the any-Linux-host statement and the not-Jetson-required / workstation-unaffected statements (`grep -n "any Linux host\|does not require a Jetson" docs/deployment-headless-host.md`).
- [x] 4.2 Confirm every `nvpmodel` or JetPack mention in the runbook falls inside a subsection labelled `Worked example — Jetson Orin Nano Super (JetPack)` and none appears in generic steps.
- [x] 4.3 Confirm the change's diff touches only `docs/deployment-headless-host.md`, the `docs/README.md` and `docs/operations.md` links, `quadlet/README.md`, and the change's own openspec files — no edits to `config/kaine.toml`, `quadlet/*.container`, or x86_64 workstation docs.

## 5. Verification: SSH-before-headless ordering gate

Normative requirements for the SSH-before-headless ordering gate live in the `headless-host-operations` capability spec.

- [x] 5.1 Confirm step 2 contains the enable command, both status checks with expected outputs, the second-device login check, and the blocking warning about loss of physical access.
- [x] 5.2 Confirm step 6 is explicitly sequenced after the gate (its title states "only after step 2 was verified") and includes the target switch, display-manager disable, reboot, and post-reboot checks (`systemctl get-default` reports `multi-user.target`; `systemctl is-active gdm3` reports `inactive`; SSH login succeeds).
- [ ] 5.3 Execute the ordered sequence on the Jetson worked-example host and record dated evidence that the step 2 gate preceded the target switch and all post-reboot checks pass.

## 6. Verification: performance profile persistence

Normative requirements for performance-profile persistence live in the `headless-host-operations` capability spec.

- [x] 6.1 Confirm step 1 states the persistence rule, the worked-example specifics (line 216 `DEFAULT=1`; modes 0=15W, 1=25W, 2=MAXN_SUPER), the silent-failure description, and includes the post-reboot `nvpmodel -q` check in 'Verification checklist: after a power cut'.
- [ ] 6.2 On the Jetson worked-example host: set `DEFAULT=2` in `/etc/nvpmodel.conf`, reboot, and record `nvpmodel -q` output showing MAXN_SUPER.

## 7. Verification: reboot survival requires linger

Normative requirements for reboot survival via linger live in the `headless-host-operations` capability spec.

- [ ] 7.1 Confirm `quadlet/README.md`'s production-path claim is now conditioned on linger and its setup steps include `sudo loginctl enable-linger <user>` with the `Linger=yes` check.
- [x] 7.2 Confirm step 5 includes enable-linger, the `Linger=yes` check, and the unattended-reboot test, and that 'Verification checklist: after a power cut' includes it.
- [ ] 7.3 On the Jetson worked-example host: enable linger for `erik`, reboot, and record `loginctl show-user erik` reporting `Linger=yes` plus unit start timestamps near `uptime -s`.

## 8. Verification: host prerequisites

Normative requirements for host prerequisites live in the `headless-host-operations` capability spec.

- [x] 8.1 Confirm step 5 lists `podman --version` (>= 4.4) with its remedy and expected output, and step 3 lists the venv creation probe with expected outputs and states that `python3 -m venv --help` succeeding is not evidence that venv creation works on Ubuntu (ensurepip is split into `python3-venv`).
- [x] 8.2 Confirm step 3 states the PEP 668 constraint and directs all KAINE dependency installation into the venv (no system pip, no `--break-system-packages`).
- [x] 8.3 On the Jetson worked-example host: run the preflight, apply the remedies, and record `podman --version` (4.9.3) and a successful venv probe.

## 9. Verification: swap policy

Normative requirements for the swap policy live in the `headless-host-operations` capability spec.

- [x] 9.1 Confirm step 4 contains the full swapfile procedure, the `vm.swappiness=10` sysctl drop-in, the stated reasoning including the zram-on-slow-storage caveat, and the two verification commands.
- [ ] 9.2 On the Jetson worked-example host: after reboot, record `swapon --show` showing the NVMe swapfile and `sysctl vm.swappiness` reporting 10 (baseline was empty `swapon --show` and no zram unit).

## 10. Verification: dashboard reachability

Normative requirements for dashboard reachability live in the `headless-host-operations` capability spec.

- [x] 10.1 Confirm step 7 states the proxy-in rule (loopback preserved as defence in depth; never `0.0.0.0`), documents that the `config/kaine.toml` and `quadlet/kaine-nexus.container` binds are unchanged, and contains the Tailscale Serve worked example including the cert domain `kaine-one.beardie-bleak.ts.net` and the MagicDNS-stability note.
- [x] 10.2 Confirm no wildcard bind is introduced by this change: `grep -rn "0.0.0.0" config/ quadlet/` shows no new matches against the pre-change baseline.
- [x] 10.3 On the Jetson worked-example host: run `sudo tailscale serve --bg 8088`, then from a second tailnet device load `https://kaine-one.beardie-bleak.ts.net` and record that the dashboard renders.

## 11. Verification: privacy defaults

Normative requirements for privacy defaults live in the `headless-host-operations` capability spec.

- [x] 11.1 Confirm step 7's privacy guidance states the tailnet-wide exposure consequence, lists both settings with their required values, and enumerates the gated content categories.
- [x] 11.2 Confirm this change does not modify `config/kaine.toml` and that it still sets `dev_content_override = false` and `conversation_enabled = false` (`git diff` empty for the file; `grep -rn "dev_content_override\|conversation_enabled" config/` shows both false).

## 12. Traceability and validation

- [x] 12.1 Confirm every Requirement in sections 4–11 maps to at least one runbook step and one verification task above, and no verification task references a requirement absent from the change's spec delta.
- [x] 12.2 Run `openspec validate headless-host-operations --strict` and resolve all reported issues.

## 13. Headless host bring-up script

Normative requirements for the bring-up script live in the `headless-host-operations` capability spec.

- [ ] 13.1 Author `scripts/prepare-headless-host.sh` (`#!/usr/bin/env bash`, `set -euo pipefail`, `# SPDX-License-Identifier: LicenseRef-CAL-0.2` plus a copyright line matching the repo's existing scripts) with argument parsing — `--phase1` (default), `--phase2`, `--all`, `--dry-run`, an opt-in dashboard flag (e.g. `--serve-dashboard`), and a swap-size option (default 16G) — a per-step result recorder, and a final summary table listing every step with its OK / SKIPPED (reason) / FAILED (reason) outcome followed by the runbook's post-run verification commands, exiting non-zero if any step FAILED.
- [ ] 13.2 Implement the single-sudo-prompt contract: refuse to run when invoked as root (e.g. via `sudo scripts/prepare-headless-host.sh`) so the linger target is the unambiguous invoking user, perform exactly one up-front `sudo -v`, and keep the credential cache alive with a background refresh loop for the run's duration so no step prompts again.
- [ ] 13.3 Implement phase 1 (safe on a local console or over SSH) idempotently, each step detecting already-done state and reporting OK or SKIPPED (reason) instead of repeating work: Jetson-only performance-profile persistence (detect via `/etc/nv_tegra_release` or `/proc/device-tree/model`; flip the `/etc/nvpmodel.conf` `< PM_CONFIG DEFAULT=1 >` line to `DEFAULT=2`; report not-applicable and never fail on non-Jetson hosts), `systemctl enable --now ssh` verified via `is-enabled` = enabled and `is-active` = active, `apt-get install -y python3-venv python3-dev build-essential` degrading to a reported skip on non-apt hosts, the configurable-size `/swapfile` (fallocate, `chmod 600`, `mkswap`, `swapon`, `/etc/fstab` entry) guarded by existing-swap detection so an active swap is never duplicated or corrupted, `vm.swappiness=10` set live and persisted to `/etc/sysctl.d/99-kaine-swap.conf`, `apt-get install -y podman` with a >= 4.4 version check, and `loginctl enable-linger <invoking user>` verified via `Linger=yes`.
- [ ] 13.4 Implement phase 2 (the headless switch) behind the machine-checked gate: refuse to proceed unless `$SSH_CONNECTION` is set and refuse unless the ssh service is both enabled and active, then `systemctl set-default multi-user.target` and report that a reboot is required — the script never reboots the host; `--all` enforces the same gate before running phase 2.
- [ ] 13.5 Implement step 7 as opt-in: only when the dashboard flag is passed and tailscale is present and up, run `tailscale serve --bg 8088`; otherwise report the step SKIPPED with the reason (flag not given, tailscale absent, or tailscale down).
- [ ] 13.6 Implement `--dry-run` so every action is printed without being performed, with the phase 2 precondition checks still evaluated and reported so a dry run from a local console shows the refusal it would produce.
- [ ] 13.7 Run `shellcheck scripts/prepare-headless-host.sh` and resolve all reports so it passes cleanly.
- [ ] 13.8 Verify `--dry-run` on a representative host: every action is printed (including not-applicable and would-skip reports), no state changes occur (`systemctl get-default`, `swapon --show`, `loginctl show-user <user> -p Linger`, `/etc/fstab`, and `/etc/sysctl.d/99-kaine-swap.conf` unchanged), the summary table renders, and the exit code is 0 absent failures.
- [ ] 13.9 Verify idempotency: run the script twice back-to-back and confirm the second run reports each already-done step as OK or SKIPPED with a reason, creates no second swapfile, duplicates no `/etc/fstab` or sysctl drop-in entries, reports already-installed packages rather than reinstalling, prompts for the sudo password at most once, and exits 0.
- [ ] 13.10 Verify the phase 2 gate: from a local console (no `$SSH_CONNECTION`), confirm `--phase2` and `--all` refuse with a message naming the SSH precondition, exit non-zero, and leave `systemctl get-default` unchanged; then over SSH confirm the gate passes and the target switch proceeds, with the reboot still left to the operator.
- [ ] 13.11 Verify the skip paths on a non-Jetson host: the performance-profile step reports not-applicable without failing, non-apt and tailscale-absent environments degrade to clearly-reported SKIPPED outcomes, the run completes with exit 0 absent real failures, and no output implies KAINE requires a Jetson.
- [ ] 13.12 Link the script from `docs/deployment-headless-host.md`: a short note near the purpose header that `scripts/prepare-headless-host.sh` automates steps 1–7 with a single sudo prompt, that phase 2 requires an active SSH session (enforcing the step 2 gate as a machine check), and pointers to `--dry-run`, the phase flags, and the opt-in dashboard flag.