## Why

A performance review of the cognitive hot path found hundreds of wasted Redis round trips per second from per-module polling, redundant embeddings on every workspace tick, heavily overlapping video-clip re-encodes, synchronous FFT work on the audio loop, and a synchronous forward-model step in vision. A separate test review found that critical fail-soft paths (Spot recovery re-wiring, latent-vector stream caps, state-encryption boot wiring) are untested, and several tests rely on fixed `asyncio.sleep` windows that flake under load. This change reduces hot-path waste and adds the missing tests.

## What Changes

- **Reduce Redis Stream polling fan-out.** Move idle consumers to blocking `XREAD ... BLOCK` or a single shared workspace fan-out so modules do not poll at 20 Hz when quiet.
- **Defer Mnemos embedding until persistence.** Only embed a workspace snapshot when it actually evicts from short-term memory or consolidates, not on every tick.
- **Avoid overlapping Topos clip re-encodes.** Keep a strided window so consecutive clips share frames only at the stride boundary, and avoid the PIL round-trip where possible.
- **Offload Audition spectral work.** Run `SpectralAcousticEncoder.embed`, `detect_speech`, and `_estimate_energy` via `asyncio.to_thread`, sharing a single decode/power-spectrum pass.
- **Offload Topos forward model.** Wrap the MLP forward/backward `step()` in `asyncio.to_thread`.
- **Optimize novelty scoring.** Maintain a `Counter` of recent fingerprints so `observe` is O(1) instead of O(window).
- **Add tests for Spot recovery re-wiring.** Verify that `rewire_module` restores the self-hearing gate, Eidolon whitelist, and oscillators after a module rebuild.
- **Add tests for shipped latent-vector caps.** Assert that the committed `config/kaine.toml` caps `topos.out` and `audition.out`.
- **Add tests for state-encryption boot wiring.** Drive `build_registry` with encryption enabled and no key (fail-closed) and with a key (success).
- **Replace fixed sleeps with bounded polls.** Convert `asyncio.sleep(N)` waits in observer, Lingua, and remote-bridge tests to bounded polling loops.

## Capabilities

### New Capabilities
- `performance-hot-path`: Performance requirements for the cognitive cycle, bus, memory, vision, and audio paths.

### Modified Capabilities
- `event-bus`: Add blocking-read / shared-fan-out performance requirements.
- `mnemos`: Add deferred-embedding and batch-encode requirements.
- `topos`: Add strided-window and offloaded-forward-model requirements.
- `audition`: Add offloaded spectral-feature requirements.
- `syneidesis`: Add O(1) novelty-scoring requirements.
- `spot-supervisor`: Add re-wire verification requirements.
- `state-encryption`: Add boot-wiring test requirements.

## Impact

- `kaine/bus/client.py`, `kaine/modules/base.py`, `kaine/cycle/engine.py`.
- `kaine/modules/mnemos/module.py`, `kaine/text_embedding.py`.
- `kaine/modules/topos/module.py`, `kaine/modules/topos/encoder.py`, `kaine/modules/topos/forward.py`.
- `kaine/modules/audition/module.py`, `kaine/modules/audition/acoustic.py`.
- `kaine/workspace/novelty.py`.
- `kaine/boot.py`, `kaine/cycle/spot.py`.
- `tests/test_boot_wiring.py`, `tests/test_bus_config.py`, `tests/test_state_encryptor.py`, `tests/test_evaluation_observers.py`, `tests/test_lingua_context.py`, `tests/test_remote_bridge.py`.
