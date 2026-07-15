<!-- Fixes the dual-decoder A/V desync in the playlist feed: video pulled at the
     tick rate (~0.4x) while audio plays at 1x, so the two drift onto different
     manifest items (observed: seeing item 0 while hearing item 1). Operator
     decision: real-time wall-clock pacing, trading bit-identical frame
     reproduction for real-time A/V fidelity (live/statistical tier). PROPOSAL
     ONLY — no implementation in this change yet. -->

## 1. Real-time video pacing

- [x] 1.1 Add an injectable monotonic clock to `PlaylistSource`.
- [x] 1.2 `read()` returns the frame at `elapsed × item.fps`, dropping/holding
  frames to track 1× instead of returning the next sequential frame.
- [x] 1.3 Advance to the next manifest item when the real-time position passes the
  file's end; reset per-item pacing state on open.
- [x] 1.4 Unit test with a fake `cv2` + fake clock: a given elapsed selects the
  expected frame; ticking faster than fps holds the current frame; ticking slower
  drops frames.

## 2. Boundary alignment across the two feeds

- [x] 2.1 Introduce a shared playlist start-clock (one monotonic origin + per-item
  durations) that both `PlaylistSource` and `PlaylistAudioStream` consult for
  `(item_idx, offset)`.
- [x] 2.2 Both feeds cross item boundaries together under the shared clock; assert
  in a test that video and audio report the same item across a simulated boundary.

## 3. On-bus provenance

- [x] 3.1 Expose `current_item` (title/basename, manifest order, media offset) on
  both feeds.
- [x] 3.2 Topos stamps `item` + `item_order` on `topos.report`; Audition stamps the
  same on `audition.perception`. Extend the content-free-payload contract tests to
  include the new keys.
- [x] 3.3 Verify the playing item is now readable off the bus (no fd inspection).

## 4. Reproducibility reclassification (docs + tests)

- [x] 4.1 Update the `feed.py` module docstring: the playlist feed is a live /
  statistical-tier source (reproducible by per-item sha256), not bit-identical
  frame reproduction. Zero-persistence invariant unchanged.
- [x] 4.2 Update the `reproducible-perception-feed` change notes to match.
- [x] 4.3 Relax/replace the `test_topos_feed.py` assertions that require frame
  *i* → media frame *i* for the playlist; keep sha256 fail-closed verification and
  zero-persistence tests intact.

## 5. Paper alignment

- [ ] 5.1 Ensure §6 (evaluation tiers) describes the playlist feed under the live
  tier (statistical reproducibility by media identity), consistent with this change.
  NOTE: §6 lives in the SEPARATE paper repo (predictive-workspace-paper), outside
  this kaine worktree — no paper copy exists here — so this is a follow-up for the
  paper agent; left unchecked deliberately.
