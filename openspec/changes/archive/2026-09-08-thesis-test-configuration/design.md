## Context

The base thesis (Baars global workspace + predictive processing) needs several
*diverse* predictive processors competing for a shared workspace, with the
language organ demoted to a downstream, output-only voice and no input path that
lets a transcript reach it. The codebase already has the parts — the `[modules]`
toggles, the injectable `ActionSelectionPolicy` seam, one-in-flight guards, the
publication (conscious) threshold, and the perception feed — but ships defaults
(thin minimal set, live STT→speak trigger) that make the thesis untestable.

## Goals / Non-Goals

**Goals:**
- Configure the honest base-thesis form (Soma/Chronos/Topos/Audition + Lingua),
  raw AV as prediction error, self-initiated voice — by gating, not deletion.
- Make the entity's speech self-initiated, rare, present-focused, non-queuing.
- Keep the offline workspace-mediation ablation as the falsification instrument,
  now pointed at this richer, externally-grounded processor set.

**Non-Goals:**
- Not activating any richer faculty (memory/self/affect/world/social/sleep/
  effectors) — those are gated behind a positive base result.
- Not deleting any module or the STT code.
- Not claiming consciousness — a positive result is necessary, not sufficient.
- Not changing default behavior (all additions are opt-in).

## Decisions

**D1 — Report gate is a new injectable policy, not a change to Volition.** Volition
already takes an `ActionSelectionPolicy` and already gates on the inhibition flag.
Add `kaine/workspace/report_policy.py::SelfInitiatedReportPolicy` and select it via
`[volition].policy`. It computes the coalition's precision-weighted surprise (the
top `salience_scores` value of the selected coalition) and applies a two-tier
threshold: `think_threshold` <= `report_threshold`, both ABOVE the publication
threshold. Rationale: keeps the report/access distinction explicit and reuses the
proven in-flight-guard pattern from `DriveBiasedActionSelectionPolicy`.

**D2 — Drop, don't queue.** The policy always reports the CURRENT coalition; with
the one-in-flight guard, no new intent forms while a prior is realizing, so stale
coalitions are never queued — when the guard clears, only the then-current state
is eligible. Novelty is enforced by a last-report content signature (top
source/type) plus the refractory interval; the salience novelty term already
decays repeated content upstream.

**D3 — STT gate, not removal.** Add `[audition].transcription_enabled` (default
true = unchanged). When false, Audition's process path skips the STT call and the
`audition.transcription` publish; the acoustic-perception and affect paths are
untouched. The STT code stays. Rationale: preserves everything, matches "configure
to non-functioning," and closes the confound (no transcript can reach Lingua).

**D4 — Thesis-test profile.** `config/profiles/thesis_test.toml` enables
soma/chronos/topos/audition/lingua, disables the rest, sets `[audition].
transcription_enabled=false`, Topos foveation on, the perception feed to raw AV,
and `[volition].policy="self_initiated_report"`. A labeled experiment overlay,
distinct from the deployment tiers.

**D5 — Surprise = precision-weighted salience of the top coalition member.** The
snapshot already carries `salience_scores` keyed by entry id; the coalition's
report signal is the max selected score (the winning coalition's precision-weighted
prediction error expressed as salience, per the paper). No new metric is invented.

## Risks / Trade-offs

- **Entity is mute if thresholds are too high** → thresholds are config; the report
  policy exposes `report_threshold`/`think_threshold`/refractory as knobs, and a
  test asserts a high-surprise coalition reports and a low one does not.
- **Foveation/live capture needs display+audio access** → in a container this means
  X11/Pulse passthrough (a boot-time deployment choice), or run the cycle on the
  host; either way it's a runtime concern, not a code change here.
- **STT gate could accidentally silence perception** → spec + test require the
  `audition.perception` path to be unaffected by the transcription gate.
- **Report gate is the falsification-critical no-chatbot guarantee** → the policy
  never reads utterance/transcription events; a test asserts it forms intents with
  no utterance present and reads only workspace surprise.

## Migration Plan

1. Add the `SelfInitiatedReportPolicy` (default-off; opt-in via config).
2. Add the Audition transcription gate (default-on = unchanged).
3. Wire `[volition].policy` selection in the cycle entrypoint.
4. Add the `thesis_test` profile.
5. Reconcile the paper (separate, review-gated; paper-agent prompt provided).

Rollback: don't select the profile/policy and leave `transcription_enabled=true`;
behavior is identical to pre-change.

## Open Questions

- Exact default `report_threshold` / refractory values — tuned on a first observed
  run; the pre-registration fixes them before any verdict.
- Live screen/monitor capture vs. seeded/playlist feed for the first boot — a
  runtime choice; the profile supports both.
