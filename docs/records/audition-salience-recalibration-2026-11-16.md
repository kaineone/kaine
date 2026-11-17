# Audition acoustic salience recalibration — planning note (2026-11-16)

Scope: task 6.7 ("acoustic salience recalibration: normalisation, alert factor,
floor") for the audition encoder bake-off (task 6.6). Records how the
recalibration must be done, what has to be measured, and how the default-profile
decision is gated. No winner is selected here; 6.6 still has only the seeded
synthetic feed, and task 6.7 cannot land until all three feed families exist.

Source records:

- `docs/records/audition-encoder-bakeoff.json` — 600 blocks × 8000 samples @
  16 kHz, surprise every 150 blocks, seed 42, device cuda:0.
- `docs/records/audition-encoder-bakeoff-1200blocks.json` — 1200-block
  snapshot (stdout capture, not JSON).
- `docs/records/audition-encoder-decision-note-2026-11-16.md` — 6.6 not complete.
- `docs/records/audition-feed-variant-readiness-2026-11-16.md` — feed loader
  contract still pending.

## What must be recalibrated

The acoustic perception path (`kaine/modules/audition/module.py`,
general-audition mode) computes three interlocking quantities:

1. **Normalisation** — rolling-window division of the raw score by its own
   rolling mean:
   - `normalised_change = change / mean(change window)` (alert ratio input),
     published as `normalised_change`.
   - `normalised error = prediction_error / mean(prediction_error window)`,
     published as `normalised_error`.
   - Window today: `prediction_error_window` (audition), default 32 **utterance
     windows**, shared by both histories (`_acoustic_change_history` and
     `_acoustic_errors`). ` AuditoryForwardModel` keeps its own buffer sized by
     `auditory_buffer_size`.
2. **Alert factor** — `acoustic_change_alert_factor` (default 2.0): an alert
   fires when `normalised_change >= factor`. Mirrors the forward-model criterion
   `normalised_error >= 2.0`.
3. **Floor** — `acoustic_change_alert_threshold` (default 0.35): absolute floor
   retained as a noise guard, because a large ratio over a near-static stream
   (tiny mean) can fire on numerical noise. The criterion is primarily
   relative; the floor is secondary.

These three knobs live in `[audition]` of `config/kaine.toml` and are wired
through `kaine/boot/factories/audition.py`; `arousal_window_range` and
`acoustic_encoder`/`acoustic_device` are separate and are not part of this
recalibration.

## Evidence on hand (and its limits)

600-block synthetic seeded feed:

| encoder | ROC AUC | false alerts/min | p95 salience | p95 latency (ms) | peak RSS (MB) | embed dim |
|---|---:|---:|---:|---:|---:|---:|
| spectral | 0.9992 | 6.00 | 1.398 | 1.62 | 285 | 64 |
| wavjepa | 0.9950 | 6.00 | 3.119 | 6.55 | 3142 | 768 |
| dasheng | 0.9836 | 6.00 | 3.136 | 3.79 | 1713 | 768 |

1200-block snapshot shows wavjepa leading on AUC (0.997 vs spectral 0.989,
dasheng 0.927) while spectral keeps latency leadership and the false-alert tie.
The three-way false-alert tie is not dispositive: the FA metric here is defined
*internally* as non-surprise blocks above the 95th percentile of non-surprise
salience, so it measures dispersion rather than absolute behaviour. In other
words, a detection threshold chosen at the 95th percentile of *that* run cannot
answer whether the current `factor`/`floor` produce sensible alerts in a live
stream.

**Consequences for recalibration:**

- The relative factor (default 2.0) is correct in *principle* — the ratio is
  embedding-scale-agnostic — but its value is inherited from the vision
  module's precedent, not fitted to acoustic data. It needs an acoustic
  data fit on **all three feeds**.
- The rolling window (32) determines both the lag of the baseline and the
  variance of the ratio. It is set as an utterance count and is therefore
  confounded with VAD segmentation; on the continuous-window feeds (seeded,
  playlist, stimulus source) the count-to-seconds mapping differs.
- The floor (0.35) is given in *absolute* change-score units. The bake-off's
  `p95_threshold` column shows that absolute change scales differ markedly
  across encoders (≈1.4 for spectral versus ≈3.1 for both SSL encoders). A
  single absolute floor therefore cannot be fair to all three encoders; it must
  either be chosen per-encoder at the noise shoulder or the design must move the
  guard to a relative (percentile-of-rolling-mean) quantity. Moving the guard is
  a code change, not a config change, and is out of scope for this note; the
  candidate work below therefore documents **both** options.

## Proposed recalibration procedure (6.7)

Perform offline, entity never booted. Follow feed-variant readiness concrete
plan for loaders first; once each feed exists, run this:

### A. Per-feed, per-encoder characterisation

For each (feed, encoder), compute over the non-surprise blocks:

- `change` distribution: median, mean, p90, p95, p99, min nonzero,
  numerical-noise floor.
- `normalised_change` distribution under a fixed candidate window.
- Event-marked blocks' `change` and `normalised_change` percentiles.
- Confusion curve: threshold sweep over `normalised_change` (and over absolute
  `change` with each floor).
- Per-encoder recall@factor-2.0 and achieved false-alerts/minute at the
  *absolute* config floor, reported alongside the relative figure.

Store each in a per-feed record file, e.g.
`docs/records/audition-salience-calibration-{feed}.json`, preserving the
feed metadata required by the readiness note (seed, manifest digest, knobs,
label rule, hop length). Zero-persistence invariant: no PCM written to disk.

### B. Normalisation (window) candidates

`prediction_error_window` candidates, all measured with the same feed/encoder
matrix:

- 8, 16, 32 (current), 64 sliding windows.
- Where a feed is continuous-window rather than VAD-segmented, also express
  the window in seconds at the feed's block rate and report both (window is an
  integer count today; seconds = window × frames_per_block / sample_rate). Do not
  change the knob's unit in this pass — only document the mapping.

