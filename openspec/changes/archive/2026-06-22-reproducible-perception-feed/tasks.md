# Tasks — reproducible-perception-feed

> Design-of-record from the 2026-06-18 shakedown. Build when the operator gives
> the go. Ships the feed `off`; boots no entity. Operator supplies copyright-free
> media for the playlist mode; the seeded generator needs no external assets.

## 1. SeededProceduralSource (in-repo default)

- [x] 1.1 Implement `_VideoSource` whose `read()` returns `frame(seed, i)` as a
      pure function of `(seed, frame_index)` — bit-identical across runs of a seed.
- [x] 1.2 Structured **base signal** the world model can learn to predict
      (prediction error falls as it fits).
- [x] 1.3 **Surprise events** at the configured cadence, with onset/content drawn
      from a **counter-based, seed-keyed PRNG** (stateless/seekable). Reproducible
      given the seed; not invertible from frames (entity cannot anticipate).
- [x] 1.4 Persist only `(seed, schedule)`, never rendered frames (zero-persistence).
- [x] 1.5 Tests: identical seed → identical frame bytes at index i; different seeds
      → decorrelated surprise schedules; restart/seek reproduces frame i; surprise
      cadence matches config.

## 2. PlaylistSource (operator-curated, reproducible)

- [x] 2.1 Implement `_VideoSource` over an operator manifest (item path + sha256 +
      fps + order). Decode to in-memory frames; persist nothing beyond the manifest.
- [x] 2.2 `open()` verifies every sha256 before the run; mismatch fails the source
      (reproducibility void if media changed). Order + fps define frame i.
- [x] 2.3 Tests: verified manifest opens and indexes deterministically; a digest
      mismatch fails closed; frame i is stable across runs.

## 3. Config + wiring

- [x] 3.1 `[topos.perception_feed]` with `mode` (off/seeded/playlist/camera),
      `seed`, `surprise_interval`, `surprise_strength`, `playlist_manifest`;
      shipped `mode = "off"`.
- [x] 3.2 Select the `source_factory` from `mode` in Topos/LiveCamera construction;
      `camera` keeps the existing cv2 path; `off` keeps capture disabled.
- [x] 3.3 Confirm the zero-persistence AST guard covers both new sources; add a test
      asserting neither source writes frames.

## 4. Research covariate

- [x] 4.1 Record the feed descriptor in the submission manifest: seeded →
      `{seed, schedule_params}`; playlist → `{manifest_sha256, item_digests}`.
- [x] 4.2 Test: the covariate round-trips and is sufficient to regenerate (seeded)
      or verify (playlist) the stream.

## 5. Surface + docs + validate

- [x] 5.1 Nexus perception panel shows the active feed mode + descriptor (seed or
      manifest digest), reinforcing that input is deterministic.
- [x] 5.2 Docs (present tense): the two modes, how to pin a reproducible run, and
      that live human/camera input is excluded from research runs (camera mode is
      operator-present demos only).
- [x] 5.3 `.venv/bin/pytest -q` green; `openspec validate reproducible-perception-feed --strict`.
- [x] 5.4 Confirm shipped `config/kaine.toml` ships the feed `off` and the all-off
      first-boot guard passes.
