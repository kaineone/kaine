## 1. Pre-flight module (`kaine/cycle/preflight.py`)
- [x] 1.1 `GpuPreflightConfig.from_section` (enabled, min_free_vram_gb, unload_idle_ollama, ollama_url, timeout_s, override_env)
- [x] 1.2 Real probes: per-device free VRAM (describe_host), Ollama `/api/ps` + keep_alive=0 eviction, `nvidia-smi` consumer list, KAINE service port detection
- [x] 1.3 `run_preflight`: check headroom → evict only non-keep KAINE models → re-measure → pass/blocked/overridden; write status snapshot; never kill a process
- [x] 1.4 `read_preflight_state` for read-only display

## 2. Cycle integration (`kaine/cycle/__main__.py`)
- [x] 2.1 Run the gate after config load, BEFORE bus/modules open
- [x] 2.2 Refuse to boot (exit code 4) with the operator message when not ok

## 3. Config (`config/kaine.toml`)
- [x] 3.1 `[gpu_preflight]` section, `enabled = false` (operator-supervised first boot)

## 4. Nexus (`kaine/nexus/health.py`)
- [x] 4.1 Read-only `_gpu_preflight_block()` mapping the snapshot to operator states
- [x] 4.2 Add `gpu_preflight` to the health snapshot

## 5. Tests (`tests/test_gpu_preflight.py`)
- [x] 5.1 config defaults/overrides; disabled→skipped; pass; reclaim keeps organ; blocked; override; snapshot round-trip
- [x] 5.2 never-kills source guard; shipped-config-disabled guard; Nexus block read
- [x] 5.3 Full suite green before PR
