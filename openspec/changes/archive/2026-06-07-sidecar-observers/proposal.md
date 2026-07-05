## Why

`KAINE_Paper_v4.md` §5.2 lists the data the evaluation sidecar must collect. The
v4 architecture adds signals the current sidecar does not observe: **oscillatory
coherence logs** (PLV between module pairs, keyed as `metadata['coherence']` in
`WorkspaceSnapshot` from `oscillatory-layer`), **replay logs** (which memory IDs
were replayed, what associations/Phantasia scenarios formed — memory IDs not text),
**Empatheia agent-model accuracy** (predicted vs. actual agent behavior),
**voice-alignment divergence** (operator-seeded vs. self-generated preference
pairs), and **fatigue-accumulator history** (substrate load trajectory). Three
additional observers close measurement gaps identified in the architecture review:
**prediction error** (sliding-window mean/p95/p99 across predictive modules),
**welfare events** (§5.5 Gray-Zone Events), and **Nous policy** (EFE/horizon/
selected action). These close the measurement loop for the new modules.

## What Changes

- Add read-only observers under `kaine/evaluation/observers/` (daily-rotated JSONL,
  matching the existing sidecar pattern):
  - `coherence_observer` — reads `WorkspaceSnapshot.metadata['coherence']` (the
    PLV key defined by `oscillatory-layer`) from broadcasts → PLV time series per
    module pair.
  - `replay_observer` — `mnemos.replay` + `phantasia.scenario` → replay/association
    log. Default `redact_content = true`: logs memory IDs, not text content.
  - `empatheia_observer` — `empatheia.agent_model` predictions vs. subsequent
    `audition.emotion`/behavior → agent-model accuracy.
  - `voice_alignment_divergence_observer` — operator-seeded vs. self-generated
    preference pairs from Hypnos phase 5 → divergence trajectory.
  - `fatigue_observer` — `soma.fatigue`/`soma.report` → fatigue history.
  - `prediction_error_observer` — subscribes to `soma.out`, `chronos.out`,
    `topos.out`, `audition.out`, `phantasia.out`; maintains a sliding-window
    mean/p95/p99 of prediction error; surfaces counts on Nexus diagnostics.
  - `welfare_observer` — §5.5 Welfare/Gray-Zone Events: fatigue threshold crossing
    without subsequent maintenance; sustained extreme Thymos VAD (high
    valence+arousal beyond a configurable window); replay write-rate exceeding the
    consolidation window; surfaces event counts on Nexus diagnostics.
  - `nous_policy_observer` — logs `nous.policy` events: EFE value, planning
    horizon, selected action ID.
- Each observer is read-only and never injects into the cognitive loop (preserves
  the §5.1 non-intrusiveness commitment); Nexus continues to show metadata only.
- `[evaluation.observers]` config toggles per observer; all gated by the existing
  sidecar enable.

## Capabilities

### New Capabilities

- `evaluation-observers`: eight read-only sidecar observers for the v4
  signals (coherence, replay with ID-only logging, Empatheia accuracy, alignment
  divergence, fatigue, prediction error, welfare events, Nous policy).

### Modified Capabilities

None expressed as deltas (extends the existing `evaluation-sidecar` with new
independent observers).

## Impact

- **Depends on:** `evaluation-sidecar` (shipped). Each observer activates as its
  source module lands; all degrade to no-ops when their source stream is absent.
  No observer is a hard blocker on any other change.
- **Privacy:** `replay_observer` defaults to `redact_content = true` (IDs only);
  the §4.4/§5 recording tension and Guardian-consent governance apply unchanged.
- **Repo:** adds `kaine/evaluation/observers/*.py`, tests; `config/kaine.toml`.
