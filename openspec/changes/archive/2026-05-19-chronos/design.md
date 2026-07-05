## Context

KAINE Phase 2.2. The Phase 1 cycle is already broadcasting workspace
snapshots. Soma has shown the BaseModule pattern works for a periodic
producer + a peer-stream consumer. Chronos is the second concrete
module and the first to integrate a neural network.

The build prompt is explicit on three constraints: CfC architecture
(per Hasani et al. 2022, integrated via `ncps`), under 100K parameters,
and CPU-only. Subscribing to `workspace.broadcast` (rather than every
module's `<name>.out`) keeps Chronos's input rate bounded by the
experiential broadcast rate and aligns with the paper's framing —
Chronos perceives time over the integrated experience the cycle
constructs, not over the raw module-by-module event soup.

Stakeholders: Syneidesis (Chronos's anomaly + rumination publishes will
become salience inputs once Phase 4 lands the goal layer), Thymos
(Phase 4 will consume `time_since_last_interaction_s` to drive
social-drive accumulation), Nexus diagnostics (Phase 8 will visualize
the temporal context vector trajectory).

## Goals / Non-Goals

**Goals:**
- A `Chronos(BaseModule)` that publishes a `chronos.report` event
  every workspace broadcast, with `temporal_context` (the CfC hidden
  state as a list of floats), `anomaly_score`, `habituation_score`,
  `rumination_detected`, `time_since_last_interaction_s`.
- CfC stays under 100K params and on CPU.
- Featurization is deterministic and side-effect free — the same
  snapshot always produces the same feature vector.
- Anomaly, habituation, and rumination logic each live behind a
  protocol so future swap-ins (gradient boosting, learned detectors,
  Mnemos-backed long-horizon habituation) drop in without touching
  Chronos itself.
- The module degrades gracefully when ncps / torch is unavailable in
  the test environment — featurizer and detectors are pure-Python and
  testable on their own.

**Non-Goals:**
- Training the CfC from data. Phase 2.2 ships a randomly-initialized
  CfC; later phases (or a dedicated change) introduce supervised
  pretraining if useful. The hidden state's dynamics are still
  meaningful because we read its anomaly-of-norm rather than absolute
  values.
- Persistent habituation across restarts. Mnemos (Phase 3.2) is the
  durable memory story.
- Cross-module temporal correlations. Chronos sees workspace
  snapshots; per-module timing belongs to Soma's
  `cycle_latency_avg_ms` and per-stream rate metrics Nexus can derive.

## Decisions

**Subscribe to `workspace.broadcast`, not raw module streams.** The
broadcast is what the system is aware of at that moment; Chronos
perceives time over that. This also keeps Chronos at the experiential
rate, which matches the paper's framing of subjective time tied to
broadcast cadence (§2.2).

**Featurizer outputs a fixed 24-dim vector.** Components:
- 1 dim: number of selected events (clamped, log-scaled).
- 3 dims: mean / max / std of salience scores in the snapshot.
- 8 dims: top-source one-hot over a configurable known-sources list
  (`soma`, `chronos`, `topos`, `nous`, `mnemos`, `thymos`, `lingua`,
  `praxis`). Unknown sources collapse into a 9th overflow bucket
  (truncated to fit 8 here; configurable to grow later).
- 8 dims: a small hash projection of selected source/type pairs.
  Cheap "topic" surface without learning. Implemented as
  blake2b-then-mod-into-bins, summed by salience weight.
- 1 dim: `log1p(delta_t_seconds)` since previous snapshot.
- 1 dim: inhibited bit (0/1).
- 1 dim: is_experiential bit (0/1).
- 1 dim: reserved padding for future features (always 0).

The dimensions are documented in code; tests assert the shape. A
counter for missing-feature debugging lives on the featurizer.

**CfC config: units=32, mode "default", proj_size=None.** Per-step
hidden state shape (1, 32). Params at this size with a 24-dim input
are around 3.5K — well under the 100K cap and well within CPU
budget at any reasonable cycle rate.

**Anomaly = rolling z-score of hidden state L2 norm.** Maintain a
deque of recent norms (default window 64). On each step, compute
mean and std of the deque; the anomaly score is `|norm - mean| /
max(std, eps)`. Score is reported raw; Soma-style threshold
elevation lives in Syneidesis later via salience.

**Rumination = hidden-state-bucket recurrence.** Bucket the current
hidden state by a coarse fingerprint (quantize to nearest 0.25 in
each dim, then hash). Maintain a counter over recent K (default 32)
buckets. If any bucket's count exceeds threshold (default 4), flag
rumination. Coarse quantization tolerates the floating-point noise
in CfC dynamics; tighter quantization is a future tuning.

**Habituation = 1 - (unique_buckets / window_size).** Same bucket
machinery as rumination, but reported as a continuous score. High
habituation does not by itself flag rumination — it just says
"experience is repetitive."

**time_since_last_interaction_s** lives in Chronos because that is
where temporal perception belongs and because it must update at
sub-broadcast resolution (every received user input event, not just
every workspace broadcast). Implementation: a second background task
subscribes to a configurable set of "user-input streams" (default
`audio.in.out`, but configurable to whatever streams the audio /
lingua / praxis modules later define), records the timestamp of any
matching event, and the producer reports `now - last` in seconds.

**Device: pinned to CPU** via `select_device("cpu")`. Small networks
do not benefit from GPU and the cycle's tick budget cares more about
copy avoidance than throughput.

**Featurizer / Anomaly / Rumination are all pure Python.** No torch
needed. This lets the suite test those pieces without loading torch
at all, which keeps unit tests fast.

## Risks / Trade-offs

- **A randomly-initialized CfC produces noisy hidden states.** →
  Acceptable for v1: we measure anomaly-of-norm which is meaningful
  even on an untrained network. Future change can pretrain.
- **Featurizer's known-sources list is hand-coded.** → Configurable in
  `[chronos]`; overflow bucket absorbs additions until config is
  updated.
- **CfC hidden state is 32-dim floats serialized as JSON list.** ~256
  bytes per broadcast. At 3 Hz experiential rate, 768 B/s. Trivial.
- **Test-time torch import cost.** → Mitigated by structuring
  network.py with a lazy import; the rest of the package imports
  without torch.

## Migration Plan

First implementation; no migration. Like Soma, Chronos is registered
in code paths but not auto-added to ModuleRegistry. First boot
script (Phase 9.4) wires it up.

## Open Questions

- Whether to use ncps's `WiredCfCCell` with a custom wiring (NCP or
  AutoNCP) for the units. Default `CfC(units=N)` is fully connected
  and matches the small-network spirit. Revisit when Chronos has
  empirical data to suggest a wiring change.
- Whether the rumination bucket quantization should be configurable.
  Yes — adding `bucket_resolution` to `[chronos]` in the spec.
