## 1. Units

- [x] 1.1 Replace `%h/projects/kaine` with `@KAINE_ROOT@` in the cycle and Nexus host-path mounts and in the cycle unit's comment.
- [x] 1.2 Add `[Service] EnvironmentFile=@KAINE_ROOT@/compose/.env` to every unit that expands a `${...}` variable (cycle, Nexus, Redis, Qdrant).
- [x] 1.3 Pass `KAINE_CYCLE_OPERATOR_PRESENT=${KAINE_CYCLE_OPERATOR_PRESENT}` into the cycle container; keep no `[Install]` and `Restart=no`.

## 2. Install script

- [x] 2.1 `scripts/install-quadlet.sh [--root DIR] [--dest DIR] [--dry-run]`: default root is the checkout holding the script, default destination is `${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd`.
- [x] 2.2 Refuse a root that is not absolute or contains characters outside `A-Za-z0-9._/+-` (spaces, `%`, `$`, `:` and quotes break unit lines).
- [x] 2.3 Refuse when `config/kaine.operator.toml`, `config/secrets.toml` or `compose/.env` is missing, naming the bootstrap step that creates each.
- [x] 2.4 Render every `quadlet/*.container`, `*.network` and `*.volume` except names containing `unattended`; verify no placeholder remains; write each file atomically; list what was written; never run `systemctl`.

## 3. Tests and docs

- [x] 3.1 Tests run the script against a fake checkout and a temporary destination: rendered paths, no placeholder left, unsafe roots refused, missing files refused, an `unattended` unit never installed, `--dry-run` writes nothing.
- [x] 3.2 Shipped units carry the placeholder and never `projects/kaine`; every unit that uses `${` has the `EnvironmentFile=` line; the cycle unit passes the presence flag and has no `[Install]`.
- [x] 3.3 `quadlet/README.md`, `docs/deployment-containers.md` and `docs/deployment-headless-host.md` describe the script and the env file instead of `cp` and `export`.
