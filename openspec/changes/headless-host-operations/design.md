# Design — `headless-host-operations`

## Why this capability exists

KAINE's documentation answers two questions: how to install the software, and how to bring services up. Neither answers the question an operator of a dedicated host actually faces: how to turn a general-purpose Linux machine into an appliance that runs one KAINE instance continuously, unattended, across power cuts and reboots, with no human logged in.

Dedicating a host is a distinct activity with its own invariants — ordering constraints between steps, boot-persistence properties, and acceptance tests that produce evidence rather than silence. That is procedural, gate-ordered knowledge, which is why it takes the shape of a new capability plus an operator runbook rather than additional paragraphs in the install docs.

The gap is not hypothetical. A live install (Jetson Orin Nano Super, verified 2026-09-14) produced seven concrete defects, each one a way for a 24/7 host to silently fail at its one job.

## Verified defects on the live install, and what each implies

| # | Defect (verified on the live machine) | What it implies for the design |
|---|---|---|
| 1 | `nvpmodel -q` reports MAXN_SUPER, but `/etc/nvpmodel.conf` DEFAULT is `1` (25W); reboot silently drops to 25W with no error and no log line | "Currently set" and "persists across reboot" are different properties. Verification must read the persisted boot-time source of truth, and acceptance requires surviving an actual reboot. |
| 2 | `Linger=no` for the service user (`erik`); rootless quadlet units will not start at boot | The "reboot survival" claim in `quadlet/README.md` is false as shipped. Boot persistence must be verified by reboot evidence or by reading the linger flag — never inferred from unit files or documentation claims. |
| 3 | Podman absent (Docker only); quadlet units need Podman >= 4.4 | Prerequisites must be checked, not assumed. Ubuntu 24.04's candidate (4.9.3) clears the floor, but the check itself must be a runbook step. |
| 4 | `python3-venv` absent, so venv creation fails even though `python3 -m venv --help` succeeds; `python3-pip` absent; PEP 668 managed | Tooling presence is not capability: help text succeeding proves nothing about `ensurepip`. Distro package splits and PEP 668 must be handled explicitly, not discovered at failure time. |
| 5 | No swap of any kind; 8 GB unified (CPU+GPU) memory; 854 GB NVMe free | An OOM safety valve is required, and the medium must be chosen by reasoning about the host, not by platform habit. |
| 6 | SSH disabled and inactive; host boots to `graphical.target` with gdm3 consuming ~2-3 GB of the 8 GB budget | Removing the local access path before proving a remote one risks total loss of access. This is an ordering constraint, not a tip. |
| 7 | Nexus loopback-only with no documented remote path; Tailscale present and running, HTTPS certs already provisioned | Dashboard reachability is a real capability gap; the fix is a proxy in front of the loopback bind, never a widened bind. |

