#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2025 KAINE contributors
#
# prepare-headless-host.sh - one-shot automation for
# docs/deployment-headless-host.md (dedicating a Linux host to a 24/7
# KAINE instance).
#
# Design notes:
#   * Idempotent. Every step detects the already-done state and reports it
#     instead of repeating work; re-running is always safe.
#   * One sudo prompt. Credentials are validated once up front and kept
#     alive by a background keep-alive; no step prompts on its own. Run the
#     script as the normal user (never `sudo script.sh`) so the lingering
#     target user is unambiguous.
#   * Two phases. Phase 1 (default) only does things that cannot lock
#     anyone out. Phase 2 flips the default systemd target to
#     multi-user.target and therefore refuses to run unless the session is
#     already over SSH ($SSH_CONNECTION is set) AND the ssh unit is both
#     enabled and active. Running over SSH is itself the proof the
#     runbook's step-2 human gate asks for - checked by the machine rather
#     than trusted to the operator.
#   * No reboot, ever. The script reports that a reboot is required; the
#     operator does it, deliberately, from the SSH session that proves
#     access works.
#   * Portable. Non-Jetson and non-apt hosts degrade to clearly-reported
#     SKIPPED steps; KAINE does not require a Jetson.

set -euo pipefail

readonly SCRIPT_NAME="${0##*/}"
readonly PODMAN_MIN="4.4"
readonly SWAPFILE="/swapfile"
readonly SWAP_SYSCTL_CONF="/etc/sysctl.d/99-kaine-swap.conf"

PHASE="1"
DRY_RUN=0
SWAP_SIZE="16G"
SERVE_NEXUS=0
ANY_FAILED=0
REBOOT_REQUIRED=0
SUDO_KEEPALIVE_PID=""
SSH_UNIT=""
TARGET_USER=""

declare -a SUMMARY_STEPS=() SUMMARY_RESULTS=() SUMMARY_NOTES=()
declare -a PHASE2_PROBLEMS=()

die() {
    printf '%s: error: %s\n' "$SCRIPT_NAME" "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
prepare-headless-host.sh - automate docs/deployment-headless-host.md

Dedicates a Linux host to a 24/7 KAINE instance. Run it as the normal
user (NOT under sudo); it prompts for sudo once and keeps the credentials
alive for the whole run. Idempotent: safe to re-run, already-done steps
are reported as SKIPPED. It never reboots the host.

Phases:
  --phase1        (default) Safe on the local console or over SSH:
                  Jetson performance-profile persistence, ssh, python
                  tooling, swap, podman + user lingering.
  --phase2        The headless switch: `systemctl set-default
                  multi-user.target`. Refuses to run unless this session
                  is over SSH ($SSH_CONNECTION is set) AND the ssh unit
                  is both enabled and active - running over SSH is itself
                  the proof that remote access works before the graphical
                  target goes away. Reports that a reboot is required;
                  never reboots.
  --all           Phase 1, then phase 2 (the phase-2 gate still applies).

Options:
  --dry-run       Print every action without performing any.
  --swap-size SZ  Swapfile size for /swapfile (default 16G; e.g. 8G, 32G).
  --serve-nexus   Opt in to `tailscale serve --bg 8088` for the dashboard
                  (runs with --phase2 or --all; only attempted when
                  tailscale is installed and up; changes what other
                  tailnet devices can reach).
  -h, --help      Show this help.

Exit status: 0 when every step is OK/SKIPPED, 1 when any step FAILED.
EOF
}

# record <step> <OK|SKIPPED|FAILED> <note>
# One row in the final summary table, echoed as it happens so a live run
# stays readable.
record() {
    local step="$1" result="$2" note="$3"
    SUMMARY_STEPS+=("$step")
    SUMMARY_RESULTS+=("$result")
    SUMMARY_NOTES+=("$note")
    printf '==> [%s] %s: %s\n' "$result" "$step" "$note"
    if [[ "$result" == "FAILED" ]]; then
        ANY_FAILED=1
    fi
    return 0
}

# Every mutating action goes through run_root (or the line-writers below),
# so --dry-run prints the exact command list a live run would execute -
# and performs none of it.
run_root() {
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] sudo %s\n' "$*"
        return 0
    fi
    sudo "$@"
}

