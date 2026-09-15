# Dedicated headless host: 24/7 KAINE operation

This runbook turns a Linux machine into a dedicated, unattended host for a
continuously-running KAINE instance. Installing KAINE and bringing up its services is
not the same as operating them: every failure this runbook prevents was found on a live
install that looked healthy right up until the next reboot or power cut — a power
profile that silently reverted, services that never came back after a power cut, a
dashboard reachable from nothing but the machine itself.

**Portability.** These steps apply to any Linux host being dedicated to 24/7 KAINE
operation. Nothing here changes KAINE's default path: the dual-GPU x86_64 workstation
remains the standard target and is unaffected by this document. Nor does anything here
imply KAINE requires particular hardware — platform-specific commands appear only inside
clearly-labelled **worked example** callouts, and everything else is general.

**The order below is load-bearing.** Step 2 (verified remote access) must be completed
before step 6 (switching to a headless boot target). That is the one mistake in this
runbook that can cost you physical access to the machine.

You need before starting:

- sudo on the host, with the KAINE repo present (`scripts/install.sh`, `quadlet/`,
  `config/kaine.toml`)
- a second device — a laptop on the same network or tailnet — for the step 2
  verification

Each step ends in a verification. A step is not done until its verification passes.

## 1. Make the performance profile persist

A performance profile that is set but not persisted is a defect waiting for a reboot.
The property a 24/7 host needs is not "the profile is correct right now" — it is "the
profile is correct after every boot, with no human involved." So the verification that
matters is always *after a reboot*: a profile that reads correctly today tells you
nothing about the next one.

On any host:

1. Identify the platform's performance/power mechanism (CPU governor, firmware power
   profile, vendor power daemon).
2. Set the profile you want.
3. Write it into whatever the platform reads at boot for its **default** — not just the
   runtime state.
4. Reboot, and re-check the profile.

**Worked example — NVIDIA Jetson (JetPack, `nvpmodel`)**, verified on a Jetson Orin Nano
Super running Ubuntu 24.04. `nvpmodel` selects power modes; on this board the modes are
`0` = 15 W, `1` = 25 W, `2` = MAXN_SUPER. The trap is that the live mode and the
boot-time default live in different places: `nvpmodel -q` can report MAXN_SUPER while
`/etc/nvpmodel.conf` still carries `DEFAULT=1` (25 W). The next reboot then drops the
host to 25 W silently — no error, no log line.

Check both, separately:

```bash
nvpmodel -q
grep '^< PM_CONFIG' /etc/nvpmodel.conf
```

If `nvpmodel -q` says MAXN_SUPER but the grep says `< PM_CONFIG DEFAULT=1 >`, the host is
running on a setting it will not keep. Fix the default:

```bash
sudo sed -i 's/^< PM_CONFIG DEFAULT=1 >/< PM_CONFIG DEFAULT=2 >/' /etc/nvpmodel.conf
```

Verify the edit:

```bash
grep '^< PM_CONFIG' /etc/nvpmodel.conf
```

Expected output:

```
< PM_CONFIG DEFAULT=2 >
```

The definitive verification happens after the next reboot (step 6 reboots; if you want
the proof sooner, reboot now):

```bash
nvpmodel -q
```

Expected output:

```
NV Power Mode: MAXN_SUPER
```

If it reports `25W` after a reboot, persistence failed — stop and fix it before
continuing. (To set the live mode as well as the default: `sudo nvpmodel -m 2`.)

## 2. Enable remote access — and prove it works (blocking)

Everything after this point is aimed at making the host headless. If SSH is enabled but
does not actually work — firewall rule missing, key rejected, wrong unit name — you will
find out from a machine with no display attached, and the recovery is a physical trip
with a monitor and keyboard. Enabling a service is not the same as being able to log in
to it, so this step ends in a hard gate: an actual login from another device.

Enable and start SSH:

```bash
sudo systemctl enable --now ssh
```

(Debian/Ubuntu name the unit `ssh`; RHEL/Fedora name it `sshd`. If a host firewall is
active, allow the port before you go further.)

Verify the service is running and will start at boot:

```bash
systemctl is-active ssh
systemctl is-enabled ssh
```

Expected output:

```
active
enabled
```

**Blocking verification — do not skip.** From a different device:

```bash
ssh <user>@<host>
```

Expected: an interactive shell on the host.

**Skipping this verification costs physical access.** If the login fails, stop here and
fix it now, while you still have a keyboard attached to the machine. Performing the
headless switch in step 6 with unverified SSH is how a routine conversion becomes a
monitor-and-keyboard recovery trip.

## 3. Install the Python tooling the installer needs

`scripts/install.sh` builds KAINE's virtualenv itself (`.venv` in the repo), so you need
no system-wide pip — and on Ubuntu 24.04 you could not use one anyway: the system Python
is PEP 668 "externally managed", and pip refuses to install into it.

