# One owner for host memory, one host snapshot per preflight, one definition per service port

## Why

The complexity audit of 2026-10-03 (W6) found the host probes duplicated:
- `kaine.hardware.total_ram_gb` kept its own `sysconf` → `/proc/meminfo` → psutil chain beside `kaine.hostmem`'s `/proc/meminfo` → psutil chain.
- The GPU preflight called `describe_host()` twice per run, once for VRAM and once for the memory state, which probed torch and NVML twice.
- The preflight re-exported `kaine.net.SERVICE_PORTS` under a second name, `KAINE_SERVICE_PORTS`.
- The setup dependency probe wrote the Redis and Qdrant host ports as literals.

## What changes

- **One memory owner.** `kaine.hostmem.system_memory_pool()` gains a last rung: POSIX `sysconf` gives the total when `/proc/meminfo` and psutil both fail, as on macOS without psutil. Available memory is then marked unknown. `hardware.total_ram_gb()` reads that pool instead of keeping a chain of its own.
- **One snapshot per preflight.** `describe_host()` returns a documented `HostSnapshot` (a `TypedDict` naming every key). `run_preflight` takes one snapshot and passes it to both the VRAM read and the memory-state classification.
- **No port alias.** The `KAINE_SERVICE_PORTS` alias is gone, and the preflight reads `SERVICE_PORTS` directly.
- **Port constants.** `kaine/defaults.py` gains `DEFAULT_REDIS_PORT` (6479) and `DEFAULT_QDRANT_PORT` (6533), the host ports of KAINE's own containers. The setup dependency probe and the ignition-study CLI use them.

## Decisions recorded, no code change

- **Organ gate arguments.** The audit asked for one `organ_gate_args(config)` helper. The single-source-defaults change already routes both remaining content-probe call sites (the cycle entry point and preboot) through `lingua_section_chat_url` and `lingua_section_api_key`, and the model-server call sites no longer exist. A further helper would save one three-argument call, so none is added.
- **`KAINE_ALLOW_MUTE_ORGAN`.** It stays a cycle-boot policy only. Preboot reports a mute organ as a failed check for the operator to read, and has nothing to override.
- **Config validation layers stay as three:**
  - `kaine.config.validate_config_shape` checks types and shapes when the config loads, and refuses a malformed config.
  - `boot._require_keys` (through `require_known_keys`) refuses unknown keys in each module's table when the module is built.
  - `preboot.check_config_sanity` reports the boot mode, the enabled modules, the tier fit, the encryption posture and the torch stack to the operator. It reports and never refuses.

  A new check goes in the first layer when it is about shape, in the second when it is about one module's keys, and in the third when it is advice to the operator.
- **`BusConfig.port` defaults to Redis's 6379,** while the shipped config sets 6479. Changing the code default would change how a config without `[bus].port` connects, so it is left as is.
- **Indirect setup imports.** The runtime speech modules' imports of `kaine.setup.speech_models` are handled in a separate change. The Hypnos organ window imports `kaine.setup.model_server` because it drives the model server's process lifecycle, which setup shares on purpose. Moving it means moving that module, `kaine.setup.organ` and `kaine.setup.device_map` out of setup, which is follow-up work.

## Impact

- **Behaviour:** the figures are unchanged. A host where `/proc/meminfo` and psutil both fail now reports its total RAM from `sysconf` instead of nothing. The preflight probes the host once per run instead of twice.
- **Research:** none. No study is running.
