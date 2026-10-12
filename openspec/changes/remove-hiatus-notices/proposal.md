## Why

The owner has asked that no part of the project describe development as paused or on hiatus. Several documents still carry such notices: the README status block, a line in the roadmap appendix, a handoff record written for the pause and listed in the records index, a test-run record, and notes in two active OpenSpec changes.

## What Changes

- The README status block about a hiatus is removed. The project line uses a colon instead of an em dash.
- The roadmap appendix no longer says the project is paused, and it no longer points to the handoff record.
- The handoff record `docs/records/2026-10-06-handoff.md` and its entry in `docs/records/README.md` are deleted. The record exists only to describe the pause, and git history keeps it.
- The K1-Jev W2a smoke-run record titles its gaps list without reference to a hiatus.
- `functional-module-names` (design.md and proposal.md) and `k1-jev-decision-model` (design.md) state their reasoning without reference to a pause.

## Capabilities

### Modified Capabilities

- `documentation-consistency`: the documentation does not describe the project as paused or on hiatus.

## Impact

- **Docs:**
  - `README.md`
  - `docs/appendix-d-roadmap.md`
  - `docs/records/README.md` and the deleted `docs/records/2026-10-06-handoff.md`
  - `docs/records/shakedowns/2026-10-06-k1jev-w2a-0.8b-smoke-run.md`
  - the two active changes named above
- **Behaviour:** none. No code or configuration changes.