Two patterns run through the table. First, three of the seven (#1, #2, and the boot-time half of #6) are "correct now, silently absent at boot" defects — a class of failure only a 24/7 host cares about, because only a 24/7 host reboots unattended. Second, none of them produce errors. The host keeps running; the entity just gets slower, stays down after a power cut, or loses its safety valve. Silent degradation is the characteristic failure mode of an appliance, so the runbook is built around verification steps that produce evidence, not checks that produce silence.

## SSH before headless is an ordering constraint, not advice

The runbook requires: enable SSH, prove a real authenticated login from a different device, and only then switch the default target to `multi-user.target` (dropping gdm3 and the graphical session). The order is normative because the failure it prevents is not recoverable by any later step in the procedure.

If the host goes headless before a remote-access path is proven, and SSH does not actually work — unit disabled, key rejected, firewall, sshd misconfigured — the machine is headless with no working access path. Nothing in software can recover from that state. The recovery is a physical trip with a monitor and keyboard, to a machine that may be mounted, boxed, or in another building. Advice can be ignored at the cost of rework; a violated ordering constraint costs physical access.

Three properties make this an ordering constraint rather than a recommendation:

1. **Asymmetric, unrecoverable failure.** Every other step in the runbook can be re-run after a mistake. This one cannot: the state it can produce — headless, no remote access — has no software exit.
2. **Silent at the moment of violation.** Switching to `multi-user.target` produces no error even if SSH is broken. The defect surfaces only when access is next needed, which for a dedicated host is exactly when nobody is standing next to it.
3. **The gate is a demonstrated login, not a service check.** `systemctl is-active ssh` and a listening port prove the daemon, not the path. The failure modes that matter — authentication, keys, firewall — only surface when a real session is established from a different device. The gate is therefore an actual successful login, which is what converts "SSH is configured" into "SSH is a recovery path."

The constraint is stated generically — prove a remote-access path before removing the local one — because it applies to any host conversion. The Jetson specifics (gdm3, `graphical.target`) belong to the worked example. A secondary benefit of doing SSH first: every subsequent step — linger, swap, Podman, the headless switch itself — is then performed over SSH, which doubles as the first rehearsal of the access path the host will depend on.

## Swap policy: an NVMe swapfile, not zram — and when zram is still right

NVIDIA's standard Jetson guidance is zram. That guidance is calibrated for eMMC: where persistent storage is slow, swap I/O is pathologically slow and wear-heavy, so compressed in-memory swap wins despite its costs. The trade zram makes is explicit — spend CPU cycles and RAM (compressed page storage plus metadata) to enlarge effective memory.

On this host the trade is inverted. The scarce resource is RAM itself: 8 GB of unified memory shared by CPU and GPU, with model weights intended to stay resident. zram would spend RAM to buy back a fraction of RAM, and spend CPU that competes with inference, on a machine with 854 GB of fast NVMe sitting idle. An NVMe swapfile spends no RAM and no CPU in the common case; its cost is paid only when pages actually move, and NVMe latency is orders of magnitude below eMMC.

The role of swap here is deliberately narrow: an OOM safety valve, not a hot path. Hence `vm.swappiness = 10` — the kernel should strongly prefer reclaiming page cache and reach for swap only under real pressure. The failure being guarded is a transient spike (a memory-hungry subprocess, a model-load overshoot) that would otherwise invoke the OOM killer and take down the KAINE instance or a system service. Swap gives the system room to degrade instead of die. On a unified-memory host there is no separate GPU pool to absorb a spike; an OOM event takes everything down at once, which strengthens the case for a valve. NVMe wear from a low-swappiness valve is negligible: pages move rarely, and modern NVMe endurance is far beyond what an emergency valve consumes.

The decision rule, stated generically in the runbook: choose the swap medium by the ratio of storage speed to memory scarcity, not by platform habit.

- **Fast writable persistent storage + scarce RAM** → swapfile on that storage, low swappiness. (This host.)
- **Slow storage (eMMC, SD card) or no writable persistent storage** → zram; the CPU/RAM cost is worth paying because the alternative is unusably slow or nonexistent swap.
- **Abundant RAM relative to workload** → swap is a formality either way; pick the cheaper option.

zram is not wrong in general — it is wrong *here*, and the runbook says why rather than silently diverging from platform guidance.

## Reachability: keep the loopback bind, add a proxy

The obvious fix for "the dashboard is unreachable from other devices" is to set `[nexus] host = "0.0.0.0"` or drop the `127.0.0.1:` prefix from `PublishPort`. The design rejects it, and the reasoning generalizes to any service on any host.

Widening a bind changes the service's own trust boundary. A loopback bind means only host-local processes can connect; it is the innermost layer of defence in depth, and it travels with the service configuration. A `0.0.0.0` bind means every interface — LAN, wireless, current and future container bridges, anything that can route to the host — can connect unless a separate firewall layer is independently correct and maintained. Every later network change (a new interface, a new bridge, joining a new network) silently expands exposure. The innermost layer, once removed, does not come back on its own.

Proxying preserves the invariant. With `tailscale serve --bg 8088`, the service still sees a loopback peer and its bind is untouched; exposure is mediated by one explicit, auditable, reversible layer:

- **Scope is explicit.** Only devices on the tailnet can reach the proxy, and the tailnet is an authenticated overlay — membership is the access control.
- **It is inspectable and reversible.** `tailscale serve status` shows exactly what is exposed, and a single reset command removes it. The blast radius of a mistake is bounded by the proxy's rules, not by the service's bind.
- **Transport comes free.** The tailnet already has HTTPS certs provisioned for the node's MagicDNS name, so the dashboard gets a trusted HTTPS URL with no certificate management.
- **The URL is stable in the way that matters.** MagicDNS names persist across changes to the node's 100.x address, so the dashboard URL outlives address churn that would break an IP-based URL.

The general principle: never widen a service's own exposure when a mediating layer in front of it will do. On every host, in every variant of this runbook, services stay bound to loopback and reachability is added by a proxy whose scope is explicit.

## Exposing the dashboard on a tailnet has a privacy consequence

A tailnet is a perimeter around devices, not around people or purposes. Once the dashboard is served on the tailnet, it is reachable from every device on the tailnet — the operator's laptop, but also phones, tablets, and any node ever added. Reachability that was scoped to "whoever sits at this machine" becomes scoped to "everything in the tailnet, now and in the future."

KAINE's dashboard content gates exist precisely for this boundary. `[nexus] dev_content_override` gates raw message text, beliefs, memory bodies, internal speech, and affect reasons — the entity's interior. If reachability were fixed by widening a bind and nothing else were said, that interior would silently become fleet-readable as a side effect of a networking fix.

The design position: enabling reachability must not widen content. `dev_content_override` stays `false`, and `conversation_enabled` stays `false` unless deliberately changed. The default posture is that the tailnet dashboard shows what a dashboard should show; the entity's unfiltered interior is available only as a separate, deliberate operator decision — never as a side effect of fixing reachability. The runbook states this as part of the exposure step itself, not as an afterthought, because the two changes are independent in mechanism but coupled in consequence.

Transport encryption is not part of this control. `tailscale serve` provides HTTPS in transit, but encryption is not authorization; the privacy property lives in the content gates, and the design keeps them closed by default.

## "Currently set" and "persists across reboot" are different properties

These are different claims requiring different evidence:

- **Currently set** is a property of running state. `nvpmodel -q` reporting MAXN_SUPER is evidence about *now*.
- **Persists across reboot** is a property of persisted configuration — what the system will select at the *next boot*. On Jetson that lives in `/etc/nvpmodel.conf`'s DEFAULT, which on the live install read `1` (25W) while live state read MAXN_SUPER.

The live install held both facts simultaneously: the profile is set, and it will not survive. Any check that reads only live state passes while the defect is present. The defect then manifests at the next reboot — silently, with no error and no log line — and the host drops to 25W and keeps running. Nothing crashes; the entity just gets slower, on a machine nobody is watching a terminal on. For a 24/7 host, silent throttling is as real a failure as a crash, and harder to notice.

The design consequence: for a 24/7 host, the property that matters is boot persistence, so verification must produce evidence about boot time. Two forms qualify — reading the persisted source of truth (the config default, the enabled unit, the linger flag), and, where feasible, an actual reboot followed by re-verification. The runbook uses whichever is stronger for each property, and its acceptance tests are phrased against persistence ("survives reboot"), never against present state ("is currently set"). The same principle covers the boot-start mechanics of #2: units that must start at boot must be owned by something that starts at boot — system units, or a user manager with linger enabled — and that is verified by reboot evidence, not by the README's word.

This is the general rule the capability encodes: every property claimed of a 24/7 host must be a boot-persistent property, and every verification must distinguish "set now" from "set at every boot."

## Portability and explicit non-goals

The procedure is written host-agnostic: prove remote access before going headless; make service boot persistence real and verify it by reboot; choose the swap medium by storage speed versus memory scarcity; keep services on loopback and add reachability by proxy; verify that performance and power configuration persists rather than merely is set. Host-specific commands — `nvpmodel`, JetPack, the Jetson power modes — appear only inside a clearly-labelled worked example.

Deliberately out of scope:

- **Nothing implies KAINE requires a Jetson or ARM.** The dual-GPU x86_64 workstation path remains the default and is untouched; this capability is purely additive.
- **No distro is mandated.** Ubuntu 24.04's package splitting and PEP 668 appear as worked-example details; the generic steps name the capability needed (a working venv/`ensurepip`, the distro's Python packaging policy) rather than a package name.
- **No widening of any bind, anywhere, for any reason covered here.**
- **No change to dashboard content defaults as a consequence of exposure.**

## Residual risks the design accepts

Stated so the operator knows them rather than discovers them:

- **If the tailnet is down, the dashboard is remotely unreachable** — but the entity keeps running, because the dashboard is an observation surface, not part of KAINE's control path. Loopback access on the host itself is unaffected.
- **Enabling linger means the user's services run without a login session.** That is the point, and it is scoped to the dedicated service user on a host whose purpose is exactly this.
- **A swapfile is not more RAM.** With swappiness at 10 it absorbs spikes; it does not permit workloads that genuinely exceed unified memory. The runbook says so, so the valve is not mistaken for headroom.