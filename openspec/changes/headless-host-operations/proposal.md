## Why

KAINE's docs cover installing the software and bringing up services. Nothing covers the step beyond that: turning a machine into a dedicated, headless, 24/7 host for a continuously-running entity. That gap is not hypothetical — it has already produced real, verified defects on a live install (Jetson Orin Nano Super, 2026-09-14; every fact below was checked on the machine, not assumed).

The two most serious:

**The performance profile silently does not persist.** `nvpmodel -q` reports MAXN_SUPER (mode 2), but `/etc/nvpmodel.conf` line 216 reads `< PM_CONFIG DEFAULT=1 >` — and mode 1 is 25W. On the next reboot the host drops to 25W with no error and no log line. A 24/7 host must verify that its performance profile *persists*; "it is currently set correctly" is not a checkable claim, and nothing in the docs even names this failure mode.

**The quadlet README's "reboot survival" claim is false as shipped.** `quadlet/README.md` presents Quadlet as "the recommended production path ... with native dependency ordering, logging, restart, and reboot survival." But rootless systemd user units do not start at boot unless the user has linger enabled, and `loginctl show-user erik` reports `Linger=no`. As shipped, a power cut leaves every KAINE service down until a human logs in at the console — the exact failure a dedicated host exists to prevent, asserted as solved by the documentation.

The same audit surfaced the rest of the gap on the same host:

- **Podman is absent.** The quadlet units require Podman >= 4.4; the host has only Docker. Ubuntu 24.04's candidate 4.9.3 is sufficient.
- **Python venv creation fails.** `python3-venv` is not installed (Ubuntu splits `ensurepip` into it), `python3-pip` is absent, and Ubuntu 24.04 is PEP 668-managed.
- **No swap of any kind.** `swapon --show` is empty and no zram unit exists, on a host with 8 GB of unified CPU+GPU memory and 854 GB free on NVMe.
- **SSH is off while the desktop burns the RAM budget.** `openssh-server` is installed but `ssh` reports `disabled` and `inactive`; the host boots to `graphical.target` with gdm3 consuming ~2–3 GB of the 8 GB budget.
- **The dashboard is unreachable from any other device.** `[nexus] host = "127.0.0.1"` and `PublishPort=127.0.0.1:8088:8088`, with no documented remote path — even though Tailscale is installed and running on this host (node `kaine-one`) with tailnet HTTPS certificates already provisioned.

One step is order-sensitive in a way that costs physical access if done wrong: SSH must be enabled and a real remote login verified *before* switching the host to `multi-user.target`. Invert that order and recovery requires a trip with a monitor and keyboard.

This is a general operations problem, not a Jetson problem. The procedure — remote access before headless, service reboot survival, swap policy, dashboard reachability, performance-profile persistence — applies to any Linux host being dedicated to a 24/7 KAINE instance. Jetson-specific commands (`nvpmodel`, JetPack) will appear only as a clearly-labelled worked example. This change must not imply that KAINE requires a Jetson, and must not regress or complicate the existing dual-GPU x86_64 workstation path, which remains the default and is unaffected.

## What Changes

- **Add a new capability `headless-host-operations`**, encoding the dedication procedure as normative, host-agnostic requirements:
  - **Remote access before headless, as a hard gate.** SSH is enabled and a real remote login is verified before the boot target is switched to `multi-user.target`; the switch is not performed until remote access is proven to work.
  - **Reboot survival that is verified, not assumed.** Rootless services survive reboot only with linger enabled; the procedure enables linger and then proves survival by actually rebooting and confirming the services come back.
  - **Performance-profile persistence.** The host's performance/power profile is set, made persistent, and re-verified after a reboot. The rule is general; `nvpmodel` appears only in the worked example.
  - **Swap policy: NVMe swapfile, not zram, where storage is fast.** A swapfile on fast storage with `vm.swappiness=10`, positioned as an OOM safety valve rather than a hot path. The reasoning is part of the spec: zram buys capacity by spending CPU *and* RAM to compress pages — the wrong trade on a host whose scarce resource is RAM and whose goal is keeping model weights resident. zram remains correct where storage is slow (e.g., eMMC), and the docs say so.
  - **Dashboard reachability without widening binds.** Services stay bound to loopback; remote access is proxied in — `tailscale serve --bg 8088` proxies the tailnet to the existing loopback bind, yielding a permanently stable HTTPS URL (MagicDNS names persist even when the node's 100.x address changes) without touching `0.0.0.0`. Widening a bind is the obvious move and the wrong one; proxying preserves loopback as defence in depth.
  - **The privacy consequence is normative.** Serving the dashboard over a tailnet makes it reachable from every device on the tailnet, so `[nexus] dev_content_override` must stay `false` (it gates raw message text, beliefs, memory bodies, internal speech, and affect reasons) and `conversation_enabled` should stay `false` unless deliberately changed.
  - **Dedication prerequisites.** Podman >= 4.4 present for the quadlet units; Python venv/pip tooling present, handled within the distribution's package-management discipline (PEP 668 on Ubuntu 24.04).
- **Add an operator runbook under `docs/`** walking the full procedure in order: prerequisites → SSH enabled and login verified → headless target switch → linger and reboot-survival verification → performance-profile persistence → swap → dashboard reachability. The Jetson Orin Nano Super install appears as a clearly-labelled worked example inside the general procedure — not a requirement, and no implication that KAINE requires Jetson hardware.
- **Correct `quadlet/README.md`.** The "recommended production path ... reboot survival" claim is amended to state the linger prerequisite and the verification step, so the documented production path is no longer false as shipped.
- **Explicitly out of scope:** the dual-GPU x86_64 workstation path. It remains the default install path and is unaffected; nothing here introduces a hardware requirement of any kind.