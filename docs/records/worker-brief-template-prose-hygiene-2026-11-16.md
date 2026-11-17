# Worker brief template and prose hygiene protocol — 2026-11-16

Template for any OpenSpec, roadmap, or code task handed to an Ollama cloud
worker or Claude subagent. Keep the brief single-directive, flush-left code, and
full file bodies.

## 0. Mandatory pre-build search and licence check

Before any code is sent to a worker:

1. Search the repo for existing helpers, module paths, and prior art.
   Use `git log -S` and `grep -R` on the terms in the task scope.
2. Confirm licence compatibility of any new dependency, library, or vendored
   snippet against KAINE's CAL v0.2 before adding it. Note the licence in the
   task file.
3. Verify no duplicate OpenSpec change already covers the task. List
   `openspec/changes/` and check `tasks.md` checkbox state.
4. Record the check outcome in the task note or PR description.

These steps are not optional and may not be skipped for "small" changes.

## 1. Brief format and code style

- Output blocks use the worker format: `@@@FILE path` then content, then
  `@@@END`. No other wrapper.
- Code is flush-left inside heredocs. Never indent the code body.
- Provide the complete file body, never patches or diffs. Workers mishandle
  hunk arithmetic.
- Quote the exact helper names taken from the repo. Workers invent names.
- Put tests in the module named in the task, not ad-hoc paths.
- Strip control characters from worker output before applying.
- State the output format once at the top. No few-shot examples beyond one.
- Single directive only. No hedging.

## 2. Whole-file insertion rules

- Whole-file replacement is allowed for files under 200 lines or when a change
  rewrites most of the file.
- For files above 200 lines, anchor edits use `@@@EDIT` SEARCH/REPLACE blocks
  applied by `tools/maintainer/apply_edits.py`.
- The SEARCH block must match the file exactly, including whitespace, and occur
  once.
- Never mix a whole-file replace with a patch of the same file in one brief.
- State the edit mode (whole file or anchor blocks) explicitly in the task.

## 3. Flush-left constraint

All code bodies are flush-left. No leading spaces or tabs before statement lines.
This holds for every heredoc and every pasted block in the brief and review.

## 4. Direct edit limit

No direct unreviewed source edit may exceed 20 lines. Anything larger goes through
the worker pipeline: feature branch, PR, worker first-pass review, Claude
adversarial review, merge. Small cleanups under the limit are acceptable when
they do not alter behaviour.

## 5. Test commands before any push

Run the relevant gate set before pushing. At minimum:

- `pytest -q <touched module tests>` on the affected tests, or the full suite
  when shared code changes.
- `ruff check` on changed Python files (lint module and isort config).
- `python -m pytest` peak memory stays under the 16 GB watchdog stated in
  `reference_suite_memory_ceiling.md`; use `safe-run.sh` for heavy runs.
- Dependency and import graph check: `lint-imports` if the change touches
  package boundaries.
- Container or GPU paths: hold the `gpu-lock.sh` lock and verify peak RSS.
- List the exact commands in the PR description.

Nothing is pushed without these passing locally.

## 6. Global concurrency and retry/backoff

- Global concurrency cap is 4 Ollama cloud requests in flight at once. Excess
  requests queue, so schedule no more than 4 parallel workers.
- Each worker call retries on empty or truncated responses. Use exponential
  backoff at 2 s, 4 s, 8 s, 16 s, then stop. Four retries maximum.
- Empty responses usually mean a defective brief. Re-run with reasoning visible
  before declaring an outage. See the KAINE CLAUDE notes on empty responses.
- Record retry counts and final outcome in the task note.

## 7. OpenSpec and roadmap update

- OpenSpec task files under `openspec/changes/<name>/tasks.md` track progress.
  Tick a box only when disk evidence exists, not on an agent's report.
- Update `ROADMAP.md` or the atomic roadmap record alongside any merged PR.
- New work packages get a `design.md` plus `tasks.md` under
  `openspec/changes/<name>/`.
- High-risk tasks (welfare, safety, security, encryption, persistence) need an
  Opus second review before merge.
- Run `regen_roadmap_progress.py` after task checkbox changes.

## 8. Prose hygiene

All prose in the brief, PR description, commit message, and docs must pass the
prose hygiene skill before push.

- Skill path: `/home/erik/.claude/skills/prose-hygiene/SKILL.md`
- Run `/prose-hygiene` on every documentation file before any `git push`.
- Standing constraints include: no em dashes, banned vocabulary list, banned
  phrases, banned structural patterns (tricolons, negative parallelism, staccato
  runs, participial tails), and Claude-specific tells.
- Full rule set lives in the skill file linked above. Read it before editing
  prose.
- Apply the same rules to chat summaries and review comments, not only docs.

## 9. Assign and review

1. Open a feature branch named after the change.
2. Dispatch the worker with `--model` or `WORKER_MODEL` set (beam is default).
   Prefer `beam:cloud`; `gpt-oss:120b-cloud` as backup; `kimi-k2.7-code:cloud`
   as last resort. Banned: all Gemma and Meta (Llama, Muse, derivatives).
3. Worker returns one first-pass review note.
4. Claude runs an adversarial review against `review-template.md` patterns.
5. Merge only when the preflight gate is green and no findings remain.
6. Push promptly after the gate passes; do not leave commits local.
