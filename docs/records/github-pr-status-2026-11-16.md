# GitHub PR status (2026-11-16)

Snapshot of open pull requests, CI/test status, and GitHub Advanced Security (GHAS) alerts.
Generated from `gh pr list --state open` and `gh pr checks`.

## Summary

- Open PRs: 7 (1 draft).
- Required CI gates pass on 6 PRs; draft PR 818 fails the offline pytest gate.
- GHAS open alerts: 2 code-scanning (both non-security lint/style findings in test fixtures); 0 dependabot open alerts; 0 secret-scanning open alerts.

## Open PRs

| PR | Title | Branch | State | CI status | Notes / next action |
|---:|---|---|---|---|---|
| 823 | chore(deps): Update playwright requirement from >=1.64.1 to >=1.65.1 | dependabot/pip/playwright-gte-1.65.1 | OPEN | All checks pass: CodeQL, analyze, lint-imports, pytest offline (py3.11/py3.12/torch min), redteam, ruff | Low-risk dependency bump. Merge via normal queue after review. |
| 822 | chore(deps): Update librosa requirement from <1,>=0.10 to >=0.11.0,<1 | dependabot/pip/librosa-gte-0.11.0-and-lt-1 | OPEN | All checks pass | Low-risk dependency bump. Merge via normal queue after review. |
| 821 | chore(deps): Update fastapi requirement from <1,>=0.143.0 to >=0.162.5,<1 | dependabot/pip/fastapi-gte-0.162.5-and-lt-1 | OPEN | All checks pass | FastAPI upgrade merits a smoke check of web/setup routes; otherwise merge after review. |
| 820 | chore(deps): Update peft requirement from <1,>=0.21.0 to >=0.21.2,<1 | dependabot/pip/peft-gte-0.21.2-and-lt-1 | OPEN | All checks pass | Low-risk dependency bump affecting training helpers. Merge after review. |
| 819 | chore(deps): Update pytest-asyncio requirement from >=1.4.0 to >=1.4.1.post1 | dependabot/pip/pytest-asyncio-gte-1.4.1.post1 | OPEN | All checks pass | Test-only dependency. Merge after review. |
| 818 | feat: audition encoder bake-off script (task 6.6) | feat/audition-encoder-bakeoff | DRAFT | CodeQL, analyze (python), lint-imports, redteam, ruff pass; pytest offline suite FAILS on all 3 variants (py3.11, py3.12, py3.12 torch min) | Failing test: `tests/test_rename_modules_repo.py::test_full_repo_dry_run_deterministic` (`IndexError: list index out of range` in `tools/maintainer/rename_modules.py:_offset`, via `_python_contexts`). Appears tied to the maintainer rename-module fixture/repo-dry-run path rather than the audition bake-off change. Next action: reproduce locally and fix or mark as pre-existing/unrelated before moving PR 818 out of draft. |
| 815 | feat: Stage 2 voice alignment and K-candidate sampling | feat/voice-dev-stage2-alignment | OPEN | All checks pass: CodeQL, analyze, lint-imports, pytest offline (py3.11/py3.12/torch min), redteam, ruff | Feature PR. Next action: adversarial review, then enqueue/merge. |

## GHAS alerts

### Code scanning (open: 2)

1. Alert 1026: `py/import-and-import-from`, state open, severity null
   - File: `tests/fixtures/rename_modules/persisted_names_in_import_paths/after/kaine/runner.py`
2. Alert 953: `py/unused-local-variable`, state open, severity null
   - File: `tests/fixtures/rename_modules/false_positives/before/kaine/boot/feed.py`

Both are non-security code-quality findings inside rename-module test fixtures. No action required for release; either leave as fixture inputs or dismiss as test fixtures.

### Dependabot (open: 0)

No open Dependabot alerts.

### Secret scanning (open: 0)

No open secret-scanning alerts.

## Recent PR check run

Latest per-PR `gh pr checks` captured above (all required gates listed). Draft PR 818 is the only failing gate; all other open PRs are green.
