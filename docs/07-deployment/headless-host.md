# A dedicated headless host

This runbook turns a Linux machine into an unattended, continuously running KAINE host. Read it if you plan to leave KAINE running without a local display and keyboard for days or weeks. Installing KAINE and bringing up its services are covered in [Getting started](../04-getting-started/README.md) and [Supporting services](../04-getting-started/services.md); this page is about making that install survive reboots and power cuts. For the other deployment shapes, see [Choosing a deployment](./README.md).

KAINE's standard target is the dual-GPU x86_64 workstation; nothing here changes that, and nothing here requires particular hardware. Platform-specific commands appear only inside **worked example** callouts; everything else is general.

**The order matters.** Verify remote SSH access in step 2 before you switch to a headless boot target in step 6. Skipping that order is the one mistake in this runbook that can cost you physical access to the machine.

`scripts/prepare-headless-host.sh` automates the safe preparation work in steps 1–5 up to Podman and linger, with a single `sudo` prompt. It is idempotent, reports OK / SKIPPED / FAILED for each step, and refuses phase 2 unless the session is over SSH and the ssh unit is both enabled and active. Use `--dry-run` to preview every action, `--phase1` for the safe preparation steps, `--phase2` for the headless switch, `--all` for both, and `--serve-nexus` to opt in to `tailscale serve --bg 8088` for dashboard reachability. The script also accepts `--swap-size` (for example `--swap-size 16G`) to set the swapfile size. It does not bootstrap Redis/Qdrant credentials, run `install-quadlet.sh`, switch the boot target, or set up dashboard reachability; run those steps manually.

## Before you start

You need:

- sudo on the host
- the KAINE repo present, including `scripts/install.sh`, `quadlet/`, and `config/kaine.toml`
- a second device — a laptop on the same network or tailnet — to verify step 2

Each step ends with a verification. Do not mark a step done until its verification passes.

## 1. Make the performance profile persist

A performance profile set only at runtime resets at reboot. The property a 24/7 host needs is "the profile is correct after every boot, with no human involved." The verification that matters is always *after a reboot*.

On any host:

1. Find the platform's performance/power mechanism: CPU governor, firmware power profile, or vendor power daemon.
2. Set the profile you want.
3. Write it into the boot-time default, not just the runtime state.
4. Reboot and check again.

### Worked example: NVIDIA Jetson with nvpmodel

The Jetson example was verified on an Orin Nano Super running Ubuntu 24.04. `nvpmodel` selects power modes; on this board `0` = 15 W, `1` = 25 W, and `2` = MAXN_SUPER. The live mode and the boot-time default live in different places. `nvpmodel -q` can report MAXN_SUPER while `/etc/nvpmodel.conf` still carries `DEFAULT=1`. The next reboot then drops the host to 25 W silently.

Check both, separately:

```bash
nvpmodel -q
grep '^< PM_CONFIG' /etc/nvpmodel.conf
```

If `nvpmodel -q` says MAXN_SUPER but the grep says `< PM_CONFIG DEFAULT=1 >`, the host is running a setting it will not keep. Fix the default:

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

The real verification happens after the next reboot (step 6 reboots; if you want the proof sooner, reboot now):

```bash
nvpmodel -q
```

Expected output:

```
NV Power Mode: MAXN_SUPER
```

If it reports `25W` after reboot, persistence failed. Stop and fix it before continuing. To set the live mode as well as the default, run `sudo nvpmodel -m 2`.

## 2. Enable remote access and prove it works

Everything after this point makes the host headless. If SSH is enabled but does not actually work — missing firewall rule, wrong key, wrong unit name — you will find out from a machine with no display attached, and the recovery is a physical trip with a monitor and keyboard. Enabling a service is not the same as being able to log in, so this step ends with an actual login from another device.

Enable and start SSH:

```bash
sudo systemctl enable --now ssh
```

Debian/Ubuntu name the unit `ssh`; RHEL/Fedora name it `sshd`. If a host firewall is active, allow the port before you continue.

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

