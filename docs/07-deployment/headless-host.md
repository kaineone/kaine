# A dedicated headless host

This runbook turns a Linux machine into a KAINE host that runs continuously without a person at it. Read it if you plan to leave KAINE running without a local display and keyboard for days or weeks. Installing KAINE and bringing up its services are covered in [Getting started](../04-getting-started/README.md) and [Supporting services](../04-getting-started/services.md); this page is about making that install survive reboots and power cuts. For the other deployment shapes, see [Choosing a deployment](./README.md).

KAINE's standard target is a dual-GPU x86_64 workstation, and nothing here requires particular hardware. Platform-specific commands appear only inside worked examples, and everything else applies to any Linux host.

Verify remote SSH access in step 2 before you switch to a headless boot target in step 6. Doing these out of order is the one mistake in this runbook that can cost you physical access to the machine.

`scripts/prepare-headless-host.sh` automates steps 1 to 6 with a single `sudo` prompt. Run it as your normal user without `sudo`. It is idempotent, reports OK, SKIPPED or FAILED for each step, and never reboots the host. Its options:

| Option | Effect |
|---|---|
| `--phase1` | The default. Steps 1 to 5: Jetson power-profile persistence, SSH, Python tooling, swap, Podman and linger. Safe on the local console. |
| `--phase2` | Step 6: `systemctl set-default multi-user.target`. Refused unless the session is over SSH (`$SSH_CONNECTION` is set) and the SSH unit is both enabled and active. |
| `--all` | Phase 1, then phase 2, with the same phase-2 check. |
| `--dry-run` | Prints every action without performing any. |
| `--swap-size SZ` | Size of `/swapfile` (default `16G`). |
| `--serve-nexus` | With `--phase2` or `--all`, runs `tailscale serve --bg 8088` when Tailscale is installed and up. |

The script does not create the Redis and Qdrant credentials or install the quadlet units. Do those by hand as described in step 5.

## Before you start

You need:

- sudo on the host;
- the KAINE repository, including `scripts/install.sh`, `quadlet/` and `config/kaine.toml`;
- a second device, such as a laptop on the same network or tailnet, to verify step 2.

Each step ends with a verification. Do not mark a step done until its verification passes.

## 1. Make the performance profile persist

A performance profile set only at runtime resets at reboot. A host that runs around the clock needs the profile to be correct after every boot with no one involved, so the verification that matters is the one after a reboot.

On any host:

1. Find the platform's performance or power mechanism: CPU governor, firmware power profile or vendor power daemon.
2. Set the profile you want.
3. Write it into the boot-time default as well as the runtime state.
4. Reboot and check again.

### Worked example: NVIDIA Jetson with nvpmodel

This example was verified on an Orin Nano Super running Ubuntu 24.04. `nvpmodel` selects power modes; on this board `0` is 15 W, `1` is 25 W and `2` is MAXN_SUPER. The live mode and the boot-time default are stored in different places. `nvpmodel -q` can report MAXN_SUPER while `/etc/nvpmodel.conf` still carries `DEFAULT=1`, and the next reboot then drops the host to 25 W without any message.

Check both:

```bash
nvpmodel -q
grep '^< PM_CONFIG' /etc/nvpmodel.conf
```

If `nvpmodel -q` says MAXN_SUPER but the grep shows `< PM_CONFIG DEFAULT=1 >`, the host is running a setting it will not keep. Fix the default:

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

The real verification happens after the next reboot. Step 6 reboots, or you can reboot now for earlier proof:

```bash
nvpmodel -q
```

Expected output:

```
NV Power Mode: MAXN_SUPER
```

If it reports `25W` after the reboot, persistence failed. Stop and fix it before continuing. To set the live mode as well as the default, run `sudo nvpmodel -m 2`.

## 2. Enable remote access and prove it works

Every later step makes the host headless. If SSH is enabled but a firewall rule, a key or the unit name is wrong, you find out from a machine with no display attached, and recovery means bringing a monitor and keyboard to it. An enabled service does not prove that you can log in, so this step ends with a real login from another device.

Enable and start SSH:

