## 1. Memory
- [x] 1.1 `hostmem.system_memory_pool()` falls back to POSIX `sysconf` for the total, with available memory marked unknown.
- [x] 1.2 `hardware.total_ram_gb()` reads `hostmem.system_memory_pool()`.

## 2. Preflight
- [x] 2.1 `describe_host()` returns a documented `HostSnapshot`.
- [x] 2.2 `run_preflight` takes one snapshot per run and passes it to the VRAM and memory-state probes.
- [x] 2.3 Remove the `KAINE_SERVICE_PORTS` alias.

## 3. Ports
- [x] 3.1 `DEFAULT_REDIS_PORT` and `DEFAULT_QDRANT_PORT` in `kaine/defaults.py`, used by the setup dependency probe and the ignition-study CLI.

## 4. Tests
- [x] 4.1 The sysconf rung, the delegation of `total_ram_gb`, one snapshot per preflight, no alias, no port literals in the dependency probe.
- [x] 4.2 The all-sources-unreadable hostmem test also makes `sysconf` fail.

## 5. Decisions
- [x] 5.1 Record the organ-gate, mute-organ, validation-layer, bus-port and indirect-import decisions in the proposal.