### Blocking verification

From a different device:

```bash
ssh <user>@<host>
```

You should get an interactive shell on the host.

If the login fails, stop here and fix it while you still have a keyboard attached. Performing the headless switch in step 6 with unverified SSH turns a routine conversion into a monitor-and-keyboard recovery trip.

## 3. Install the Python tooling the installer needs

`scripts/install.sh` builds KAINE's virtual environment itself (`.venv` in the repo), so you need no system-wide pip. On Ubuntu 24.04 you cannot use one anyway: the system Python is PEP 668 "externally managed", and pip refuses to install into it.

The trap is `python3-venv`. `python3 -m venv --help` succeeding proves nothing: Ubuntu splits `ensurepip` — the module that bootstraps pip inside a new venv — into the `python3-venv` package. Without it, `--help` works but every real `python3 -m venv` creation fails. The verification below creates an actual venv.

Install the Debian/Ubuntu packages; on other distributions install the equivalents for venv/ensurepip support, Python headers, and a C toolchain:

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev build-essential
```

Verify by doing the thing that fails when the package is missing:

```bash
python3 -m venv /tmp/kaine-venv-probe && /tmp/kaine-venv-probe/bin/pip --version && rm -rf /tmp/kaine-venv-probe
```

Expected: a `pip 24.0 ...` version line and no traceback. If you see `ensurepip is not available`, `python3-venv` did not actually install.

## 4. Configure swap as an OOM safety valve

A 24/7 host running model weights needs swap. With none, memory pressure ends with the kernel's OOM killer choosing a victim — possibly KAINE — at the worst moment. With swap present and swappiness low, the kernel pages out cold memory instead.

First confirm the gap:

```bash
swapon --show
```

Expected output: nothing at all — no partition, no file, no zram.

### Why a swapfile and not zram

NVIDIA's standard Jetson advice is zram, but that advice assumes slow eMMC storage. zram buys swap capacity by compressing pages, which spends CPU and RAM. On a host whose scarce resource is RAM and whose purpose is keeping model weights resident, that is the wrong trade when fast NVMe is available: a swapfile on NVMe costs nothing at idle and adds no compression load. zram remains the right choice where storage is slow (eMMC, SD card). This is a storage-speed decision, not a universal rule.

The reference host has 8 GB of unified memory shared by CPU and GPU, with hundreds of GB free on NVMe, so a generous file is cheap. Create a 16 GB swapfile:

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

Set swappiness low, live first and then persisted, so swap stays a safety valve rather than a hot path:

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

If `swapon` rejects the file — btrfs and some XFS configurations disallow `fallocate`d swap files — create it with `sudo dd if=/dev/zero of=/swapfile bs=1M count=16384 status=progress` and repeat the `mkswap` and `swapon` steps.

## 5. Container runtime and reboot survival

Two independent gaps here, and the second is the one that usually causes outages.

### Podman

KAINE's quadlet units need Podman >= 4.4, the version where quadlet shipped inside Podman. The reference host had only Docker; Ubuntu 24.04's candidate, 4.9.3, is sufficient:

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

For the full container picture, see [Containers](./containers.md).

### Linger

Without linger, "reboot survival" is false. KAINE's rootless services run as systemd user units (quadlet generates user units; see `quadlet/README.md`). Rootless user units do not start at boot unless the user has linger enabled. Without it, the user's service manager is torn down at logout and never starts at boot.

> Without linger, a power cut leaves every service down until a human logs in. That defeats the purpose of a 24/7 host, and it makes the reboot survival promised by the quadlet setup false.

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

If this shows `Linger=no`, stop and fix it. Nothing past this point survives a power cut without it.

### Install the units

The units need the bus and vector-store credentials, an operator config file, and the checkout's location. `install-quadlet.sh` refuses to run if `config/kaine.operator.toml` is missing. Create it, even empty, if you have no operator overrides yet. Then create the credentials. The bootstrap scripts write them to `compose/.env` (mode 0600), which the units read at every start. The bootstraps also start Redis and Qdrant themselves, so they may occupy ports 6479 and 6533 before the quadlet units start; stop any native `redis-server` or Docker Compose stack they started before you start the quadlet units.

```bash
touch config/kaine.operator.toml
bash scripts/redis-bootstrap.sh
bash scripts/qdrant-bootstrap.sh
```

Then render the units into `~/.config/containers/systemd/`:

```bash
bash scripts/install-quadlet.sh
systemctl --user daemon-reload
systemctl --user start kaine-redis kaine-qdrant kaine-nexus
```

The script writes this checkout's absolute path into the units. It refuses a path containing spaces or characters that break a unit line, refuses if `config/kaine.operator.toml`, `config/secrets.toml`, or `compose/.env` is missing, and checks the rendered units with Podman's quadlet generator before installing them. It never enables or starts anything, and it never installs the entity unit's unattended variant. Re-run it after moving the checkout.

## 6. Switch to headless only after step 2 was verified

Do not run this step unless the SSH login in step 2 succeeded from another device. If it did not, stopping costs you nothing; proceeding may cost you physical access.

The reference host boots to `graphical.target` with gdm3 active, which costs roughly 2–3 GB of RAM. On an 8 GB unified-memory host, that is a quarter to a third of the budget spent rendering a desktop nobody is looking at. A dedicated host has no use for a desktop session.

Switch the default boot target and reboot:

```bash
sudo systemctl set-default multi-user.target
sudo reboot
```

After the reboot — over SSH; from here on you do not need the physical console — verify three things.

The default target took:

```bash
systemctl get-default
```

Expected output:

```
multi-user.target
```

The performance profile persisted — this is the reboot check from step 1 (Jetson worked example):

```bash
nvpmodel -q
```

Expected output:

```
NV Power Mode: MAXN_SUPER
```

The desktop's memory is freed:

```bash
free -h
```

Expected (representative; values vary by host):

```
               total        used        free      shared  buff/cache   available
