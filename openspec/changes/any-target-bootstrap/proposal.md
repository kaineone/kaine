# Proposal — `any-target-bootstrap`

## Why

The operator wants the full entity running on this desktop, on a Jetson Orin Nano Super and under Termux on a Pixel 6a, and wants one install entry point for any target. Today:

- **Target detection only checks for `nvidia-smi`.** A Jetson whose `nvidia-smi` is missing or limited falls to CPU wheels, although `kaine.hostmem` already recognises Tegra through `/etc/nv_tegra_release` and the device tree.
- **Android is never detected.** On Termux the installer tries manylinux torch wheels, which cannot work there, and fails obscurely.
- **The installers install no system packages and no Python.**
- **There is no one-line bootstrap.**

## What changes

- **A target probe** (`kaine/install_target.py`, stdlib only): `desktop-cuda`, `desktop-rocm`, `desktop-xpu`, `desktop-cpu`, `jetson` (Tegra, with its JetPack/L4T release and CUDA version), `aarch64-cpu`, `termux` (`TERMUX_VERSION` or a `/data/data/com.termux` prefix), `macos`, or `unsupported` with a reason.
  - `install.sh`/`install.py` use it for the wheel flavor. A Jetson gets the CUDA path even when `nvidia-smi -L` fails, and the self-test still decides.
- **A per-target extras plan.** The target selects the extras from `slim-base-dependencies`:
  - desktops: `full`;
  - Jetson: `full` with the aarch64 cu13x wheel;
  - aarch64 CPU: `full`, CPU torch;
  - Termux: the base plus `memory-edge`, with a plain statement that Soma and Chronos need torch, which has no Termux wheel until the NumPy CfC (phase 2), and that Nous and Phantasia need JAX until phase 3.
  - The installer prints what the host will and will not run before it starts.
- **`scripts/bootstrap.sh`**, a `curl | sh`-able entry point:
  1. check git and Python ≥ 3.11;
  2. print the system-package commands for the host's package manager (`apt`, `dnf`, `pacman`, `pkg`) and run them only with `--yes`. Root is never assumed; the operator runs `sudo` commands themself;
  3. clone or update the repo;
  4. run the installer with the planned extras;
  5. run the native or container service bootstrap (`native-services`);
  6. offer the setup wizard.
  - It never starts the entity.
- **Docs.** A "one command on any host" section in `docs/getting-started.md`, with the per-target table.

## Depends on

- `slim-base-dependencies`, `native-services`.

## Impact

- New `kaine/install_target.py` and `scripts/bootstrap.sh`; installer edits; docs. Existing flags and the desktop default are unchanged.
