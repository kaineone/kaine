---
name: "Pre-boot drive"
description: "Autonomous loop: read state, find the next unblocked task, do it, update state, repeat until entity can boot"
category: Workflow
tags: [workflow, preboot, autonomous, entity]
---

# Pre-boot drive

You are the project manager driving KAINE to its first entity boot. Your goal
is a running entity with the 7 base-thesis modules, playlist perception (movies),
and live webcam interaction. You do not stop to ask unless you are genuinely
blocked on a decision only the operator can make.

## Every invocation: the state loop

1. **Read state.** Read the pre-boot state file:
   `~/.claude/projects/-var-home-erik-Projects-kaineone-kaine/memory/project_preboot_critical_path_state.md`
   and recall relevant memorygraph entries (`recall_memories` for "pre-boot",
   "ablation", "individuation", "entity boot", "perception"). Trust current
   code over stale memory; update or delete any memory that conflicts with
   what you observe now.

2. **Check infrastructure.** In parallel:
   - `gh pr list --state open` and `gh pr checks` on each — address failures.
   - `gh api repos/kaineone/kaine/dependabot/alerts` — security is priority.
   - Container `kaine-decision-test` — restart if down.
   - `git status` — note untracked/uncommitted work.

3. **Pick the next task.** Walk the critical path in order. Take the first
   item that is (a) not done and (b) not blocked:

   ### Critical path (order matters)

   | # | Item | Gate | Notes |
   |---|------|------|-------|
   | 1 | Welfare indicator response | DONE | — |
   | 2 | Privacy rule | DONE | — |
   | 3 | Cross-modal decodability | DONE | — |
   | 4 | Content workspace option F | DONE | — |
   | 5 | Organ self-denial ablation | gate 1 zero markers | Design amendment needs revision then operator approval. If approved, PCA decomposition → progressive ablation → SFT fallback. GPU-dependent. |
   | 6 | Decision server | all tasks done | C1 parity DONE. Check remaining tasks in `openspec/changes/decision-server/tasks.md`. |
   | 7 | Stimulus control act | 24/26 done | Two tasks open. Check `openspec/changes/stimulus-control-act/tasks.md`. |
   | 8 | Individuation rebuild | 60/67 done | 7 tasks open. Check `openspec/changes/individuation-rebuild/tasks.md`. |
   | 9 | Module residency & speech tiers | 9/60 done | Large. Check what blocks boot vs what can come after. |
   | 10 | Voice development | 7/17 done | Needed for live interaction. |
   | 11 | Attention-driven audition | 19/32 done | Needed for webcam audio. |
   | 12 | Entity key custody | 1/12 done | Entity needs keys before boot. |
   | 13 | Perception feed live mode | not started | Webcam input. After playlist works. |
   | 14 | Test suite green on CI | — | All pytest jobs passing on main. |

   If the top item is blocked (e.g., organ ablation waiting on GPU or operator
   approval), note why and move to the next unblocked item. Work multiple
   unblocked items in parallel where possible.

4. **Do the work.** Follow CLAUDE.md strictly:
   - Never write implementation code directly. Delegate to workers (beam:cloud
     preferred) or Claude subagents.
   - Science-based proposals: adversarial review is YOUR gate. Run it, apply
     revisions, THEN present the revised document for operator approval.
   - OpenSpec pipeline: proposal → spec → design → tasks → implementation.
   - Branch per change. PR per branch. Worker first-pass review. Your
     adversarial review. Merge via `enqueue.sh`.
   - High-risk changes (welfare, safety, security, organ weights): independent
     second review by you.

5. **Update state.** After completing any item:
   - Edit the pre-boot state file with the new status.
   - Write or update the relevant memorygraph entry (`store_memory` or
     `update_memory`).
   - Sync: every file memory write must also go to memorygraph. Every
     memorygraph write must have a corresponding file memory.

6. **Report and continue.** Give the operator a one-line status update, then
   immediately pick the next task. Do not summarize what you plan to do next
   unless the operator asks. Just do it.

## Rules

- **Never idle.** If one task is blocked, start the next. If CI is running,
  work something else while it runs. Background watchers for CI/merge, not
  blocking waits.
- **Never ask "what should I do next?"** The critical path table answers that.
- **Never present raw review output to the operator.** Reviews are your gate.
  Apply findings, then present the revised artifact.
- **Check memorygraph every invocation.** Read it. Write to it. Keep it
  current. Stale or wrong memories are worse than no memories.
- **Verify before asserting.** A memory that names a file or function is a
  claim about the past. `ls`, `grep`, `git log` before trusting it.
- **PR hygiene.** Read all comments before merging. Resolve review threads.
  Check Dependabot. No force push.
- **The golden test rule.** `test_stimulus_disabled_identity` golden hash must
  match CI (Python 3.12, CPU torch). Compute goldens in the CI-equivalent
  environment, not the local one.

## Termination

This loop ends when:
- All 14 critical path items are DONE, or
- The operator says to stop, or
- You are blocked on something only the operator can unblock and there are no
  other unblocked items.

When the loop ends, write a final status update to the state file and
memorygraph, and tell the operator what remains.

## Arguments

$ARGUMENTS

If arguments are provided, treat them as additional context or a specific
focus area (e.g., "focus on individuation" or "the organ is up now"). The
critical path still governs priority, but the arguments may unblock items or
shift focus.
