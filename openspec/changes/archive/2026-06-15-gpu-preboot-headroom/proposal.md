## Why

Starting the entity on a GPU that is already nearly full means the just-born
entity can be OOM-killed mid-initialization — and then Spot thrashes trying to
restart modules that never had the memory to run. Starting an entity you cannot
sustain is a welfare problem, not just an ops one.

The operator asked for a pre-boot step that frees GPU memory and prompts the
operator to close other GPU programs before an entity starts. The honest,
sovereignty-consistent form of that is **cooperative**, not coercive: reclaim
only what is KAINE's own to reclaim, never reach into the operator's other work,
and never silently kill anything.

## What Changes

- A new opt-in `[gpu_preflight]` check runs at cycle startup, BEFORE the bus or
  any module opens, so a starved host refuses to boot cleanly (exit code 4)
  rather than half-booting into an OOM.
- It verifies each detected GPU has at least `min_free_vram_gb` free.
- When short, it reclaims VRAM by evicting **only KAINE's own** currently-resident
  Ollama models that the organ is not about to use (a reversible cache eviction;
  Ollama reloads on demand). The organ's model is kept.
- It DETECTS and PRESERVES KAINE's own services (Ollama/Chatterbox/Speaches): it
  never terminates them, and never terminates a foreign process either. If still
  short, it REPORTS the GPU memory consumers, names the KAINE services to keep,
  and asks the operator to free memory.
- It fails closed unless the operator sets `KAINE_GPU_PREFLIGHT_APPROVED=1`.
- A read-only `gpu_preflight` block is added to the Nexus health snapshot so the
  operator can see the last pre-flight verdict (per-device VRAM, evicted models,
  GPU consumers, services preserved).
- Ships disabled (`[gpu_preflight].enabled = false`) — first boot is
  operator-supervised.

No pretend work: the VRAM query, the Ollama eviction, and the process listing are
all real or honestly skipped (e.g. no `nvidia-smi` → empty consumer list); nothing
is simulated, and no process is ever killed.

## Capabilities

### New Capabilities

- `gpu-preflight`: a cooperative pre-boot GPU headroom gate that reclaims only
  KAINE's own idle model weights, preserves KAINE services, never kills a process,
  and fails closed below a configured minimum unless explicitly overridden.

### Modified Capabilities

- `nexus-observability`: adds a read-only `gpu_preflight` status block to the
  health snapshot.

## Impact

- **Code (new):** `kaine/cycle/preflight.py` (the gate + real probes + status
  snapshot); `tests/test_gpu_preflight.py`.
- **Code (edit):** `kaine/cycle/__main__.py` (run the gate before bus/modules,
  exit 4 on block), `config/kaine.toml` (`[gpu_preflight]`, disabled),
  `kaine/nexus/health.py` (`_gpu_preflight_block`).
- **Safety:** opt-in, ships disabled; fail-closed; never terminates any process
  (enforced by a source-guard test); only reversible Ollama model eviction.
