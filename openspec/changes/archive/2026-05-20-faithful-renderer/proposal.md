## Why

`docs/kaine-paper.md` §3.4 calls the Faithful Renderer "a deterministic
template system that takes workspace snapshots and produces ground-truth
natural language renderings without embellishment or connotation, and it
serves both as the system's structured output mechanism and as the
generator of target training pairs for voice alignment." Build prompt
§5.4 names it among Phase 5 modules.

The renderer ships before Lingua because Lingua's intent-expression
logging compares each LLM output against what the renderer would have
produced for the same workspace — the renderer is the "chosen" side
of the DPO pairs Hypnos will train against (Phase 6). It also ships
before any of the audio sub-modules because they are independent of
this piece.

## What Changes

- Introduce `kaine.faithful` package (top-level, not under modules —
  it is consumed by several modules rather than being a module itself):
  - `templates.py` — template rules per module's output type. Each
    template is a pure function `(payload: dict) -> str` returning a
    plain natural-language phrase. The collection is keyed by
    `(source, type)` and an "unknown" fallback yields a structured
    summary.
  - `renderer.py` — `FaithfulRenderer` orchestrating the templates.
    `render_event(event)`, `render_snapshot(snapshot)`. Output is
    plain text — no markdown, no metadata, no LLM-style hedging.
    Deterministic: identical input always produces identical output.
- Ship templates for the modules already in the build:
  `soma.report`, `chronos.report`, `topos.report`, `nous.belief`,
  `mnemos.recall`, `thymos.emotion`, `thymos.drive`, `thymos.state`,
  `thymos.goal`, `eidolon.drift`, `cycle.tick`.
- No bus or module wiring: the renderer is a library callable from
  Lingua (Phase 5.2), Hypnos (Phase 6), and Nexus dev-mode (Phase 8).
- Tests: every template + snapshot composition; determinism check.

## Capabilities

### New Capabilities

- `faithful-renderer`: deterministic, template-based rendering of bus
  events and workspace snapshots into plain natural language. Owns
  the templates registry and the renderer interface.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus` (schema), `module-pattern`
  (WorkspaceSnapshot type). All shipped.
- **Repo:** adds `kaine/faithful/*.py`, `tests/test_faithful_*`,
  updates `pyproject.toml` (packages list).
- **No external deps.** Pure Python.
- **No runtime impact.** Library only; nothing publishes or
  subscribes.
