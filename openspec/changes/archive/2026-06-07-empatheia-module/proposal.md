## Why

`KAINE_Paper_v4.md` §3.3.2 introduces **Empatheia**, the social-cognition / theory-
of-mind module. It builds and maintains models of other agents (emotional
patterns, behavioral tendencies, reliability, relationship history), publishes
**social prediction errors** when an agent's behavior deviates from its model, and
drives the **affect coupling coefficient** in Thymos: agents with longer history
and better-characterized models produce stronger coupling. No such module exists
today; KAINE currently has no representation of *who* it is interacting with.

Empatheia is a prerequisite for `thymos-affect-coupling` (the familiarity score)
and is the eleventh module of the fourteen.

## What Changes

- New module package `kaine/modules/empatheia/`:
  - `agent.py` — `AgentModel` dataclass (id/label, emotion histogram, behavioral
    feature summary, reliability, interaction count, first/last seen) + a
    `familiarity()` score derived from interaction count and model coverage.
  - `store.py` — agent-profile persistence: `AgentStore` protocol with
    `serialize()` / `deserialize()`; **Reuse Qdrant** (new collection
    `empatheia_agents`) + the existing all-MiniLM-L6-v2 embedder for behavioral
    similarity; in-memory backend for tests, mirroring Mnemos.
  - `module.py` — `Empatheia(BaseModule)`. Consumes `audition.emotion` and
    `audition.transcription` (which exist only after `rename-audition-vox`
    merges) and the workspace broadcast to attribute observed behavior to an
    agent; updates the agent model; publishes `empatheia.agent_model` (carrying
    the familiarity score) and `empatheia.social_error` when behavior deviates.
- `EmpatheiaMergeStrategy` (mirroring `MnemosMergeStrategy`): supports the
  fork/merge subsystem via `serialize()` / `deserialize()` on `AgentStore`;
  reconciles diverged profile sets by combining interaction counts and merging
  histograms; persists the merged profile to Qdrant before completing.
- `empatheia.social_error` is a **salience-only signal**: it enters the workspace
  and raises attention by its salience value; the sidecar records every emission.
- Agent identity v1: a single conversational partner keyed by an operator-set
  speaker label (default `"operator"`); speaker diarization is future work
  (paper §10) and the design leaves a seam for it.
- `[empatheia]` config + `[modules].empatheia = false`; `make_empatheia` factory.
- **FaithfulRenderer templates** for `empatheia.agent_model` and
  `empatheia.social_error` added to `kaine/faithful/templates.py`.

## Capabilities

### New Capabilities

- `empatheia`: per-agent modeling, familiarity scoring, social prediction errors,
  Qdrant-backed agent profiles with fork/merge support.

### Modified Capabilities

None (Thymos coupling that *consumes* the familiarity score is a separate change,
`thymos-affect-coupling`).

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `rename-audition-vox` (consumes
  `audition.emotion` / `audition.transcription` which only exist post-rename),
  `mnemos` (reuses the Qdrant + embedder infra patterns), `fork-merge`
  (EmpatheiaMergeStrategy).
- **No new package:** reuses Qdrant + sentence-transformers already in the stack.
- **Consumed by:** `thymos-affect-coupling` (`empatheia.agent_model` familiarity);
  the evaluation sidecar (`sidecar-observers`) scores agent-model accuracy and
  records every `empatheia.social_error`.
- Ships disabled-by-default.