# append_root_line <file> <line>
append_root_line() {
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] append to %s: %s\n' "$1" "$2"
        return 0
    fi
    printf '%s\n' "$2" | sudo tee -a "$1" >/dev/null
}

# write_root_line <file> <line> - truncating write, for KAINE-owned files.
write_root_line() {
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] write %s: %s\n' "$1" "$2"
        return 0
    fi
    printf '%s\n' "$2" | sudo tee "$1" >/dev/null
}

# shellcheck disable=SC2317
# Invoked indirectly via EXIT trap; shellcheck's reachability heuristic misses it.
cleanup() {
    if [[ -n "$SUDO_KEEPALIVE_PID" ]]; then
        kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
        wait "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

acquire_sudo() {
    if ! command -v sudo >/dev/null 2>&1; then
        die "sudo not found - this script needs sudo for system-level steps"
    fi
    printf '%s: prompting for sudo once; the credentials stay cached for the whole run.\n' "$SCRIPT_NAME"
    if ! sudo -v; then
        die "could not obtain sudo credentials"
    fi
    # Keep-alive: refresh the sudo timestamp from a background loop so a
    # long apt-get or mkswap never blocks on a second prompt mid-run.
    # `sudo -n` never prompts - if the cache somehow expires the refresh
    # fails quietly, but a 55s refresh against the default 15-minute
    # timeout makes that unreachable in practice.
    (
        while true; do
            sleep 55
            sudo -n -v 2>/dev/null || exit 0
        done
    ) &
    SUDO_KEEPALIVE_PID=$!
}

# KAINE runs on any Linux host; nvpmodel is Jetson power-management
# plumbing. Detect via the Tegra release marker or the device-tree model
# string so non-Jetson hosts get a clean "not applicable" instead of a
# failure.
is_jetson() {
    if [[ -f /etc/nv_tegra_release ]]; then
        return 0
    fi
    if [[ -r /proc/device-tree/model ]] && grep -qi 'jetson' /proc/device-tree/model 2>/dev/null; then
        return 0
    fi
    return 1
}

# Debian/Ubuntu name the unit ssh.service; the RHEL family calls it
# sshd.service.
detect_ssh_unit() {
    SSH_UNIT=""
    local units
    units="$(systemctl list-unit-files --type=service 2>/dev/null || true)"
    if grep -q '^ssh\.service' <<<"$units"; then
        SSH_UNIT="ssh"
    elif grep -q '^sshd\.service' <<<"$units"; then
        SSH_UNIT="sshd"
    fi
}

ssh_enabled_and_active() {
    local en act
    en="$(systemctl is-enabled "$SSH_UNIT" 2>/dev/null || true)"
    act="$(systemctl is-active "$SSH_UNIT" 2>/dev/null || true)"
    [[ "$en" == "enabled" && "$act" == "active" ]]
}

have_active_swap() {
    local out
    if out="$(swapon --show --noheadings 2>/dev/null)" && [[ -n "$out" ]]; then
        return 0
    fi
    # swapon may be missing from PATH or too old for --show; /proc/swaps is
    # authoritative and always present on Linux. Its first line is a header,
    # so any line starting with "/" means something is swapping right now.
    if [[ -r /proc/swaps ]] && grep -q '^/' /proc/swaps; then
        return 0
    fi
    return 1
}

podman_version_ok() {
    local v="$1" ordered
    [[ -n "$v" ]] || return 1
    ordered="$(printf '%s\n%s\n' "$v" "$PODMAN_MIN" | sort -V | head -n 1)" || true
    [[ "$ordered" == "$PODMAN_MIN" ]]
}

user_linger_enabled() {
    # Parse `Linger=yes` instead of using `--value`, which needs systemd
    # >= 247; this verifies on older LTS releases too.
    loginctl show-user "$1" --property=Linger 2>/dev/null | grep -qx 'Linger=yes'
}

all_packages_installed() {
    local pkg
    for pkg in "$@"; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -qx 'install ok installed'; then
            return 1
        fi
    done
    return 0
}

# `python3 -m venv --help` succeeding proves nothing: Ubuntu splits
# ensurepip out into python3-venv, so the only honest check is to actually
# create a throwaway venv.
verify_venv_works() {
    local tmp
    if ! tmp="$(mktemp -d)"; then
        return 1
    fi
    if python3 -m venv "$tmp/probe" >/dev/null 2>&1 && [[ -x "$tmp/probe/bin/python" ]]; then
        rm -rf "$tmp"
        return 0
    fi
    rm -rf "$tmp"
    return 1
}

phase2_gate() {
    # The machine-checkable form of the runbook's step-2 human gate.
    #
    # WHY $SSH_CONNECTION: switching the default target to multi-user.target
    # is the one action in this runbook that can permanently lock an
    # operator out of a headless machine (monitor-and-keyboard recovery
    # trip). The runbook asks a human to prove a real remote login before
    # the switch; rather than trusting that the check happened, the script
    # demands the proof itself. sshd sets $SSH_CONNECTION in every session
    # it spawns, so a non-empty value means remote access demonstrably
    # works *right now*.
    #
    # The enabled+active check is belt and braces on top: the ssh unit must
    # also survive the reboot that applies the new default (enabled) and be
    # reachable at the moment of the switch (active).
    PHASE2_PROBLEMS=()
    if [[ -z "${SSH_CONNECTION:-}" ]]; then
        PHASE2_PROBLEMS+=("this session is not over SSH (\$SSH_CONNECTION is unset) - open a real remote login from a second device and re-run --phase2 from there")
    fi
    if [[ -z "$SSH_UNIT" ]]; then
        detect_ssh_unit
    fi
    if [[ -z "$SSH_UNIT" ]]; then
        PHASE2_PROBLEMS+=("no ssh.service/sshd.service unit found - remote access cannot be verified (is systemd running? is openssh-server installed?)")
    else
        local en act
        en="$(systemctl is-enabled "$SSH_UNIT" 2>/dev/null || true)"
        act="$(systemctl is-active "$SSH_UNIT" 2>/dev/null || true)"
        if [[ "$en" != "enabled" ]]; then
            PHASE2_PROBLEMS+=("$SSH_UNIT is not enabled (is-enabled: '${en:-unknown}') - run phase 1 first")
        fi
        if [[ "$act" != "active" ]]; then
            PHASE2_PROBLEMS+=("$SSH_UNIT is not active (is-active: '${act:-unknown}')")
        fi
    fi
    [[ ${#PHASE2_PROBLEMS[@]} -eq 0 ]]
}

# Runbook step 1: pin < PM_CONFIG DEFAULT=2 > (MAXN_SUPER; modes are
# 0=15W, 1=25W, 2=MAXN_SUPER) so the performance mode survives reboots.
step_performance_profile() {
    local conf="/etc/nvpmodel.conf"
    local sed_expr='s|^([[:space:]]*<[[:space:]]*PM_CONFIG[[:space:]]+DEFAULT=)[0-9]+|\12|'
    local backup

    if ! is_jetson; then
        record "performance-profile" "SKIPPED" "not a Jetson host - nvpmodel not applicable (KAINE does not require a Jetson)"
        return 0
    fi
    if [[ ! -f "$conf" ]]; then
        record "performance-profile" "FAILED" "Jetson detected but $conf is missing"
        return 0
    fi
    if grep -Eq '<[[:space:]]*PM_CONFIG[[:space:]]+DEFAULT=2[[:space:]]*>' "$conf"; then
        record "performance-profile" "SKIPPED" "$conf already pins < PM_CONFIG DEFAULT=2 > (MAXN_SUPER)"
        return 0
    fi
    if ! grep -Eq '<[[:space:]]*PM_CONFIG[[:space:]]+DEFAULT=[0-9]+' "$conf"; then
        record "performance-profile" "FAILED" "no < PM_CONFIG DEFAULT= > line found in $conf"
        return 0
    fi
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] sudo cp -a %s %s.bak.<timestamp>\n' "$conf" "$conf"
        printf "    [dry-run] sudo sed -i -E '%s' %s\n" "$sed_expr" "$conf"
        record "performance-profile" "OK" "dry-run: would set < PM_CONFIG DEFAULT=2 > (MAXN_SUPER), backing up first"
        return 0
    fi
    backup="${conf}.bak.$(date +%Y%m%d-%H%M%S)"
    if ! run_root cp -a "$conf" "$backup"; then
        record "performance-profile" "FAILED" "could not back up $conf to $backup"
        return 0
    fi
    # Precise substitution: only the digits after `PM_CONFIG DEFAULT=` are
    # replaced; the rest of the `< ... >` line is left byte-for-byte intact.
    if ! run_root sed -i -E "$sed_expr" "$conf"; then
        record "performance-profile" "FAILED" "sed edit of $conf failed (backup at $backup)"
        return 0
    fi
    # Verify by re-reading the file, not by trusting sed's exit code.
    if grep -Eq '<[[:space:]]*PM_CONFIG[[:space:]]+DEFAULT=2[[:space:]]*>' "$conf"; then
        record "performance-profile" "OK" "$conf now pins < PM_CONFIG DEFAULT=2 > (MAXN_SUPER); backup: $backup"
    else
        run_root cp -a "$backup" "$conf" || true
        record "performance-profile" "FAILED" "verification read of $conf failed; restored from $backup"
    fi
}

# Runbook step 2: enable and start the ssh service, then verify both states.
step_ssh() {
    if ! command -v systemctl >/dev/null 2>&1; then
        record "ssh" "SKIPPED" "systemctl not available (non-systemd host) - enable the ssh service manually"
        return 0
    fi
    detect_ssh_unit
    if [[ -z "$SSH_UNIT" ]]; then
        record "ssh" "FAILED" "no ssh.service/sshd.service unit found - install openssh-server first"
        return 0
    fi
    if ssh_enabled_and_active; then
        record "ssh" "SKIPPED" "$SSH_UNIT is already enabled and active"
        return 0
    fi
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] sudo systemctl enable --now %s\n' "$SSH_UNIT"
        record "ssh" "OK" "dry-run: would enable and start $SSH_UNIT"
        return 0
    fi
    if ! run_root systemctl enable --now "$SSH_UNIT"; then
        record "ssh" "FAILED" "systemctl enable --now $SSH_UNIT failed"
        return 0
    fi
    if ssh_enabled_and_active; then
        record "ssh" "OK" "$SSH_UNIT enabled and active (verified)"
    else
        record "ssh" "FAILED" "$SSH_UNIT is not both enabled and active after enable --now"
    fi
}

# Runbook step 3: python venv/dev tooling via apt-get (never `apt`, which
# is chatty and opinionated about non-interactive use).
step_python_tooling() {
    local pkgs=(python3-venv python3-dev build-essential)

    if ! command -v apt-get >/dev/null 2>&1; then
        record "python-tooling" "SKIPPED" "apt-get not available - install python3-venv python3-dev build-essential (or equivalents) with the native package manager"
        return 0
    fi
    if all_packages_installed "${pkgs[@]}"; then
        # Still probe: packages being installed is not proof the venv
        # module actually works (see verify_venv_works).
        if verify_venv_works; then
            record "python-tooling" "SKIPPED" "${pkgs[*]} already installed; test venv creation succeeded"
        else
            record "python-tooling" "FAILED" "${pkgs[*]} already installed but python3 -m venv cannot create a venv (ensurepip missing?)"
        fi
        return 0
    fi
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y %s\n' "${pkgs[*]}"
        record "python-tooling" "OK" "dry-run: would apt-get install ${pkgs[*]}"
        return 0
    fi
    if ! run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}"; then
        record "python-tooling" "FAILED" "apt-get install ${pkgs[*]} failed (stale package lists? try: sudo apt-get update)"
        return 0
    fi
    if ! all_packages_installed "${pkgs[@]}"; then
        record "python-tooling" "FAILED" "${pkgs[*]} still missing after apt-get install"
        return 0
    fi
    if verify_venv_works; then
        record "python-tooling" "OK" "${pkgs[*]} installed; test venv creation succeeded"
    else
        record "python-tooling" "FAILED" "${pkgs[*]} installed but python3 -m venv cannot create a venv (ensurepip missing?)"
    fi
}

# Runbook step 4: a configurable swapfile at /swapfile plus
# vm.swappiness=10, live and persisted.
step_swap() {
    local fstab_line="/swapfile none swap sw 0 0"
    local active_desc ftype swappiness_now

    # WHY this check comes first: a host that already swaps (zram, a swap
    # partition, a swapfile from an earlier setup) must not get a second
    # swapfile, and re-running mkswap/swapon against an active device is
    # exactly how active swap gets corrupted. If anything is swapping, the
    # whole step is skipped and reported; replacing an existing swap setup
    # is a human decision, not something a re-run should do silently.
    if have_active_swap; then
        active_desc="$(swapon --show --noheadings 2>/dev/null | head -n 1 || true)"
        if [[ -z "$active_desc" ]]; then
            active_desc="$(grep '^/' /proc/swaps 2>/dev/null | head -n 1 || true)"
        fi
        record "swap" "SKIPPED" "swap already active (${active_desc:-unknown device}) - not creating a second swapfile or touching the active one"
        return 0
    fi

    if [[ -e "$SWAPFILE" ]]; then
        if (( DRY_RUN == 1 )); then
            printf '    [dry-run] sudo blkid -o value -s TYPE %s   # must be "swap"\n' "$SWAPFILE"
            printf '    [dry-run] sudo chmod 600 %s\n' "$SWAPFILE"
            printf '    [dry-run] sudo swapon %s\n' "$SWAPFILE"
            record "swap" "OK" "dry-run: $SWAPFILE exists; the live run reuses it only if it is already swap-formatted, otherwise it FAILS"
            return 0
        fi
        ftype="$(run_root blkid -o value -s TYPE "$SWAPFILE" 2>/dev/null || true)"
        if [[ "$ftype" != "swap" ]]; then
            record "swap" "FAILED" "$SWAPFILE exists but is not swap-formatted (blkid type: '${ftype:-unrecognized}') - refusing to overwrite whatever is at that path"
            return 0
        fi
        printf '%s: reusing existing swap-formatted %s\n' "$SCRIPT_NAME" "$SWAPFILE"
        if ! run_root chmod 600 "$SWAPFILE"; then
            record "swap" "FAILED" "chmod 600 $SWAPFILE failed"
            return 0
        fi
    else
        if (( DRY_RUN == 1 )); then
            printf '    [dry-run] sudo fallocate -l %s %s\n' "$SWAP_SIZE" "$SWAPFILE"
            printf '    [dry-run] sudo chmod 600 %s\n' "$SWAPFILE"
            printf '    [dry-run] sudo mkswap %s\n' "$SWAPFILE"
            printf '    [dry-run] sudo swapon %s\n' "$SWAPFILE"
            printf '    [dry-run] append to /etc/fstab if absent: %s\n' "$fstab_line"
            printf '    [dry-run] sudo sysctl -w vm.swappiness=10\n'
            printf '    [dry-run] write %s: vm.swappiness = 10\n' "$SWAP_SYSCTL_CONF"
            record "swap" "OK" "dry-run: would create a $SWAP_SIZE swapfile at $SWAPFILE"
            return 0
        fi
        if ! run_root fallocate -l "$SWAP_SIZE" "$SWAPFILE"; then
            record "swap" "FAILED" "fallocate -l $SWAP_SIZE $SWAPFILE failed (filesystem may not support it)"
            return 0
        fi
        if ! run_root chmod 600 "$SWAPFILE"; then
            record "swap" "FAILED" "chmod 600 $SWAPFILE failed"
            return 0
        fi
        if ! run_root mkswap "$SWAPFILE"; then
            record "swap" "FAILED" "mkswap $SWAPFILE failed"
            return 0
        fi
    fi

    if ! run_root swapon "$SWAPFILE"; then
        record "swap" "FAILED" "swapon $SWAPFILE failed (some filesystems need extra swapfile handling)"
        return 0
    fi

    # Only append when /swapfile has no entry yet - a duplicate fstab line
    # is harmless at boot but confusing forever after.
    if ! grep -Eq '^[[:space:]]*/swapfile[[:space:]]' /etc/fstab 2>/dev/null; then
        if ! append_root_line /etc/fstab "$fstab_line"; then
            record "swap" "FAILED" "could not append the /swapfile entry to /etc/fstab"
            return 0
        fi
    fi

    swappiness_now="$(cat /proc/sys/vm/swappiness 2>/dev/null || true)"
    if [[ "$swappiness_now" != "10" ]]; then
        if ! run_root sysctl -w vm.swappiness=10; then
            record "swap" "FAILED" "could not set vm.swappiness=10 at runtime"
            return 0
        fi
    fi
    if ! grep -Eq '^vm\.swappiness[[:space:]]*=[[:space:]]*10' "$SWAP_SYSCTL_CONF" 2>/dev/null; then
        if ! write_root_line "$SWAP_SYSCTL_CONF" "vm.swappiness = 10"; then
            record "swap" "FAILED" "could not write $SWAP_SYSCTL_CONF"
            return 0
        fi
    fi

    if ! swapon --show --noheadings 2>/dev/null | grep -Fq -- "$SWAPFILE"; then
        record "swap" "FAILED" "$SWAPFILE is not listed by swapon --show after swapon"
        return 0
    fi
    record "swap" "OK" "$SWAPFILE active ($SWAP_SIZE requested); vm.swappiness=10 live and persisted in $SWAP_SYSCTL_CONF"
}

# Runbook step 5: podman (>= 4.4) plus lingering for the invoking human,
# so KAINE's services survive logout without becoming root-owned.
step_container_runtime() {
    local podman_state="ok" podman_note=""
    local linger_state="ok" linger_note=""
    local pver result

    if command -v podman >/dev/null 2>&1; then
        pver="$(podman --version 2>/dev/null | awk '{print $3}')" || true
        if podman_version_ok "$pver"; then
            podman_note="podman $pver already installed (>= $PODMAN_MIN)"
        else
            podman_state="failed"
            podman_note="podman ${pver:-unknown} is present but older than the required $PODMAN_MIN - upgrade it"
        fi
    elif command -v apt-get >/dev/null 2>&1; then
        if (( DRY_RUN == 1 )); then
            printf '    [dry-run] sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y podman\n'
            podman_note="dry-run: would apt-get install podman (KAINE needs >= $PODMAN_MIN)"
        else
            if run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y podman; then
                pver="$(podman --version 2>/dev/null | awk '{print $3}')" || true
                if podman_version_ok "$pver"; then
                    podman_note="podman $pver installed"
                else
                    podman_state="failed"
                    podman_note="podman installed as '${pver:-unknown}' but KAINE needs >= $PODMAN_MIN (distro repo too old - add a newer podman repository)"
                fi
            else
                podman_state="failed"
                podman_note="apt-get install -y podman failed (stale package lists? try: sudo apt-get update)"
            fi
        fi
    else
        podman_state="skipped"
        podman_note="no podman and no apt-get - install podman >= $PODMAN_MIN with the native package manager"
    fi

    # Lingering targets the invoking human, never root: KAINE's 24/7
    # services must belong to the operator's account. Prefer $SUDO_USER
    # (set when someone wraps this script in sudo despite the advice) and
    # fall back to the current user.
    TARGET_USER="${SUDO_USER:-$(id -un)}"
    if [[ "$TARGET_USER" == "root" ]]; then
        linger_state="failed"
        linger_note="refusing to enable lingering for root - run this script as the normal user, not as root"
    elif ! id -u "$TARGET_USER" >/dev/null 2>&1; then
        linger_state="failed"
        linger_note="invoking user '$TARGET_USER' does not exist"
    elif ! command -v loginctl >/dev/null 2>&1; then
        linger_state="skipped"
        linger_note="loginctl not available (non-systemd host) - enable lingering for $TARGET_USER manually"
    elif user_linger_enabled "$TARGET_USER"; then
        linger_note="lingering already enabled for $TARGET_USER"
    elif (( DRY_RUN == 1 )); then
        printf '    [dry-run] sudo loginctl enable-linger %s\n' "$TARGET_USER"
        linger_note="dry-run: would enable lingering for $TARGET_USER"
    elif run_root loginctl enable-linger "$TARGET_USER" && user_linger_enabled "$TARGET_USER"; then
        linger_note="lingering enabled for $TARGET_USER (verified Linger=yes)"
    else
        linger_state="failed"
        linger_note="could not enable or verify lingering for $TARGET_USER"
    fi

    if [[ "$podman_state" == "failed" || "$linger_state" == "failed" ]]; then
        result="FAILED"
    elif [[ "$podman_state" == "skipped" && "$linger_state" == "skipped" ]]; then
        result="SKIPPED"
    else
        result="OK"
    fi
    record "container-runtime" "$result" "podman: $podman_note; linger: $linger_note"
}

# Runbook step 6 (PHASE 2 ONLY): the headless switch. The script NEVER
# reboots - it reports that a reboot is required and leaves the timing to
# the operator.
step_headless_switch() {
    if ! command -v systemctl >/dev/null 2>&1; then
        record "headless-switch" "FAILED" "refused: systemctl not available (non-systemd host)"
        return 0
    fi
    if ! phase2_gate; then
        local joined="" p
        for p in "${PHASE2_PROBLEMS[@]}"; do
            if [[ -n "$joined" ]]; then
                joined+="; "
            fi
            joined+="$p"
        done
        record "headless-switch" "FAILED" "refused: $joined"
        return 0
    fi
    local current
    current="$(systemctl get-default 2>/dev/null || true)"
    if [[ "$current" == "multi-user.target" ]]; then
        record "headless-switch" "SKIPPED" "default target is already multi-user.target"
        return 0
    fi
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] sudo systemctl set-default multi-user.target\n'
        record "headless-switch" "OK" "dry-run: would set-default multi-user.target (a reboot would then be required; this script never reboots)"
        return 0
    fi
    if ! run_root systemctl set-default multi-user.target; then
        record "headless-switch" "FAILED" "systemctl set-default multi-user.target failed"
        return 0
    fi
    current="$(systemctl get-default 2>/dev/null || true)"
    if [[ "$current" == "multi-user.target" ]]; then
        REBOOT_REQUIRED=1
        record "headless-switch" "OK" "default target is now multi-user.target - REBOOT REQUIRED to apply; this script never reboots the host"
    else
        record "headless-switch" "FAILED" "default target reads '$current' after set-default"
    fi
}

