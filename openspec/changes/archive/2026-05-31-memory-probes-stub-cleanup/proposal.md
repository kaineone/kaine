## Why

`kaine/evaluation/memory_probes.py:45-50` defines:

```python
def reconstruction_accuracy(
    response: str, memory: dict[str, Any], embedder: TextEmbedder
) -> float:
    """Placeholder synchronous-friendly stub — actual scoring requires
    an embedding round-trip. Real implementation lives in `score_async`."""
    return 0.0
```

The real scorer is `score_async` immediately below, which is what
`MemoryProbeRunner.run_once` actually calls. The sync stub is unused
anywhere in `kaine/` and nothing imports it from outside the file.
It's dead code that returns `0.0` and could mislead a future maintainer
into thinking memory probes are broken.

Trivial hygiene fix. Lands as its own minimal change so there's a
clean audit trail and no spurious commits mixed into the larger
voice-alignment or adapter-merge changes.

## What Changes

- Delete `reconstruction_accuracy` function from
  `kaine/evaluation/memory_probes.py`.
- Verify no imports of the symbol exist anywhere
  (`git grep reconstruction_accuracy`) — expected to come up empty.
- Run the full test suite — no test should reference the deleted
  symbol (verified pre-flight; the runner uses `score_async`).

## Capabilities

### Modified Capabilities

- `evaluation-sidecar` (existing) — `memory_probes.py` loses a
  dead helper function. No behavior change.

## Impact

- **No behavior change.** Dead-code removal only.
- **No new deps.**
- **Tests unchanged.** The runner test already exercises the real
  `score_async` path.
- Folded into the next merge (no separate tag needed). Can land
  alongside `voice-alignment-training` or as a standalone hygiene
  commit, operator's choice.