```bash
sudo systemctl enable --now ssh
```

Debian and Ubuntu name the unit `ssh`; RHEL and Fedora name it `sshd`. If a host firewall is active, allow the port before you continue.

Verify that the service is running and will start at boot:

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

If the login fails, stop here and fix it while you still have a keyboard attached.

## 3. Install the Python tooling the installer needs

`scripts/install.sh` builds KAINE's virtual environment itself (`.venv` in the repository), so you need no system-wide pip. On Ubuntu 24.04 you could not use one anyway, because the system Python is marked externally managed (PEP 668) and pip refuses to install into it.

The trap is `python3-venv`. Ubuntu ships `ensurepip`, the module that installs pip into a new virtual environment, in that separate package. Without it, `python3 -m venv --help` works but creating a real environment fails, so the verification below creates one.

Install the Debian or Ubuntu packages. On other distributions, install the equivalents for venv and ensurepip support, the Python headers and a C toolchain:

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev build-essential
```

Verify by creating an environment:

```bash
python3 -m venv /tmp/kaine-venv-probe && /tmp/kaine-venv-probe/bin/pip --version && rm -rf /tmp/kaine-venv-probe
```

Expected: a `pip ...` version line and no traceback. If you see `ensurepip is not available`, `python3-venv` did not install.

## 4. Configure swap as an OOM safety valve

A host that keeps model weights resident around the clock needs swap. Without it, memory pressure ends with the kernel's OOM killer choosing a process to kill, possibly KAINE. With swap present and swappiness low, the kernel pages out cold memory instead.

First confirm that no swap exists:

```bash
swapon --show
```

Expected output: nothing, meaning no partition, file or zram device. The script skips this step when any swap is already active.

### Swapfile or zram

NVIDIA's usual Jetson advice is zram, which assumes slow eMMC storage. zram gains swap capacity by compressing pages in RAM, which costs CPU time and memory. On a host whose scarce resource is RAM and whose job is keeping model weights resident, a swapfile on fast NVMe is the better choice: it costs nothing while idle and adds no compression load. Where storage is slow (eMMC or an SD card), zram is still the better choice.

The reference host has 8 GB of unified memory shared by CPU and GPU and hundreds of GB free on NVMe, so a large file is cheap. Create a 16 GB swapfile:

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

Set swappiness low, first live and then persisted, so that swap stays a safety valve:

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

If `swapon` rejects the file (btrfs and some XFS configurations do not accept a swapfile made with `fallocate`), create it with `sudo dd if=/dev/zero of=/swapfile bs=1M count=16384 status=progress` and repeat the `mkswap` and `swapon` steps.

## 5. Container runtime and reboot survival

This step closes two separate gaps. The second, linger, is the one that usually causes outages.

### Podman

KAINE's quadlet units need Podman 4.4 or newer, the first version that ships quadlet. The reference host had only Docker, and the Ubuntu 24.04 package, 4.9.3, is new enough:

```bash
sudo apt install -y podman
```

Verify:

```bash
podman --version
```

Expected output (4.4 or newer):

```
podman version 4.9.3
```

For the container topology, see [Containers](./containers.md).

### Linger

KAINE's rootless services run as systemd user units, which quadlet generates (see `quadlet/README.md`). User units start at boot only when the user has linger enabled. Without linger, the user's service manager stops at logout and does not start at boot, so after a power cut every service stays down until someone logs in.

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

If this shows `Linger=no`, stop and fix it, because nothing after this point survives a power cut without it.

### Install the units

The units need the bus and vector-store credentials, the operator config and the checkout's location. `install-quadlet.sh` refuses to run while `config/kaine.operator.toml`, `config/secrets.toml` or `compose/.env` is missing. Create the operator config, empty if you have no overrides yet, then create the credentials. The bootstrap scripts write them to `compose/.env` (mode 0600), which the units read at every start, and to `config/secrets.toml`. The bootstraps also start Redis and Qdrant themselves, which can occupy ports 6479 and 6533; stop whatever they started before you start the quadlet units.

```bash
touch config/kaine.operator.toml
bash scripts/redis-bootstrap.sh
bash scripts/qdrant-bootstrap.sh
```

Then render the units into `~/.config/containers/systemd/` and start the services:

```bash
bash scripts/install-quadlet.sh
systemctl --user daemon-reload
systemctl --user start kaine-redis kaine-qdrant kaine-nexus
```

The script writes the checkout's absolute path into the units and refuses a path with spaces or other characters that would break a unit line. It checks the rendered units with Podman's quadlet generator before installing them (`--dry-run` renders and checks without writing; `--root` and `--dest` choose another checkout or destination). It never enables or starts a unit, and it never installs `kaine-cycle-unattended.container`. Run it again after moving the checkout.

The data, model, voice and Nexus units carry `[Install] WantedBy=default.target`, so with linger they start at boot. `kaine-cycle.container` has no `[Install]` section and `Restart=no`, so the entity starts only when you start it:

```bash
systemctl --user set-environment KAINE_CYCLE_OPERATOR_PRESENT=1
systemctl --user start kaine-cycle
```

The `kaine-chatterbox` unit uses the image `kaine-chatterbox:local`, which you must build yourself; until it exists, that unit fails to start.

## 6. Switch to headless only after step 2 was verified

Do not run this step unless the SSH login in step 2 succeeded from another device. If it did not, stopping costs you nothing, and proceeding may cost you physical access.

The reference host boots to `graphical.target` with gdm3 active, which uses roughly 2 to 3 GB of RAM. On an 8 GB unified-memory host, that is a quarter to a third of the memory spent on a desktop no one looks at.

Switch the default boot target and reboot:

```bash
sudo systemctl set-default multi-user.target
sudo reboot
```

After the reboot, log in over SSH and verify three things.

The default target took effect:

```bash
systemctl get-default
```

Expected output:

```
multi-user.target
```

The performance profile persisted (the reboot check from step 1, Jetson example):

```bash
nvpmodel -q
```

Expected output:

```
NV Power Mode: MAXN_SUPER
```

The desktop's memory is free:

```bash
free -h
```

Representative output (values vary by host):

```
               total        used        free      shared  buff/cache   available
