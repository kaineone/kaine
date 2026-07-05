## Context

KAINE Phase 1.3. The cycle now collects events each tick and hands them to a
`SyneidesisProtocol` collaborator (currently the `FakeSyneidesis` from
tests). This change ships the real Syneidesis. The salience computation
maturation path runs v1 (rules) → v2 (gradient boosting on inspectable
features) → v3 (GNN/VAE) per `docs/kaine-paper.md` §2.3. We are committing
to v1 here while keeping the seam where v2 and v3 will land.

Constraints:
- The cycle calls `Syneidesis.select(events, context)` once per tick and
  expects a `WorkspaceSnapshot`. The interface is fixed; v2 and v3 must
  drop into the same call site.
- Per build prompt §1.3, salience is product-form:
  `intensity * novelty * goal_relevance * thymos_modulation`.
- Goals do not yet exist (Phase 4) and neither does Thymos (Phase 4), so
  defaults for those terms must let the system run before those modules
  land.

Stakeholders: cycle (caller), every module that consumes
`workspace.broadcast` (downstream), Phase 4 Thymos (will plug in a real
modulator), Phase 4 goal repr (will plug in a real goal scorer).

## Goals / Non-Goals

**Goals:**
- `Syneidesis` class with stable `select(events, context) -> WorkspaceSnapshot`.
- `SalienceStrategy` protocol — v2 and v3 substitute by implementing this
  one method.
- `RuleBasedSalience` v1 implementing the product-form score.
- `NoveltyTracker` short-window in-memory deduplication that decreases
  novelty as a fingerprint recurs in window.
- `GoalScorer` and `ThymosModulator` protocols with static-default
  implementations that return 1.0 until Phase 4 ships real versions.
- Executive inhibition: a coalition's top score below
  `publication_threshold` flags `WorkspaceSnapshot.inhibited=True`. The
  cycle still broadcasts but action modules treat the inhibition flag as
  "stay silent."

**Non-Goals:**
- Gradient-boosted or GNN/VAE salience — those are v2/v3 changes.
- Persisted-state habituation. NoveltyTracker holds a fixed-size deque in
  memory; Chronos (Phase 2.2) owns longer-horizon habituation.
- Coalition diversity heuristics. Top-k is plain max-score; future
  changes may add coverage constraints.

## Decisions

**Product-form score, four terms, output clamped to `[0, 1]`.** Direct
read of the build prompt. Each term is in `[0, 1]`; clamping guards
against floating-point overshoot from accumulated multiplication.

**NoveltyTracker uses a deque of size 32 by default.** Small enough to
forget last-second repetitions but large enough to recognize sustained
rumination. Configurable in `config/kaine.toml`'s `[syneidesis]`
section. Counts are recomputed from the deque on each `observe()` —
O(window), trivial at window=32 — instead of maintained as a parallel
dict that drifts under eviction.

**Fingerprint via blake2b digest of `{source, type, payload}` JSON.**
Hash collisions across distinct events at 64-bit digest size are
negligible in a window of 32. JSON sort_keys for stable ordering.
`payload` defaults to `str` for non-JSON-serializable values (datetime,
custom dataclasses) so fingerprinting never raises.

**`GoalScorer` and `ThymosModulator` ship as protocols plus static
defaults.** Phase 4 substitutes real implementations without touching
this change.

**`Syneidesis.set_top_k` and `set_publication_threshold` runtime
mutators.** Variable-speed cognition (Phase 7.1) and Hypnos sleep
(Phase 6) want to nudge these at runtime. Cheaper than rebuilding the
Syneidesis instance.

**Empty event list returns an inhibited snapshot.** A tick with no
collected events is a quiet moment; the broadcast carries
`inhibited=True` and no selected events. The cycle still broadcasts
(experiential rate decides whether the snapshot becomes a memorable
moment), but action modules treat inhibition as silence.

**Strategy error tolerance.** If `strategy.score(event, ...)` raises,
log a warning and treat the score as 0.0 for that event. The cycle
continues. Better to undercount one event than crash the whole tick.

## Risks / Trade-offs

- **Naive product-form can crush small terms.** A near-zero novelty
  kills the score even if intensity is high. → Acceptable for v1; v2's
  learned weights will downweight terms that empirically don't matter.
- **In-memory novelty resets on restart.** → Acceptable for Phase 1;
  durable habituation is Chronos's job.
- **Top-k ignores diversity.** Five events from the same source can
  dominate. → Documented; coverage constraints land later if needed.
- **publication_threshold is a single number, not per-action.** A
  module that wants different thresholds (e.g. Lingua's "speak" vs
  Lingua's "stay silent") must apply its own logic on top.

## Migration Plan

First implementation; no migration. Future v2/v3 replace `RuleBasedSalience`
by swapping the `SalienceStrategy` instance passed to `Syneidesis(...)`.

## Open Questions

- Whether `WorkspaceSnapshot.salience_scores` should contain only the
  top-k scores or every event's score. Currently every event — useful
  for diagnostics, costs ~50 floats per tick. Revisit if Nexus reports
  it's too noisy.
