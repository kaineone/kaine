# Repository hygiene snapshot - 2026-11-16

Docs-only inventory of the repository state after the 2026-11-16 commit wave. No files, refs, branches, caches, logs, or working-tree changes were removed.

## Repository

- Branch: `feat/audition-encoder-bakeoff`
- Upstream: `origin/feat/audition-encoder-bakeoff`
- Base repository: `git@github.com:kaineone/kaine.git`
- HEAD: `c1fcc861` (`2026-11-16 16:30:44 -0800 feat: wave of audition maternal-voice + docs/records (py_compile/test gate green)`)

## Recent commits on the current branch

- `c1fcc861` `2026-11-16 16:30:44 -0800` feat: wave of audition maternal-voice + docs/records (py_compile/test gate green)
- `27e37779` `2026-11-16 15:36:15 -0800` fix: add narrow noqa: E402 to sys.path-imported tests
- `55303a68` `2026-11-16 15:34:29 -0800` fix: GitHub Advanced Security alert fixes on PR 818
- `d05e1c4c` `2026-11-16 15:26:57 -0800` feat: deterministic audition feed replay loader (task 6.6)
- `fd080b30` `2026-11-16 15:25:40 -0800` Add low-risk deliverables: maternal prosody tools, audition feed bench, records
- `871ffe0a` `2026-11-12 20:02:06 -0800` feat: audition encoder bake-off script (task 6.6)

## Tracked working-tree change

- `M config/kaine.toml`
- Diff: `model_id = "kaineone/Qwen3.5-4B-abliterated-GGUF"` changed to `model_id = "kaineone/Qwen3.5-4B-abliterated-GGUF:latest"` at the relevant setting.

## Untracked files

These are present in the working tree but are not tracked:

- `.claude/hooks/enforce-worker-coding.sh` (1,970 bytes; executable)
- `CLAUDE.md` (1,263 bytes)
- `tests/test_validate_config_shape.py` (4,808 bytes)
- `openspec/changes/individuation-rebuild/validation/runs/smoke-20261113T023732Z.json` (3,627 bytes)
- `openspec/changes/individuation-rebuild/validation/runs/smoke-20261113T025759Z.json` (3,626 bytes)
- `openspec/changes/individuation-rebuild/validation/runs/smoke-20261113T030433Z.json` (3,761 bytes)

No tracked files were removed or reset. `git clean` was not used.

## Git-ignored protected leftovers

These are intentionally ignored by Git and remain untouched. They include local environment, secrets, runtime state, caches, prior evaluations, external source artifacts, and generated validation data.

Ignored-location counts by top-level path:

| Top-level path | Ignored entries |
| --- | ---: |
| `kaine` | 53 |
| `data` | 16 |
| `external` | 6 |
| `tests` | 4 |
| `.ruff_cache` | 4 |
| `.import_linter_cache` | 4 |
| `.grimp_cache` | 4 |
| `tools` | 3 |
| `scripts` | 3 |
| `.claude` | 3 |
| `openspec` | 2 |
| `docs` | 2 |
| `config` | 2 |
| `compose` | 2 |
| `.venv` | 1 |
| `state` | 1 |
| `secrets` | 1 |
| `.pytest_cache` | 1 |
| `kaine.egg-info` | 1 |
| `.chatterbox-venv` | 1 |
| `backups` | 1 |

Representative protected leftovers include:

- `.chatterbox-venv/`
- `.claude/scheduled_tasks.lock`
- `.claude/settings.local.json`
- `.claude/worktrees/`
- `.venv/`
- `backups/`
- `compose/.env`
- `compose/kaine.study.local.yml`
- `config/kaine.operator.toml`
- `config/secrets.toml`
- `secrets/`
- `state/`
- `.ruff_cache/`, `.grimp_cache/`, `.import_linter_cache/`, and `.pytest_cache/`
- `docs/records/oscillatory-ablation-positive-control-2026-11-16.jsonl`
- `docs/records/validation/self-rhythm-rests/__pycache__/`
- `openspec/changes/individuation-rebuild/validation/calibration_abliteration_probes.jsonl`
- `openspec/changes/individuation-rebuild/validation/runs/lifetime.json`
- `openspec/changes/individuation-rebuild/validation/runs/mmd.json`
- `openspec/changes/individuation-rebuild/validation/runs/power.json`
- `openspec/changes/individuation-rebuild/validation/runs/size.json`
- `external/*/` and `*/__pycache__/`
- `data/evaluation/*`
- `kaine/__pycache__/`, `tests/__pycache__/`, `scripts/__pycache__/`, and `tools/__pycache__/`

These were not deleted or modified.

## Git refs

- Remote:
  - `origin git@github.com:kaineone/kaine.git (fetch)`
  - `origin git@github.com:kaineone/kaine.git (push)`
- Local refs: 191
- Remote-tracking refs: 45
- Tags: 0
- Local branches whose upstream is `gone`: 115

The retained refs include several abandoned-in-upstream tracking branches, backup branches, feature branches, and work-package branches. Their presence is recorded here; no branches were pruned. A `gone` upstream state means only that the remote tracking branch no longer exists; it does not indicate a deleted local branch or a deletion performed by this snapshot.

## Conclusion

This is a hygiene snapshot only. The working tree still contains one tracked modification (`config/kaine.toml`), six untracked files, and the ignored protected leftovers described above. All repository refs remain intact. System generated note: run `git status --short --branch` and `git for-each-ref` to reproduce this inventory.