# Runbook step 7: dashboard over the tailnet. Opt-in, because it changes
# what other devices can reach; only attempted when tailscale is installed
# and up, otherwise a clearly-reported skip.
step_tailscale_serve() {
    if (( SERVE_NEXUS == 0 )); then
        record "tailscale-serve" "SKIPPED" "opt-in step not requested (pass --serve-nexus to serve the dashboard on :8088 over the tailnet)"
        return 0
    fi
    if ! command -v tailscale >/dev/null 2>&1; then
        record "tailscale-serve" "SKIPPED" "tailscale is not installed"
        return 0
    fi
    if ! tailscale status >/dev/null 2>&1; then
        record "tailscale-serve" "SKIPPED" "tailscale is installed but not up (tailscale status failed)"
        return 0
    fi
    if tailscale serve status 2>/dev/null | grep -q '8088'; then
        record "tailscale-serve" "SKIPPED" "already serving on :8088"
        return 0
    fi
    if (( DRY_RUN == 1 )); then
        printf '    [dry-run] sudo tailscale serve --bg 8088\n'
        record "tailscale-serve" "OK" "dry-run: would run tailscale serve --bg 8088"
        return 0
    fi
    if ! run_root tailscale serve --bg 8088; then
        record "tailscale-serve" "FAILED" "tailscale serve --bg 8088 failed"
        return 0
    fi
    if tailscale serve status 2>/dev/null | grep -q '8088'; then
        record "tailscale-serve" "OK" "dashboard served on :8088 over the tailnet"
    else
        record "tailscale-serve" "FAILED" "tailscale serve status does not show :8088 after serve"
    fi
}

