## Context

See `proposal.md` for motivation. The hot path currently uses non-blocking polling, redundant embeddings, overlapping clip encodes, synchronous audio transforms, a synchronous vision forward-model step, and linear novelty scans. Critical recovery and encryption paths lack tests, and several tests use fixed sleeps.

## Goals / Non-Goals

**Goals:**
- Reduce wasted Redis round trips and event-loop blocking on the cognitive hot path.
- Add missing tests for Spot recovery re-wiring, latent-vector caps, and encryption boot wiring.
- Replace flaky fixed-sleep tests with bounded polls.

**Non-Goals:**
- Changing the cognitive algorithm or salience model.
- Adding new modules or capabilities.
- Rewriting the test framework.

## Decisions

**Decision 1: Introduce a blocking `subscribe_workspace_block` API on `AsyncBus`.**
The existing `subscribe_workspace` stays non-blocking for callers that need it. New code and the consolidated engine fan-out can opt into blocking reads. This is the least invasive change.

**Decision 2: Defer Mnemos embedding to eviction/consolidation.**
Store raw text in `short_term`; embed only when moving to `episodic` or when `recall` needs a vector. This matches the existing eviction path and requires no new data structures.

**Decision 3: Strided window in Topos.**
Keep a deque of frames but only encode when `(frames_seen - clip_len) % clip_stride == 0`, and pass the slice directly to the encoder. The encoder protocol already accepts a list of frames; we avoid the PIL round-trip by passing ndarrays when the producer provides them.

**Decision 4: Shared audio transform pipeline.**
Decode the WAV once, compute the power spectrum once, then derive the spectral embedding, VAD decision, and RMS energy from that spectrum. Wrap the compute-heavy calls in `asyncio.to_thread`.

**Decision 5: Bounded-poll test helper.**
Add a small helper in `tests/conftest.py` or a shared test utility that polls a condition with a short sleep and timeout, replacing fixed `asyncio.sleep(N)` calls.

## Risks / Trade-offs

- **[Risk]** Blocking reads can delay shutdown.
  → **Mitigation:** Use a bounded block timeout (e.g. 100 ms) and check the module's stop flag between blocks.
- **[Risk]** Deferring Mnemos embedding changes recall behavior if short-term is queried.
  → **Mitigation:** `recall` against `short_term` will embed on demand; the common case is recall against `episodic` where embedding already happens at eviction.
- **[Risk]** Strided windows can miss rapid scene changes at the boundary.
  → **Mitigation:** The existing `change_score` and `habituation_score` already handle cadence; the stride is a config value operators can tune.
- **[Risk]** Offloading audio transforms adds thread overhead.
  → **Mitigation:** The transforms are CPU-bound and currently block the loop; the thread overhead is small relative to the FFT/filterbank work.
