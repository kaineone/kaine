## Why

Workspace novelty is meant to measure whether content recurs. `NoveltyTracker` fingerprints each event by hashing its source, type and **entire** JSON payload (`workspace/novelty.py`).

Perceptual payloads carry continuously changing floats:
- Topos: change scores, prediction errors and, with foveation on, three 768-dimension latents;
- Audition: change score, prediction error, window;
- Chronos: anomaly score, temporal context, feature vector;
- Soma: the metrics.

So a perceptual payload almost never repeats, and novelty for those sources sits near 1.0 whatever is happening. The novelty factor of the salience product is then close to inert exactly where the paper relies on habituation.

The 2026-10-05 alternatives review (§2.3 item 4) found this by reading the code. It has not been measured.

## What Changes

**Phase 1: measure, with no entity boot.**
- An offline replay script drives the real perception modules (Topos with its shipped encoder, Audition with the spectral encoder, Soma, Chronos) from the seeded feed. It records each published event's fingerprint novelty per source over the default 32-event window.
- There is no cycle, no workspace and no entity.
- The record goes under `docs/records/`, with the per-source distribution and how often the fingerprint repeats.

**Phase 2: a content fingerprint, rule chosen from the Phase 1 data.**
- The fingerprint hashes the source, the type, and the payload after:
  - the privacy filter's vector rule removes every vector field and long numeric list;
  - remaining floats are quantised.
- The quantisation rule and its resolution are recorded in the design with the Phase 1 numbers that justify them, and re-measured with the same script.
- Non-numeric content (labels, text, categories, booleans, integers) is hashed unchanged, so a genuinely new categorical event is still fully novel.

**Unchanged:** the `NoveltyTracker` semantics. The first sighting scores 1.0, repeats habituate monotonically within the window, and salience stays a pure function of its inputs.

**Paper:** a revision note recording that novelty is computed over content, not exact payload bytes.

## Capabilities

### Modified Capabilities

- `syneidesis`: the novelty fingerprint is defined over content.

## Impact

- **Code:** `kaine/workspace/novelty.py`; a new `scripts/measure_novelty.py`. Reuses `kaine.privacy_filter.strip_vectors`, so it follows `mnemos-recall-and-vector-strip`.
- **Research impact:** novelty for perceptual sources stops being pinned near 1.0. That changes salience, and so the workspace competition, in every configuration that includes perceptual modules, base-thesis among them. The next study is re-baselined on it, and no study is running.
- **Preserved beings:** none. The tracker holds no persisted state.