print_summary() {
    local i
    printf '\n============================== SUMMARY ==============================\n'
    if [[ ${#SUMMARY_STEPS[@]} -eq 0 ]]; then
        printf 'no steps ran\n'
        return 0
    fi
    printf '%-20s %-8s %s\n' 'STEP' 'RESULT' 'NOTE'
    for i in "${!SUMMARY_STEPS[@]}"; do
        printf '%-20s %-8s %s\n' "${SUMMARY_STEPS[$i]}" "${SUMMARY_RESULTS[$i]}" "${SUMMARY_NOTES[$i]}"
    done
    printf '\nPost-run verification (docs/deployment-headless-host.md checklist):\n'
    printf '  systemctl is-enabled ssh && systemctl is-active ssh\n'
    printf '  swapon --show --noheadings                      # expect %s\n' "$SWAPFILE"
    printf '  cat /proc/sys/vm/swappiness                     # expect 10\n'
    printf '  loginctl show-user %s --property=Linger   # expect Linger=yes\n' "${TARGET_USER:-<invoking-user>}"
    printf '  podman --version                                # expect >= %s\n' "$PODMAN_MIN"
    printf '  systemctl get-default                           # expect multi-user.target after phase 2\n'
    printf '  nvpmodel -q                                     # Jetson only: expect MAXN_SUPER\n'
    if (( SERVE_NEXUS == 1 )); then
        printf '  tailscale serve status                          # expect :8088\n'
    fi
    if (( REBOOT_REQUIRED == 1 )); then
        printf '\nREBOOT REQUIRED to apply multi-user.target. This script never reboots\n'
        printf 'the host - reboot yourself, from the SSH session, when you are ready.\n'
    fi
    if (( ANY_FAILED == 1 )); then
        printf '\nOne or more steps FAILED - fix the notes above and re-run; every step is idempotent.\n'
    fi
    return 0
}

parse_args() {
    while (( $# > 0 )); do
        case "$1" in
            --phase1)
                PHASE="1"
                ;;
            --phase2)
                PHASE="2"
                ;;
            --all)
                PHASE="all"
                ;;
            --dry-run)
                DRY_RUN=1
                ;;
            --serve-nexus)
                SERVE_NEXUS=1
                ;;
            --swap-size)
                if (( $# < 2 )); then
                    usage >&2
                    die "--swap-size requires a value (e.g. --swap-size 16G)"
                fi
                SWAP_SIZE="$2"
                shift
                ;;
            --swap-size=*)
                SWAP_SIZE="${1#*=}"
                ;;
            -h | --help)
                usage
                exit 0
                ;;
            *)
                usage >&2
                die "unknown option: $1"
                ;;
        esac
        shift
    done
    SWAP_SIZE="${SWAP_SIZE^^}"
    if [[ ! "$SWAP_SIZE" =~ ^[0-9]+[KMGT]?$ ]]; then
        die "invalid --swap-size '$SWAP_SIZE' (expected e.g. 16G, 8G, 2048M, or a plain byte count)"
    fi
}

