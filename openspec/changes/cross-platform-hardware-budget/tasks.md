## 1. Habitat discovery (code)
- [ ] 1.1 `kaine.hardware`: `gpu_inventory()` (no shell, pynvml/`torch.cuda`/MPS/XPU, each device's total and free VRAM reported; `None` when no library supports it, never a boot error).
- [ ] 1.2 `kaine.hardware`: `best_device_for(min_vram_mb, prefer="most_free")` returns a device string or `"cpu"`.
- [ ] 1.3 `[hardware]` section in `config/kaine.toml` with all defaults, documented in the reference docs.
- [ ] 1.4 Add budget hints to `config/profiles/*.toml` (tier0–3 through full-stack) with the resource ceilings already noted.
## 2. Encoder usage (code)
- [ ] 2.1 `VisionEncoder.load` uses `best_device_for` instead of `cuda:0`.
- [ ] 2.2 Interoception defaults to CPU (document that it needs no GPU unless the operator overrides).
- [ ] 2.3 No process claims more than the budget; if it cannot fit, mark the module `warmup_active = false` and offload to the CPU when possible (no process kill, no hook ordering change).
## 3. Preboot and documentation
- [ ] 3.1 Add `Hardware budget` preboot rows (`WARN`, not `FAIL`) for CPU, RAM and per-GPU free memory thresholds (never auto-abort).
- [ ] 3.2 Update `docs/03-hardware/README.md` and the cross-platform note in `appendix-a-configuration/core.md` with the budgeting rules.
- [ ] 3.3 Add unit tests (`tests/test_hardware_budget.py`) covering the "use largest free device, fall back to CPU, don't evict another process" case.
## 4. Update paperwork
- [ ] 4.1 `openspec validate cross-platform-hardware-budget --strict` passes.
