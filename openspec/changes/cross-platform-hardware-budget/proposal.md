# Cross-platform hardware budget

## Why

KAINE is installed on machines from a 512 MB single-board host to a multi-GPU
workstation. Today a few hot paths (vision encoder load, the organ loader's
`cuda:0` default, Ollama residency) assume a dedicated GPU and can OOM, stall
the host, or evict another process' model. The predictor has to stay small and
resource-neutral: it scans what is actually free, chooses a pool, and degrades
to CPU or "off" instead of acquiring resources the host has already committed.

## What

A hardware budget layer in `kaine/hardware.py`, wiring through `[hardware]` in
`config/kaine.toml`, used by boot and by module initialization. It is
OS-independent: Linux, Windows, macOS, *BSD and Termux all speak Python, so only
`platform` / `os` / `psutil` / `torch` introspection (no `nvidia-smi`,
`rocm-smi`, or shell `lspci`) drives decisions.

## Scope

In:
- a budget-aware `gpu_inventory()` + `best_device_for(min_vram_mb, ...)`
- `[hardware]` keys with defaults (`max_cpu_pct`, `max_vram_mb_per_device`,
  `reserved_vram_mb`, `torch_num_threads`, `model_cache_mb`)
- fallback plans (CPU, reduced precision, module off) when no GPU fits
- module initialization hooks that consult the budget instead of `cuda:0`
- preboot `WARN` (never `FAIL`) rows for unavailable VRAM
- a short hints section in `docs/03-hardware/README.md`

Out:
- selling / renting / cloud compute or multi-host inference
- containerization
- changing worker ORM behaviour
