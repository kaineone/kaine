# KAINE Quadlet units (rootless Podman, production single-host)

Quadlet is the recommended **production** path for a continuously-running
research instrument (design.md §10): each container becomes a rootless-Podman
systemd service with native dependency ordering, logging, and restart. Reboot
survival holds ONLY when lingering is enabled for the owning user — rootless
systemd USER units do not start at boot otherwise, so after a power cut every
service stays down until a human logs in.

## Install (rootless, per-user)

Run the install script from the checkout. It renders the units into the
user's quadlet directory, substituting `@KAINE_ROOT@` with the checkout's
absolute path:

```bash
bash scripts/install-quadlet.sh
```

The default destination is `${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd`.
Use `--dest DIR` to choose another directory, `--root DIR` to point at a checkout
other than the one containing the script, and `--dry-run` to render and verify
without writing anything:

```bash
bash scripts/install-quadlet.sh --dry-run
bash scripts/install-quadlet.sh --root /srv/kaine --dest ~/.config/containers/systemd
```

Secrets are read by systemd at every start from `compose/.env` (created and
kept up to date by `scripts/redis-bootstrap.sh` and
`scripts/qdrant-bootstrap.sh`). Each unit that expands a `${...}` secret
loads that file through `[Service] EnvironmentFile=`. Never export secrets in a
shell; the systemd user manager does not inherit shell environment.

Enable linger so the services survive logout and reboot:

```bash
sudo loginctl enable-linger $USER
loginctl show-user $USER | grep Linger    # expect Linger=yes
systemctl --user daemon-reload
systemctl --user start kaine-redis kaine-qdrant kaine-nexus
```

The data/model/Nexus units carry `[Install] WantedBy=default.target` so they
come up on login/reboot. **`kaine-cycle.container` has NO `[Install]` section**:
the entity is never auto-started. Boot it deliberately, operator-present:

```bash
systemctl --user set-environment KAINE_CYCLE_OPERATOR_PRESENT=1
systemctl --user start kaine-cycle
```

## GPU (rootless CDI)

Generate the CDI spec once, then the `AddDevice=nvidia.com/gpu=N` lines in the
GPU units take effect:

```bash
nvidia-ctk cdi generate --output=$HOME/.config/cdi/nvidia.yaml
```

Under SELinux add `SecurityLabelDisable=true` (already set on the GPU units) or
relabel volumes with `:Z`. See design §10 for the rootless caveats (subuid/subgid
for the non-root `kaine` uid, loopback port mapping).
