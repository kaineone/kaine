# KAINE Quadlet units (rootless Podman, production single-host)

Quadlet is the recommended **production** path for a continuously-running
research instrument (design.md §10): each container becomes a rootless-Podman
systemd service with native dependency ordering, logging, restart, and reboot
survival.

## Install (rootless, per-user)

```bash
mkdir -p ~/.config/containers/systemd
cp quadlet/*.container quadlet/*.network ~/.config/containers/systemd/
# secrets + gate flags — never in a unit file:
export KAINE_REDIS_PASSWORD=... KAINE_QDRANT_API_KEY=... KAINE_MODEL_SERVER_API_KEY=...
systemctl --user daemon-reload
systemctl --user start kaine-redis kaine-qdrant kaine-model-server \
                       kaine-speaches kaine-chatterbox kaine-nexus
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
