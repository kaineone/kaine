## Why

The quadlet units cannot be installed anywhere except one path, and the ones that need
secrets cannot get them after a reboot.

- **Hard-coded path.** `kaine-cycle.container` and `kaine-nexus.container` bind-mount
  `%h/projects/kaine/config/...`. A checkout anywhere else mounts files that do not exist
  and the containers fail to start. Quadlet resolves `Volume=` when it generates the unit,
  so the path cannot come from a variable; it has to be written into the unit at install.
- **Secrets never reach systemd.** The units expand `${KAINE_REDIS_PASSWORD}`,
  `${KAINE_QDRANT_API_KEY}` and `${KAINE_STATE_KEY}` from the service environment, but
  nothing provides one. The README says to `export` them in a shell, which never reaches
  the systemd user manager, and nothing survives a reboot. After a power cut Redis would
  start with an empty password argument and every dependent unit would fail.
- **The cycle unit cannot see the operator's presence claim.** The documented start sets
  `KAINE_CYCLE_OPERATOR_PRESENT=1` with `systemctl --user set-environment`, but the
  container only receives variables listed in its unit, so the cycle always refuses with
  exit 2.

## What Changes

- The two host-path mounts use a placeholder, `@KAINE_ROOT@`, instead of
  `%h/projects/kaine`.
- A new `scripts/install-quadlet.sh` renders the units into the user's quadlet directory
  (`${XDG_CONFIG_HOME:-~/.config}/containers/systemd`), replacing the placeholder with the
  checkout's absolute path. It refuses a path with characters that break a unit line,
  refuses when `config/kaine.operator.toml`, `config/secrets.toml` or `compose/.env` is
  missing, never installs a unit whose name contains `unattended`, never enables or starts
  anything, and prints the next steps.
- Every unit that expands a secret gets `[Service] EnvironmentFile=@KAINE_ROOT@/compose/.env`,
  the file the bootstrap scripts already maintain (mode 0600). systemd reads it at every
  start, so a rotated credential takes effect on the next restart and there is no second
  copy of any secret.
- `kaine-cycle.container` passes `KAINE_CYCLE_OPERATOR_PRESENT=${KAINE_CYCLE_OPERATOR_PRESENT}`
  into the container, so the documented `set-environment` start works and an unset flag
  still refuses. The unit still has no `[Install]` section.
- `quadlet/README.md` and the deployment docs describe the script instead of `cp` and
  `export`.

## Capabilities

### New Capabilities
- `quadlet-install`: rendering the quadlet units for a checkout at any path, and how the
  units receive secrets and the operator's presence claim.

### Modified Capabilities
- (none)

## Impact

- `quadlet/kaine-cycle.container`, `quadlet/kaine-nexus.container`,
  `quadlet/kaine-redis.container`, `quadlet/kaine-qdrant.container`, `quadlet/README.md`
- New `scripts/install-quadlet.sh`
- `docs/deployment-containers.md`, `docs/deployment-headless-host.md`
- `tests/test_container_deployment.py`, new `tests/test_install_quadlet.py`
- Prerequisite for the unattended unit in `unattended-boot-via-safety-net`.