The trap is `python3-venv`. `python3 -m venv --help` succeeding proves nothing: Ubuntu
splits `ensurepip` — the module that bootstraps pip inside a new venv — into the
`python3-venv` package. Without it, `--help` works but every real `python3 -m venv`
creation fails. So the verification below creates an actual venv rather than printing a
help screen.

Install (Debian/Ubuntu package names; on other distributions the equivalents are
venv/ensurepip support, Python headers, and a C toolchain):

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev build-essential
```

Verify by doing the thing that fails when the package is missing:

```bash
python3 -m venv /tmp/kaine-venv-probe && /tmp/kaine-venv-probe/bin/pip --version && rm -rf /tmp/kaine-venv-probe
```

Expected: a `pip 24.0 ...` version line and no traceback. If you see
`ensurepip is not available`, `python3-venv` did not actually install.

## 4. Configure swap — an OOM safety valve, not a hot path

A 24/7 host running model weights needs swap. With none, memory pressure ends with the
kernel's OOM killer picking a victim — possibly KAINE — at the worst possible moment.
With swap present and swappiness low, the kernel pages out cold memory instead.

First confirm the gap:

```bash
swapon --show
```

Expected output: nothing at all — no partition, no file, no zram.

**Why a swapfile and not zram.** NVIDIA's standard Jetson advice is zram, but that
advice assumes slow eMMC storage. zram buys swap capacity by compressing pages, which
spends CPU *and* RAM to do it. On a host whose scarce resource is RAM and whose whole
point is keeping model weights resident, that is the wrong trade when fast NVMe is
available: a swapfile on NVMe costs nothing at idle and adds no compression load.
**zram remains the right choice where storage is slow** (eMMC, SD card) — this is a
storage-speed decision, not a universal rule.

The reference host has 8 GB of unified memory (CPU and GPU share one pool) and hundreds
of GB free on NVMe, so a generous file is cheap. Create a 16 GB swapfile:

```bash
sudo fallocate -l 16G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

Persist it across reboots:

```bash
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Set swappiness low — live first, then persisted — so swap stays a safety valve rather
than becoming a hot path:

```bash
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-kaine-swap.conf
```

Verify:

```bash
swapon --show
```

Expected output:

```
NAME       TYPE  SIZE USED PRIO
/swapfile  file   16G    0B   -2
```

```bash
cat /proc/sys/vm/swappiness
```

Expected output:

```
10
```

(If `swapon` rejects the file — btrfs and some XFS configurations disallow
`fallocate`d swap files — create it with
`sudo dd if=/dev/zero of=/swapfile bs=1M count=16384 status=progress` and repeat the
`mkswap` and `swapon` steps.)

## 5. Container runtime and reboot survival

Two independent gaps here, and the second is the one that bites.

**Podman.** KAINE's quadlet units require Podman >= 4.4, the version where quadlet
shipped inside Podman. The reference host had Docker only and no Podman at all; Ubuntu
24.04's candidate, 4.9.3, is sufficient:

```bash
sudo apt install -y podman
```

Verify:

```bash
podman --version
```

Expected output (must be 4.4 or newer):

```
podman version 4.9.3
```

**Linger — without it, "reboot survival" is a false claim.** KAINE's rootless services
run as systemd *user* units (quadlet generates user units; see `quadlet/README.md`).
Rootless user units do **not** start at boot unless the user has linger enabled: without
it, the user's service manager is torn down at logout and never started at boot.

> **Without linger, a power cut leaves every service down until a human logs in.** That
> defeats the purpose of a 24/7 host, and it makes the "reboot survival" promised by
> `quadlet/README.md` false as shipped.

Enable linger for the user that will run KAINE:

```bash
sudo loginctl enable-linger <user>
```

Verify:

```bash
loginctl show-user <user> | grep Linger
```

Expected output:

```
Linger=yes
```

If this shows `Linger=no`, stop and fix it — nothing past this point survives a power
cut without it.

## 6. Switch to headless — only after step 2 was verified

**Gate: do not run this step unless the SSH login in step 2 succeeded from another
device.** If it did not, stopping costs you nothing; proceeding may cost you physical
access.

The reference host boots to `graphical.target` with gdm3 active, which costs roughly
2–3 GB of RAM. On an 8 GB unified-memory host, that is a quarter to a third of the
budget spent rendering a desktop nobody is looking at. A dedicated host has no use for a
desktop session.

Switch the default boot target and reboot:

```bash
sudo systemctl set-default multi-user.target
sudo reboot
```

After the reboot — over SSH; from here on you should not need the physical console —
verify three things.

The default target took:

```bash
systemctl get-default
```

Expected output:

```
multi-user.target
```

The performance profile persisted — this is the reboot check from step 1 (Jetson worked
example):

```bash
nvpmodel -q
```

Expected output:

```
NV Power Mode: MAXN_SUPER
```

The desktop's memory came back:

```bash
free -h
```

Expected (representative; exact values vary by host):

```
               total        used        free      shared  buff/cache   available
