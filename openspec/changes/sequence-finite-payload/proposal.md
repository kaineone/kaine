## Why

Before the first interaction, the sequence module publishes `time_since_last_interaction_s` as `math.inf`. Python's `json.dumps` writes that as the bare token `Infinity`, which is not JSON: strict parsers reject it, and the research event observer copies the field into the research records, where the paper's range sweep requires every logged number to be in range. The value already travels as `null` in saved state, and both readers (the affect module's social drive and the text renderer) treat a missing or non-finite value as "no interaction yet".

## What Changes

- `sequence.report` carries `time_since_last_interaction_s: null` until the first interaction, then the finite elapsed seconds as before.
- The internal helper returns `None` for "no interaction yet"; the saved-state form is unchanged (`null`).
- Docs say `null` where they said `inf`.

## Capabilities

### Modified Capabilities

- `sequence`: the report payload is strict JSON; no interaction yet is `null`.

## Impact

- `kaine/modules/sequence/module.py`, `tests/test_sequence_module.py`, `docs/09-modules/sequence.md`.
- Readers: the affect module already ignores non-numbers; the renderer already skips `None`. No behaviour change beyond the encoding.