Mem:           6.8Gi       1.4Gi       4.6Gi        56Mi       812Mi       5.2Gi
Swap:           16Gi         0B         16Gi
```

Confirm that `available` is roughly 2 to 3 GiB higher than it was under the desktop session and that the 16 GiB swapfile from step 4 is present.

To restore the desktop later, run `sudo systemctl set-default graphical.target && sudo reboot`.

## 7. Reach the dashboard over the private network

Nexus listens on loopback by default: `[nexus].host = "127.0.0.1"` in `config/kaine.toml`, and `PublishPort=127.0.0.1:8088:8088` in `quadlet/kaine-nexus.container`. No other device can reach it. The shipped `[nexus].access` is `"open"` (no token) because the dashboard is reachable only from the host.

Do not widen the bind to `0.0.0.0`, which would expose the port on every interface the host has. Keep the loopback bind and proxy to it from the private network.

### Worked path: Tailscale

The reference host runs Tailscale, so `tailscale serve` puts a tailnet HTTPS address in front of the loopback port, and Tailscale provisions the certificate for the node's MagicDNS name.

Nexus refuses a request whose `Host` header is not in `[nexus].host_allowlist` or whose `Origin` is not allowed, so the tailnet name must be added to both. The image contains `config/kaine.toml`, and the quadlet unit mounts only `config/kaine.operator.toml` and `config/secrets.toml` from the checkout, so configuration changes go in `config/kaine.operator.toml`. The unit sets `KAINE_NEXUS_ALLOWED_ORIGINS` itself, which overrides any `allowed_origins` in TOML, so the origin goes in the unit.

In `config/kaine.operator.toml`, add the tailnet hostname to `host_allowlist` and keep the loopback names:

```toml
[nexus]
host_allowlist = ["127.0.0.1", "localhost", "::1", "myhost.tail1234.ts.net"]
```

In `quadlet/kaine-nexus.container`, add the HTTPS origin to `KAINE_NEXUS_ALLOWED_ORIGINS`:

```ini
Environment=KAINE_NEXUS_ALLOWED_ORIGINS=http://127.0.0.1:8088,http://localhost:8088,https://myhost.tail1234.ts.net
```

Render the units again and restart Nexus:

```bash
bash scripts/install-quadlet.sh
systemctl --user daemon-reload
systemctl --user restart kaine-nexus
```

If the tailnet includes devices or people you do not fully trust, switch to token access. Set `[nexus].access = "token"` in `config/kaine.operator.toml` and put the token, at least 32 characters, under `[nexus]` as `operator_token` in `config/secrets.toml`; both files are mounted into the container. A token set only in `compose/.env` does not reach the quadlet container, because the unit passes only the variables named on its `Environment=` lines. Restart Nexus afterwards.

Then start the proxy:

```bash
sudo tailscale serve --bg 8088
```

Verify:

```bash
tailscale serve status
```

Expected output (names depend on your tailnet):

```
https://<host>.<tailnet>.ts.net (proxying to http://127.0.0.1:8088)
```

The MagicDNS name stays the same when the node's 100.x address changes, so bookmarks keep working, and the serve configuration persists across reboots.

On a host without Tailscale, use any proxy on the private network, for example an SSH local forward from your workstation (`ssh -L 8088:127.0.0.1:8088 <user>@<host>`) or a reverse proxy bound only to the private interface. Nexus keeps its loopback bind in every case.

### Privacy consequence

Serving the dashboard over a tailnet makes it reachable from every device on the tailnet. Keep `[nexus].dev_content_override` at `false`, because it gates raw message text, beliefs, memory bodies, inner speech and affect reasons. Keep `conversation_enabled` at `false` unless you have deliberately decided otherwise. Both are `false` in the shipped `config/kaine.toml`, and the `thesis_test` profile does not change them.

Verify the shipped values:

```bash
grep -E '^(dev_content_override|conversation_enabled) =' config/kaine.toml
```

Expected output:

```
conversation_enabled = false
dev_content_override = false
```

Check `config/kaine.operator.toml` as well, because it overrides both. For more on these settings, see [Nexus, the dashboard](../05-nexus.md) and [Security and privacy](../13-security-and-privacy.md).

## What these steps establish

After the seven steps:

- remote access has been proven from another device before the host became headless;
- the performance profile survives every reboot;
- the rootless services start at boot with no one logged in;
- swap exists as an OOM safety valve with low swappiness;
- KAINE's services keep their loopback binds, and access to them is proxied;
- the dashboard's content gates stay closed on a shared network.

The requirements behind these steps are specified in the OpenSpec capability `headless-host-operations` (`openspec/specs/headless-host-operations/spec.md`). This page is the operator procedure.

## Verification checklist after a power cut

Run this after any unplanned power loss. Every line should pass, and a failure points to the step above that owns it.

```bash
# --- on the host, over SSH ---

systemctl get-default                              # expect: multi-user.target
nvpmodel -q                                        # expect: NV Power Mode: MAXN_SUPER
                                                   #         (Jetson example; use your
                                                   #         platform's step-1 check)
swapon --show                                      # expect: /swapfile  file  16G
cat /proc/sys/vm/swappiness                        # expect: 10
loginctl show-user "$USER" | grep Linger           # expect: Linger=yes
systemctl --user list-units 'kaine-*' --no-pager   # expect: every service active (running)
                                                   #         except kaine-cycle, which only
                                                   #         a person starts
tailscale serve status                             # expect: https://<host>.<tailnet>.ts.net
                                                   #         proxying to http://127.0.0.1:8088
```

Unit names follow the files in `quadlet/`: `kaine-nexus.container` generates `kaine-nexus.service`. Run the user-unit check as the user that owns the KAINE services.

Then, from another device:

```bash
ssh <user>@<host>        # expect: an interactive shell
```

Open the `https://<host>.<tailnet>.ts.net` address from the `tailscale serve status` output, and the dashboard should load. If any line fails, the fix is in the corresponding step above.