Selection criteria: stable baseline under steady noise (rolling-mean CV low),
minimal detection delay for an onset, and no degradation of the 6.6 AUC gain
over a single-block change. Reject a candidate that makes the false-alert rate
rise on the steady-noise injection test (C.4).

### C. Alert factor candidates

Candidate factor grid: 1.5, 1.75, 2.0 (current), 2.25, 2.5, 3.0. For each:

- ROC AUC on each feed (must match or beat the 6.6 figure for that feed).
- Achieved false-alerts/minute (not the internal 95th-percentile artefact —
  measured against an explicit decision threshold of `factor`).
- Missed-onset rate.
- Cross-encoder parity: the relative rule should give similar
  false-alert rates across encoders on the same feed; large parity gaps
  indicate *over-calibration to one encoder* and disqualify the factor for
  multi-encoder use.
- Robustness to feed: accept a factor only if it meets the same targets on all
  three feeds without feed-specific tuning. The intent of "self-calibrating"
  rules is one global factor; per-encoder factors are to be rejected unless the
  review can show that a single value cannot satisfy two feeds at once.

### D. Floor candidates

Two documented options; evaluate both, decide with evidence, never by assumption:

**Option 1 — keep absolute floor, fit per-encoder shoulder.** For each encoder,
set `acoustic_change_alert_threshold` to the larger of (a) the numerical-noise
floor measured on a constant-input bench, and (b) the p99.9 of its absolute
`change` on routine (non-surprise) blocks across all three feeds. Report the
three candidate values; config keeps one value, so if they differ by more than
an order of magnitude the encoder with the larger shoulder loses — which may
itself feed the default-profile decision in §E.

**Option 2 — relative guard (code change).** Express the guard as a multiple
of the rolling mean (e.g. `floor_factor` so the rule becomes
`normalised_change >= alert_factor AND change >= floor_factor * floor_baseline`,
or, cleaner, drop the absolute floor and rely on the rolling mean plus a guard
that rejects windows whose mean change is below the numerical-noise lower
bound). This is more faithful to "self-calibrating" and removes the cross-
encoder shoulder problem; it costs a small patch to `Audition` and to
`tests/test_audition_normalised_change.py`. OpenSpec the change before making
it (do not implement in this task — this note specifies the question, not the
answer).

