## 1. Implementation

- [x] 1.1 `preserve_live` includes `stage.json` in the bundle when the stage file exists; a reader returns it from a bundle (`read_bundle_stage`).
- [x] 1.2 `--revive <bundle>` in the cycle entrypoint: stage restored before stage resolution; revive after module initialize; exit 7 on an unreadable bundle or a `ReviveError`; `revived_from` in `runtime.json` and the run context; new faculties logged.
- [x] 1.3 The preserve-request watcher (freeze holder `preserve`, `preserve_live`, result file, optional stop), and `python -m kaine.cycle.control preserve`.
- [x] 1.4 `docs/operations.md`: preserving and reviving an entity; exit code 7.

## 2. Verification

- [x] 2.1 Tests: the stage round-trips through a bundle; revive into a registry with an extra module succeeds and restores the captured modules' state; a bundle whose captured module is not enabled exits 7 before the cycle starts; the watcher freezes, preserves, writes the result, releases or stops, and handles each request once; a failed preservation releases the freeze and reports `ok: false`; the CLI's exit codes.
- [x] 2.2 Offline suite green; `openspec validate operator-revive-and-preserve --strict`.
