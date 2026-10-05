## 1. Launch paths
- [x] 1.1 compose/kaine.yml: add `--sleep-idle-seconds ${KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS:-600}` to the default model-server command. Document the variable in compose/.env.example, and note that a `KAINE_MODEL_SERVER_CMD` override must pass it.
- [x] 1.2 quadlet/kaine-model-server.container: the same flag, with the variable from the unit's environment and a default of 600.
- [x] 1.3 `kaine.setup.model_server.build_launch_cmd` passes the flag from `[lingua].model_server_sleep_idle_seconds` (default 600, validated as an integer of -1 or more, where -1 disables). Add the key to config/kaine.toml.

## 2. Health
- [x] 2.1 Nexus organ probe and the pre-boot `Chat LLM` row read `/props` `is_sleeping` and report up and asleep. Polling never wakes the organ.

## 3. Verification
- [x] 3.1 Tests: every launch path renders the flag and default; config validation; the probe reports asleep from a fake `/props`; the preboot row.
- [x] 3.2 On the GPU at the next launch, confirm with `nvidia-smi` that the organ's VRAM is released while it sleeps, and record the result in the docs. Confirmed 2026-10-05 on the reference host: the asleep containerized organ held about 210 MiB (the CUDA context only); recorded in `docs/06-operation/README.md` (#362).
- [x] 3.3 Docs (docs/05-nexus.md, deployment docs). The full offline suite is green. The sleep behaviour is documented in `docs/06-operation/README.md`, `docs/04-getting-started/` and `docs/07-deployment/containers.md`; the suite is green on main.