main() {
    parse_args "$@"

    # The script must know the invoking human: that user is the linger
    # target and the account KAINE runs as. Running it under sudo makes
    # that ambiguous (and would point lingering at root, which the linger
    # step refuses) - so refuse here, up front, with the reason.
    if (( EUID == 0 )); then
        die "do not run as root or under sudo - run as the normal user; sudo is invoked internally, once"
    fi

    printf '%s: phase=%s dry-run=%s swap-size=%s serve-nexus=%s\n' \
        "$SCRIPT_NAME" "$PHASE" "$DRY_RUN" "$SWAP_SIZE" "$SERVE_NEXUS"
    if [[ "$PHASE" == "1" && "$SERVE_NEXUS" == "1" ]]; then
        printf '%s: note: --serve-nexus takes effect in phase 2 (--phase2 or --all); it will not run in this phase-1 pass.\n' "$SCRIPT_NAME" >&2
    fi

    if (( DRY_RUN == 1 )); then
        printf '%s: dry-run - no changes will be made and sudo will not be invoked.\n' "$SCRIPT_NAME"
    else
        acquire_sudo
    fi

    if [[ "$PHASE" == "1" || "$PHASE" == "all" ]]; then
        step_performance_profile || record "performance-profile" "FAILED" "unexpected error - see output above"
        step_ssh || record "ssh" "FAILED" "unexpected error - see output above"
        step_python_tooling || record "python-tooling" "FAILED" "unexpected error - see output above"
        step_swap || record "swap" "FAILED" "unexpected error - see output above"
        step_container_runtime || record "container-runtime" "FAILED" "unexpected error - see output above"
    fi
    if [[ "$PHASE" == "2" || "$PHASE" == "all" ]]; then
        step_headless_switch || record "headless-switch" "FAILED" "unexpected error - see output above"
        step_tailscale_serve || record "tailscale-serve" "FAILED" "unexpected error - see output above"
    fi

    print_summary
    exit "$ANY_FAILED"
}

main "$@"