Candidate absolute floors if Option 1 is retained: 0.10, 0.15, 0.25, 0.35
(current), 0.50, plus the per-encoder shoulder from Option 1.

Floor acceptance criterion: the floor must never delete an onset that the factor
rule would have caught on the held-out feed, and must demonstrably suppress
noise-only false alerts on the steady-noise test (C.4).

### E. Candidate tests (required before 6.7 is ticked)

1. **Deterministic surrogate** (existing) — `tests/test_audition_normalised_change.py`
   and `tests/test_audition_acoustic.py`: re-run with the chosen
   (window, factor, floor) substituted into the fake encoder; assert the onset
   block is flagged and the steady block is not. Already in tree.
2. **Window sensitivity** — a parametrised test sweeping the window candidate
   values with a known onset sequence and asserting the factor-threshold crossing
   is invariant up to a bounded delay.
3. **Factor grid** — new offline test in `tests/test_bench_audition_feeds.py`
   (or a companion) that runs the bench's scoring function on a small
   committed synthetic fixture and asserts ROC AUC / FA / missed-onset at each
   candidate. Kept tiny; the full grid runs in the bake-off script, not CI.
4. **Absolute-threshold cross-encoder test** — verifies that at the chosen floor,
   no encoder has its onsets suppressed while another's survive (parity guard).
5. **Zero-persistence invariant** — loader test asserts no PCM or decoded
   samples reach disk (per readiness note §4).
6. **Steady-noise injection** — 1000-block constant-amplitude noise stream;
   assert no alert fires at the chosen factor+floor (noise-control negative).
7. **Ablation control** — onset relocated to an arbitrary non-surprise position;
   ROC AUC computed over B=200 replicates to rule out a chance codec (report
   AUC distribution, reject if the lower bound drops below 0.9).
8. **Plant-habituation check** — stream with gradually rising but uneventful
   texture; alert must remain off, checking the rolling mean tracks trend
   rather than spiking at the start of a new plateau.

Each candidate change must land with the corresponding candidate test passing
on the steady-noise and onset cases; no task checkbox is ticked until the
feed records (6.6) and the calibration records (this note) exist.

## Default-profile decision (without selecting a winner)

Tier 0 stays `spectral`. This invariant is stated in the decision note and is
not revisited by this recalibration regardless of the 6.6 outcome.

Decision (gating) sequence, none of which is taken in this document:

1. **6.6 (winner on three feeds)** — must complete first; only then is a
   candidate winner nameable. Single-feed AUC leads swap between the 600-block
   and 1200-block snapshots, so 6.6 must not be short-circuited.
2. **6.7 (this note)** — window, factor, floor fitted and reviewed on all
   feeds before any profile edit.
3. **6.9 (WavJEPA MMN mode)** — results must be in hand before a WavJEPA
   default; its mismatch mode is not in the current bake-off record.
4. **Hardware/resource gate** — measured peak RSS and p95 latency from the feed
   records must fit the deployment's per-cycle budget on the cable. The
   bake-off already shows 6–11× RSS differences and ≈4× latency differences;
   an SSL winner that clears this gate only at excessive cost is not promoted.
5. **Licence / notice entries** (6.8) — must be committed (model cards, third-
   party attributions) in the same PR as any default change.
6. **No auto-promotion to Tier 0** — even a promoted winner is promoted to the
   *beyond-first-configuration* default via config override and plugin seam, not
   by changing Tier 0's `spectral` default, which remains the safe, always
   available fallback. Any default-profile change keeps `fallback to spectral`
   behaviour specified in the same change.
7. **No implementation now** — this task changes no config or tasks; config
   edits require a separate PR through the normal pipeline, with a worker
   first-pass review and adversarial review before merge.

If the review concludes that spectral remains the leader under the fitted
calibration, the outcome is still recorded as evidence and no profile edit is
needed (Tier 0 stays spectral and the status is simply "no promotion").

## Not done by this document

- No `config/` changes, no task checkboxes changed, no code edits.
- No winner selection; 6.6 is still open.
- No implementation of the relative-floor (Option 2) variant.