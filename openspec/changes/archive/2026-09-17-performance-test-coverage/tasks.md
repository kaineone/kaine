## 1. Bus polling reduction

- [x] 1.1 Add a blocking-read API to `kaine/bus/client.py` (e.g. `read_block(streams, block_ms, count)`) and verify it issues one `XREAD ... BLOCK` command.
- [x] 1.2 Update `kaine/modules/base.py` workspace loop to use blocking reads when the module is idle, falling back to non-blocking when stopping.
- [x] 1.3 Consolidate the engine's per-tick stream reads in `kaine/cycle/engine.py` into a single `XREAD` call and verify with a test.

## 2. Mnemos embedding deferral

- [x] 2.1 Modify `kaine/modules/mnemos/module.py` so `on_workspace` stores raw text/metadata in short-term without embedding.
- [x] 2.2 Embed only on eviction to episodic or on explicit recall, and verify the embedder call count in tests.
- [x] 2.3 Add a test that 100 workspace ticks with no eviction produce zero embedder invocations.

## 3. Topos efficiency

- [x] 3.1 Implement a strided window in `kaine/modules/topos/module.py` so consecutive clips advance by `clip_stride` frames.
- [x] 3.2 Update `kaine/modules/topos/encoder.py` to accept ndarrays/PIL images directly without a per-clip PIL round-trip.
- [x] 3.3 Wrap `kaine/modules/topos/forward.py:step()` in `asyncio.to_thread` in `process_frame`.
- [x] 3.4 Add tests verifying clip overlap reduction and that the forward step does not block the loop.

## 4. Audition offloading

- [x] 4.1 Refactor `kaine/modules/audition/acoustic.py` to expose a single shared decode/power-spectrum function.
- [x] 4.2 Wrap `SpectralAcousticEncoder.embed`, `detect_speech`, and `_estimate_energy` in `asyncio.to_thread` in `kaine/modules/audition/module.py`.
- [x] 4.3 Add a test that the event loop remains responsive during audio processing.

## 5. Novelty O(1)

- [x] 5.1 Replace the linear scan in `kaine/workspace/novelty.py` with a `Counter` kept in sync with the deque.
- [x] 5.2 Add a test that 100 random fingerprints are scored in linear total time.

## 6. Test coverage gaps

- [x] 6.1 Add `tests/test_boot_wiring.py::test_rewire_module_restores_self_hearing_gate` and verify it fails if the gate is not restored.
- [x] 6.2 Add `tests/test_boot_wiring.py::test_rewire_module_reseeds_eidolon_whitelist` and `test_rewire_module_restores_oscillator_wiring`.
- [x] 6.3 Add `tests/test_bus_config.py::test_committed_config_ships_latent_stream_caps` asserting `topos.out=2000` and `audition.out=2000` in the real `config/kaine.toml`.
- [x] 6.4 Add `tests/test_boot_wiring.py::test_build_registry_encryption_enabled_fail_closed_without_key` and `test_build_registry_encryption_enabled_installs_encryptor`.

## 7. Flaky sleep tests

- [x] 7.1 Add a bounded-poll helper to the test utilities.
- [x] 7.2 Replace fixed `asyncio.sleep` calls in `tests/test_evaluation_observers.py` with bounded polls.
- [x] 7.3 Replace fixed `asyncio.sleep` calls in `tests/test_lingua_context.py` with bounded polls.
- [x] 7.4 Replace fixed `asyncio.sleep` calls in `tests/test_remote_bridge.py` with bounded polls.

## 8. Validation

- [x] 8.1 Run `openspec validate performance-test-coverage --strict` and resolve all issues.
- [x] 8.2 Run the affected test suites and verify no regressions.
- [x] 8.3 Profile the hot path before and after the changes and document the improvement.
