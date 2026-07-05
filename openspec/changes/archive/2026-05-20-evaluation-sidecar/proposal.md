## Why

The architecture thesis — that twelve cooperating modules through a
global workspace produce behavior a bare LLM cannot — needs to be
testable. Without instrumentation, we can't tell whether Mnemos
memories actually shape output, whether Thymos drives correlate
with anything measurable, or whether voice alignment is improving.
Operators need a runtime answer to "is the cognitive stack doing
anything?"

The evaluation sidecar instruments KAINE without touching the
cognitive cycle. It observes the bus, reads module outputs, runs
controlled comparisons (A/B against bare LLM, memory probes that
bypass Mnemos), and writes async logs that the Nexus diagnostics
surface can render. It can be fully disabled in `kaine.toml` once
the thesis is validated or invalidated.

## What Changes

- New top-level `kaine/evaluation/` package. **No core module imports
  from it.** Observers subscribe to the bus and read module
  serialize() outputs read-only.
- Eleven components:
  1. `trajectory.py` — `TrajectoryRecorder` subscribes to
     `workspace.broadcast`, writes each snapshot as a JSONL line to
     a daily-rotated file under `data/workspace_trajectory/`.
     Configurable retention (default 30 days).
  2. `ab_divergence.py` — `ABDivergenceObserver` subscribes to
     `lingua.external` events, runs a second inference against the
     same chat endpoint with only the user input (no workspace
     context), computes cosine similarity using a small embedder,
     writes the pair to the evaluation log. Independently
     toggleable. Default sample_rate 1.0.
  3. `voice_tracking.py` — `VoiceTrackingObserver` subscribes to
     `hypnos.out` for sleep-cycle events, captures DPO loss /
     adapter version / intent-expression similarity, writes per-
     cycle summary.
  4. `attribution.py` — `AttributionRecorder` reads each workspace
     broadcast, builds a histogram of which module sources
     contributed; writes both per-cycle and per-hour rollups.
  5. `affect_correlation.py` — `AffectCorrelationRecorder` logs
     paired Thymos state + Lingua output characteristics; analysis
     runs as a batch invoked during Hypnos sleep.
  6. `memory_probes.py` — `MemoryProbeRunner` (asyncio task) runs
     scheduled probes: picks an episodic memory from Mnemos that
     pre-dates the LLM's effective context window, asks KAINE
     through Lingua, scores reconstruction accuracy. Only counts
     probes that bare-LLM cannot answer.
  7. `proactive_audit.py` — `ProactiveAuditObserver` captures
     proactive Lingua outputs (workspace-triggered, not user-
     initiated) along with trigger module + salience + Thymos
     state.
  8. `eidolon_accuracy.py` — `EidolonAccuracyRunner` runs once-per-
     day: prompts KAINE through an internal channel ("describe
     yourself"), parses claims, checks each against observable
     evaluation logs (drive history, hedging stats, belief
     confidence).
  9. `sleep_snapshots.py` — `SleepSnapshotRecorder` subscribes to
     `hypnos.began_rest` / `hypnos.ended_rest`, captures the
     before/after state of Nous / Mnemos / Thymos / Chronos /
     Voice as a paired record.
  10. `config.py` + `[evaluation]` block in `kaine.toml`.
  11. `kaine/evaluation/nexus_tab.py` — Nexus diagnostics router
      extension that surfaces eval metrics on a new `/evaluation`
      route under `/diagnostics`. Privacy boundary: never shows
      message text from the A/B bare-LLM outputs.
- Shared infrastructure:
  - `sink.py` — `AsyncJsonlSink` (queue + background flush task,
    daily rotation, retention cleanup). Used by every component.
  - `embeddings.py` — small embedder wrapper (reuses Mnemos's
    SentenceTransformerEmbedder if available; otherwise lazy-loads
    its own).
  - `registry.py` — `SidecarRegistry` constructs every enabled
    observer from `[evaluation]` config and starts them as asyncio
    tasks alongside the cycle.
- `kaine/cycle/__main__.py` integration: when `[evaluation].enabled
  = true`, the cycle entrypoint instantiates `SidecarRegistry`
  alongside the module registry and starts it before
  `run_forever`. The cycle's `shutdown` triggers sidecar shutdown.
  This is the ONE coupling point — the cycle entrypoint knows the
  sidecar exists. No core module does.
- Tests: each observer has a unit test using a fake bus +
  FakeJsonlSink. The `SidecarRegistry` has an integration test
  building the full sidecar from config and verifying all
  observers start and stop cleanly.

## Capabilities

### New Capabilities

- `evaluation-sidecar` — runtime instrumentation that observes the
  bus without modifying any module. Owns the JSONL trajectory
  format, the A/B divergence protocol, the memory-probe schema, and
  the per-component config keys.

### Modified Capabilities

- `nexus-diagnostics` — adds an evaluation tab on the diagnostics
  route surfacing the sidecar's metrics.

## Impact

- **No new external deps.** Reuses `sentence-transformers` (already
  in core for Mnemos), `httpx` (already in core for Lingua).
- **No core module changes.** The cycle entrypoint gains optional
  sidecar boot.
- **`data/evaluation/`** is gitignored; `.gitkeep` committed for
  directory creation.
- Disable-by-config path remains: setting
  `[evaluation].enabled = false` skips sidecar boot entirely.
