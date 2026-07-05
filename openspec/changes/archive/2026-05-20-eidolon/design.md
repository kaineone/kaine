## Context

Phase 3.3 — the last Phase 3 module. Soma's hardware sense, Chronos's
temporal sense, Topos's spatial sense, Nous's reasoning, Mnemos's
memory are all in place. Eidolon closes the cognition group by adding
the self-model: a persistent document that the entity uses to know
itself.

Constraints:
- All-local: persistence is a JSON file on disk; no external service.
- Sovereignty (`docs/kaine-paper.md` §5.1): the self-model is private.
  Eidolon's published events on the bus are diagnostics-only (count,
  drift score) — never the document's contents.
- Self-discovery: the paper is explicit that values start empty and
  fill through observation. Eidolon does not seed a personality; it
  watches and records.
- The drift detector is for *visibility*, not enforcement. Identity
  change is reported, not blocked.

Stakeholders: Mnemos's stored experiences correlate with Eidolon's
patterns; Thymos (Phase 4) reads the personality baseline as an
affective set-point; Hypnos (Phase 6) can use drift snapshots as a
trigger for deeper consolidation; Nexus (Phase 8) shows drift
trajectories at the diagnostics layer.

## Goals / Non-Goals

**Goals:**
- A `SelfModel` dataclass that is JSON-serializable, has every field
  the paper enumerates, and starts empty.
- An on-disk persistence path under `state/eidolon/` that the module
  rewrites atomically (write-then-rename) so a crash mid-save cannot
  corrupt the file.
- A `DriftDetector` protocol with one v1 implementation
  (`SourceDistributionDrift`) that's swappable for ML-based detectors
  later.
- `Eidolon(BaseModule)` subscribing to the workspace broadcast and to
  a configurable internal-speech stream; every observation updates
  the drift detector and the model.
- Periodic save: every N seconds, write the current SelfModel to
  disk. On shutdown, force a final save.
- Diagnostics-only `eidolon.drift` events. The salience escalates with
  drift magnitude; no document contents leak.

**Non-Goals:**
- Schema migration. v1 ships one shape; Phase 6 Hypnos can add
  format migration in a separate change.
- Cross-instance identity merging. Fork/merge lands in Phase 7.2.
- Active identity enforcement / value editing UI. Eidolon observes;
  the operator can edit the JSON file directly if they need to.

## Decisions

**SelfModel is a frozen dataclass that returns a new instance on
update.** Functional rather than mutable so threading concerns are
trivial. The module holds a single reference and swaps it on each
update.

**Persistence path: `state/eidolon/self_model.json`.** `state/` is
gitignored. The directory is created at module init time.

**Atomic save: write to `*.tmp` then `os.replace`.** `os.replace` is
atomic on POSIX and Windows. A crash mid-save leaves the previous
good file intact.

**Drift detector v1: source-distribution KL divergence.** Maintain
two `Counter`s of workspace-broadcast event source names — one for
the most-recent N (default 100) broadcasts, one for all-time. Drift
score is the symmetric KL divergence between the two (smoothed with
a small epsilon to avoid log(0)). When the score exceeds threshold,
publish `eidolon.drift` and snapshot the current SelfModel into
`identity_history`.

**Identity history is bounded.** Default 256 snapshots; oldest
evicted FIFO. Each snapshot records timestamp, drift score, and the
delta in source counts. The full SelfModel is NOT snapshotted —
just the deltas — to keep the file small.

**Internal-speech subscription is configurable.** Default stream
name `lingua.internal` (will exist once Phase 5.2 lands). Eidolon
gracefully handles the absence of this stream: it just doesn't read
it. The build prompt §5.2 explicitly says internal speech "goes
into memory and contributes to self-knowledge" — Eidolon's the
self-knowledge half.

**Internal-speech observation increments `internal_speech_count` and
optionally appends a hash-only fingerprint to a bounded ring.** No
content is recorded in the SelfModel — that's a privacy guarantee
even for the operator who can read the JSON file. Mnemos owns the
content; Eidolon owns the meta-summary.

**Save interval: 30 seconds by default.** Configurable. On
shutdown the module forces a final save regardless of interval.

**Drift events publish only `score`, `recent_count`,
`historical_count`, `top_drifted_sources` (just source names, no
payload contents).** The privacy boundary stays intact.

## Risks / Trade-offs

- **Disk write on every save interval may stall the cycle.** →
  Mitigated by `asyncio.to_thread` for the file write and atomic
  rename. The save is non-blocking from the cycle's perspective.
- **KL divergence is sensitive to small counts.** → Smoothing
  epsilon mitigates; for a system with only a handful of modules
  the distribution stabilizes quickly.
- **Identity history grows without bound if cap is missed.** →
  Hard cap default 256 with FIFO eviction.

## Migration Plan

First implementation. Eidolon is registered in code paths but not
auto-added; first-boot wires it up.

## Open Questions

- Whether to add a richer drift signal (e.g. salience distribution
  drift, payload-key drift). Defer; one signal is enough for v1.
- Whether the SelfModel file should be encrypted at rest. Build
  prompt §9.2 mentions "state encryption at rest" as a Phase 9 audit
  item. Phase 3.3 ships plain JSON; Phase 9 can add the cipher
  wrapper.