Mem:           6.8Gi       1.4Gi       4.6Gi        56Mi       812Mi       5.2Gi
Swap:           16Gi         0B         16Gi
```

What you are confirming: `available` is roughly 2–3 GiB higher than it was under the
desktop session, and the 16 GiB swapfile from step 4 is present.

(If you ever need the desktop back on this host:
`sudo systemctl set-default graphical.target && sudo reboot`.)

## 7. Reach the dashboard over the private network

KAINE ships bound to loopback — `[nexus] host = "127.0.0.1"` in `config/kaine.toml`, and
`PublishPort=127.0.0.1:8088:8088` in `quadlet/kaine-nexus.container` — which is correct,
and also means the dashboard is unreachable from any other device.

The obvious fix is the wrong one. Widening the bind to `0.0.0.0` exposes the port on
every interface the host has and throws away loopback as defence in depth. Keep the
loopback bind exactly as it is and **proxy in** from the private network instead.

**Worked path — Tailscale.** The reference host already runs Tailscale, so
`tailscale serve` fronts the existing loopback bind with a tailnet HTTPS URL (Tailscale
provisions the certificate for the node's MagicDNS name automatically). No KAINE config
change, no quadlet change:

```bash
sudo tailscale serve --bg 8088
```

Verify:

```bash
tailscale serve status
```

Expected output (names vary with your tailnet):

```
https://<host>.<tailnet>.ts.net (proxying to http://127.0.0.1:8088)
```

The URL is stable in the way an IP address is not: MagicDNS names persist even when the
node's 100.x address changes, so bookmarks and automations keep working. The serve
configuration also persists across reboots.

On a host without Tailscale, the same invariant holds with any private-network proxy —
for example an SSH local forward from your workstation
(`ssh -L 8088:127.0.0.1:8088 <user>@<host>`) or a reverse proxy bound only to the
private interface. The invariant is the point: the KAINE process keeps its loopback
bind; access is proxied, never widened.

> **Privacy consequence.** Serving the dashboard over a tailnet makes it reachable from
> **every device on the tailnet**, not just yours. `[nexus] dev_content_override` must
> stay `false` — it gates raw message text, beliefs, memory bodies, internal speech, and
> affect reasons — and `conversation_enabled` should stay `false` unless you have
> deliberately decided otherwise.

Verify the config:

```bash
grep -E 'dev_content_override|conversation_enabled' config/kaine.toml
```

Expected output:

```
dev_content_override = false
conversation_enabled = false
```

## The invariants behind these steps

The seven steps above guarantee a small set of invariants: remote access is proven from
another device before the host is made headless, the performance profile survives every
reboot, rootless services start at boot with no human present, swap exists as an OOM
safety valve with low swappiness, KAINE services keep their loopback binds with access
proxied rather than widened, dashboard content exposure stays gated on any shared
network, and the procedure remains platform-general. These are normative statements and
are deliberately not restated here: the single source of truth for them is the openspec
capability `headless-host-operations`
(`openspec/changes/headless-host-operations/specs/headless-host-operations/spec.md`).
This runbook is operator procedure only.

## Verification checklist: after a power cut

Run this after any unplanned power loss. Every line should pass; a failure points at the
step above that owns it.

```bash
# --- on the host, over SSH ---

systemctl get-default                              # expect: multi-user.target
nvpmodel -q                                        # expect: NV Power Mode: MAXN_SUPER
                                                   #         (Jetson worked example —
                                                   #         substitute your platform's step-1 check)
swapon --show                                      # expect: /swapfile  file  16G
cat /proc/sys/vm/swappiness                        # expect: 10
loginctl show-user "$USER" | grep Linger           # expect: Linger=yes
systemctl --user list-units 'kaine-*' --no-pager   # expect: every unit active (running)
tailscale serve status                             # expect: https://<host>.<tailnet>.ts.net
                                                   #         proxying to http://127.0.0.1:8088
```

Unit names follow the files in `quadlet/` (`kaine-nexus.container` generates
`kaine-nexus.service`); run the user-unit check as the user that owns the KAINE
services.

Then, from another device:

```bash
ssh <user>@<host>        # expect: an interactive shell — remote access survived
```

and open the `https://<host>.<tailnet>.ts.net` URL from the `tailscale serve status`
output — the dashboard should load.

If every line passes, the host came back the way this runbook intends: headless, at full
performance, services up, nobody present. If any line fails, the fix is in the
corresponding step above — this checklist is the runbook compressed into regression
form.
