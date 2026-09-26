## 1. Implementation

- [ ] 1.1 `kaine/install_target.py`: the probe (with its Tegra, Termux and flavor rules) and the per-target extras plan.
- [ ] 1.2 `install.sh`/`install.py` use the probe; a Jetson gets the CUDA path without `nvidia-smi`; Termux gets the base plan and a clear statement.
- [ ] 1.3 `scripts/bootstrap.sh`: prerequisites, package commands (run only with `--yes`), clone or update, install, services, wizard; never starts the entity.
- [ ] 1.4 Docs: one command on any host, and the per-target table.

## 2. Verification

- [ ] 2.1 Tests with faked probe inputs (files, env, commands) for every target, including a Jetson without `nvidia-smi` and Termux; the plan per target; bootstrap dry runs per package manager.
- [ ] 2.2 Real runs recorded: this desktop; the Orin Nano Super (the operator runs it on the device); the Pixel 6a under Termux (the operator runs it on the device, to the documented limit).
- [ ] 2.3 Offline suite green; `openspec validate any-target-bootstrap --strict`.