Mem:           6.8Gi       1.4Gi       4.6Gi        56Mi       812Mi       5.2Gi
Swap:           16Gi         0B         16Gi
```

Confirm that `available` is roughly 2–3 GiB higher than it was under the desktop session and that the 16 GiB swapfile from step 4 is present.

To restore the desktop later, run `sudo systemctl set-default graphical.target && sudo reboot`.

## 7. Reach the dashboard over the private network

KAINE binds Nexus to loopback by default — `[nexus] host = "127.0.0.1"` in `config/kaine.toml`, and `PublishPort=127.0.0.1:8088:8088` in `quadlet/kaine-nexus.container` — which is correct, and also means the dashboard is unreachable from any other device. The shipped `[nexus].access` is `"open"` (no token) because Nexus only listens on loopback.

Do not widen the bind to `0.0.0.0`. That exposes the port on every interface the host has and throws away loopback as defence in depth. Keep the loopback bind exactly as it is and proxy in from the private network instead.

### Worked path: Tailscale

The reference host already runs Tailscale, so `tailscale serve` fronts the existing loopback bind with a tailnet HTTPS URL. Tailscale provisions the certificate for the node's MagicDNS name automatically.

The quadlet unit bakes `config/kaine.toml` into the image and bind-mounts only `config/kaine.operator.toml`, so operator overrides go in `config/kaine.operator.toml`. The unit also sets `KAINE_NEXUS_ALLOWED_ORIGINS`, which overrides any TOML `allowed_origins`. You must change both files.

In `config/kaine.operator.toml`, under `[nexus]`, add the tailnet hostname to `host_allowlist`. Keep the loopback names; Nexus refuses requests whose `Host` header is not in the list:

```toml
[nexus]
host_allowlist = ["127.0.0.1", "localhost", "::1", "myhost.tail1234.ts.net"]
```

In `quadlet/kaine-nexus.container`, add the HTTPS origin to the `KAINE_NEXUS_ALLOWED_ORIGINS` environment variable:

```ini
Environment=KAINE_NEXUS_ALLOWED_ORIGINS=http://127.0.0.1:8088,http://localhost:8088,https://myhost.tail1234.ts.net
```

Re-render and restart Nexus:

```bash
bash scripts/install-quadlet.sh
systemctl --user daemon-reload
systemctl --user restart kaine-nexus
```

Once Nexus is reachable over the tailnet, switch to `"token"` access mode and set an operator token if the tailnet includes devices or people you do not fully trust. Add `Environment=KAINE_NEXUS_ACCESS=token` to `quadlet/kaine-nexus.container`, set `KAINE_NEXUS_TOKEN` in `compose/.env` (or `[nexus] operator_token` in `config/secrets.toml` for native launches), then re-render and restart.

Then start the serve:

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

The URL is stable in a way an IP address is not: MagicDNS names persist even when the node's 100.x address changes, so bookmarks and automations keep working. The serve configuration also persists across reboots.

On a host without Tailscale, the same invariant holds with any private-network proxy — for example an SSH local forward from your workstation (`ssh -L 8088:127.0.0.1:8088 <user>@<host>`) or a reverse proxy bound only to the private interface. The KAINE process keeps its loopback bind; access is proxied, never widened.

### Privacy consequence

Serving the dashboard over a tailnet makes it reachable from every device on the tailnet, not just yours. `[nexus] dev_content_override` must stay `false` — it gates raw message text, beliefs, memory bodies, internal speech, and affect reasons — and `conversation_enabled` should stay `false` unless you have deliberately decided otherwise. Both are `false` in the effective default base-thesis `thesis_test` profile.

Verify the config:

```bash
grep -E '^(dev_content_override|conversation_enabled) =' config/kaine.toml
```

Expected output:

```
conversation_enabled = false
dev_content_override = false
```

For more on these gates, see [Nexus, the dashboard](../05-nexus.md) and [Security and privacy](../13-security-and-privacy.md).

## Invariants behind these steps

The seven steps above guarantee:

- remote access is proven from another device before the host is made headless;
- the performance profile survives every reboot;
- rootless services start at boot with no human present;
- swap exists as an OOM safety valve with low swappiness;
- KAINE services keep their loopback binds, with access proxied rather than widened;
- dashboard content exposure stays gated on any shared network;
- the procedure remains platform-general.

The single source of truth for these invariants is the openspec capability `headless-host-operations` (`openspec/changes/headless-host-operations/specs/headless-host-operations/spec.md`). This runbook is operator procedure only.

## Verification checklist after a power cut

Run this after any unplanned power loss. Every line should pass; a failure points at the step above that owns it.

```bash
# --- on the host, over SSH ---

systemctl get-default                              # expect: multi-user.target
nvpmodel -q                                        # expect: NV Power Mode: MAXN_SUPER
                                                   #         (Jetson worked example —
                                                   #         substitute your platform's step-1 check)
swapon --show                                      # expect: /swapfile  file  16G
cat /proc/sys/vm/swappiness                        # expect: 10
loginctl show-user "$USER" | grep Linger           # expect: Linger=yes
systemctl --user list-units 'kaine-*' --no-pager   # expect: every service unit active (running)
                                                   #         except kaine-cycle, which only a person starts
tailscale serve status                             # expect: https://<host>.<tailnet>.ts.net
                                                   #         proxying to http://127.0.0.1:8088
```

Unit names follow the files in `quadlet/` (`kaine-nexus.container` generates `kaine-nexus.service`). Run the user-unit check as the user that owns the KAINE services.

Then, from another device:

```bash
ssh <user>@<host>        # expect: an interactive shell — remote access survived
```

and open the `https://<host>.<tailnet>.ts.net` URL from the `tailscale serve status` output — the dashboard should load.

If every line passes, the host came back the way this runbook intends: headless, at full performance, services up, nobody present. If any line fails, the fix is in the corresponding step above — this checklist is the runbook compressed into regression form.
