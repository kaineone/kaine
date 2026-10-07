<!-- SPDX-License-Identifier: LicenseRef-CAL-0.2 -->
# Maintainer tools

These are the scripts the maintainers use to gate, review and merge pull requests. They are not part of the runtime, and nothing in `kaine/` imports them. They assume a Linux host with `git`, `gh` (signed in), `systemd --user`, the project's virtualenv at `<main checkout>/.venv`, and, for the worker scripts, a local [Ollama](https://ollama.com) endpoint.

| Script | What it does |
| --- | --- |
| `preflight-gate.sh WORKTREE` | The local pre-flight gate: ruff, import contracts, the red-team tests, the fast suite in parallel (CPU-only), and the slow lane when the branch touches a slow path. Run it before every push; it prints `PREFLIGHT GREEN` or `PREFLIGHT RED`. `GATE_WORKERS` sets the parallelism. |
| `safe-run.sh CMD...` | Runs a heavy command in a transient systemd user scope, capped at `SAFE_RUN_MEM` (default 16G) with no swap and at low CPU and I/O priority, so a runaway test cannot freeze the desktop. |
| `enqueue.sh PR` | Adds a signed-off pull request to `main`'s merge queue through the GraphQL API. All review threads must be resolved first. |
| `enqueue-when-green.sh PR...` | Enqueues each pull request in order once all its required checks pass; skips one with a failed check. |
| `review-pr.sh PR OUT_DIR [CONTEXT...]` | The worker model's first-pass review. It builds a brief from `review-template.md`, the description and the diff, and writes `OUT_DIR/response.txt`. Every finding is input for the human or lead review, never a verdict. |
| `worker.py BRIEF OUT_DIR [--allow PATH...] [--apply REPO]` | Sends a brief to the worker model through Ollama's HTTP API and saves the response and its reasoning. With `--apply` it writes allow-listed `@@@FILE` blocks into a checkout. An empty response is almost always a defective brief: read `thinking.txt`. |
| `apply_edits.py RESPONSE REPO --allow PATH...` | Applies anchored `@@@EDIT` search/replace blocks from a worker response. It is atomic: if any SEARCH text does not match exactly once, nothing is written. |
| `apply_seq.py` | Applies chained edits in order, each against the result of the previous one. |
| `regen_roadmap_progress.py CHECKOUT` | Refreshes `docs/appendix-d-roadmap.md` from `openspec/`: each active change's progress, rows for changes no longer active, and the totals line. |
| `gpu-lock.sh CMD...` | Runs a command holding the host-wide GPU lock, so training, calibration and validation runs never share the GPUs. `GPU_LOCK_PRIORITY=1` lets an approved job go next. |

## Restacking a stacked pull request

Pull requests merge as squash commits, so a stacked pull request conflicts with `main` once the one beneath it merges. Merge `origin/main` into it. A conflicted file may take the branch's side only when `main`'s copy is byte-identical to the copy of the base that the branch carries. Every other conflict needs a hand merge and a fresh review. Then gate, push and enqueue.
