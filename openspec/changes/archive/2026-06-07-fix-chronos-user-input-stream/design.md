## Context

Producer streams in KAINE are `<module>.out` where module names use underscores
(`audio_in.out`). Several modules consume peer streams by name pulled from
`config/kaine.toml`. A dot/underscore typo in such a reference fails silently:
the consumer simply reads an always-empty stream.

## Goals / Non-Goals

**Goals:** Chronos receives Audio In transcription events; a test makes any
config stream-reference typo fail loudly.

**Non-Goals:** No change to module code, the stream-naming convention, or how
Chronos featurizes interaction timing. Not parameterizing Lingua's hardcoded
stream names (separate concern).

## Decisions

- **Fix the config value, add a consistency test.** The bug is purely the
  reference string. The durable defense is a test that resolves every
  config-declared stream reference against the canonical producer-stream set
  (`{<module>.out} ∪ {workspace.broadcast, cycle.out, lingua.external,
  lingua.internal}`); anything outside that set is a wiring error.
- **Derive producer names via `module_stream()`**, not literals, so the test
  tracks the real naming rule.

## Risks / Trade-offs

- [The consistency test could be over-strict if a future stream is intentionally
  external] → the canonical set is explicit and easy to extend with a comment
  when a genuinely new producer is added.
