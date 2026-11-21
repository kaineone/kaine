# Agent records removed from the tree (2026-11-20)

These 69 notes arrived on main in #826 (squash `a1c9df8e7`, 2026-11-17), a
129-file squash titled as a one-line rename-module fix. Agents wrote them on
2026-11-16 without review. Many held local paths from one machine, and they
read as decisions or results that no one checked. They are removed from the
tree, and git history keeps every one. To read one:

    git show a1c9df8e7:docs/records/<name>

The data records from the same squash stay: `audition-encoder-bakeoff.json`
and `audition-feed-bench-synthetic.json`. `audition-encoder-bakeoff-1200blocks.json`
was console output saved under a `.json` name; it is kept as
`audition-encoder-bakeoff-1200blocks.txt`. On 1200 blocks it ranks WavJEPA
(AUC 0.997) above spectral (0.989), the reverse of the 600-block record behind
the spectral default.

## Removed

- `CLEANUP-readiness.md`
- `agent-runner-job-queue-manual-2026-11-16.md`
- `atomic-roadmap-2026-11-13.md`
- `attention-6-10-revision-anchoring-2026-11-16.md`
- `attention-audition-safety-2026-11-16.md`
- `audition-encoder-decision-note-2026-11-16.md`
- `audition-feed-integration-note-2026-11-16.md`
- `audition-feed-integration-pass-2026-11-16.md`
- `audition-feed-variant-readiness-2026-11-16.md`
- `audition-paper-revision-note-2026-11-16.md`
- `audition-salience-recalibration-2026-11-16.md`
- `audition-salience-recompute-protocol-2026-11-16.md`
- `audition-sensor-feed-checklist-2026-11-16.md`
- `base-thesis-atomic-plan-2026-11-16.md`
- `branch-cleanup-command-list-2026-11-16.md`
- `branch-cleanup-pre-execution-report-2026-11-16.md`
- `branch-cleanup-verification-template-2026-11-16.md`
- `branch-hygiene-audit-2026-11-16.md`
- `branch-integration-gate-report-2026-11-16.md`
- `branch-pr-chunking-2026-11-16.md`
- `branch-pr-execution-log-2026-11-16.md`
- `branch-pr-sequence-2026-11-16.md`
- `episodic-recall-preregistration-note.md`
- `feed-replay-implementation-report-2026-11-16.md`
- `github-pr-status-2026-11-16.md`
- `individuation-10-3b-command-plan-2026-11-16.md`
- `maternal-prosody-check-run-2026-11-16.md`
- `maternal-prosody-fixture-plan-2026-11-16.md`
- `maternal-prosody-smoke-plan-2026-11-16.md`
- `maternal-sam-conversion-phase2-2026-11-16.md`
- `maternal-sam-implementation-probe-2026-11-16.md`
- `maternal-sam-openspec-package-note-2026-11-16.md`
- `maternal-voice-sam-conversion-plan-2026-11-16.md`
- `maternal-voice-sam-hf-preflight-2026-11-16.md`
- `maternal-voice-sam-prosody-design-2026-11-16.md`
- `maternal-voice-sam-readiness-2026-11-16.md`
- `maternal-voice-sam-render-plan-2026-11-16.md`
- `maternal-voice-sam-seed-utility-status-2026-11-16.md`
- `maternal-voice-sam-smoke-2026-11-16.md`
- `maternal-voice-unintelligible-gate-2026-11-16.md`
- `openspec-archive-candidate-2026-11-16.md`
- `openspec-dry-run-preparedness-2026-11-16.md`
- `openspec-pattern-check-2026-11-16.md`
- `openspec-strict-sweep-2026-11-16.md`
- `openspec-triage-board-2026-11-16-2.md`
- `positive-control-command-map-2026-11-16.md`
- `positive-control-pre-execution-checklist-2026-11-16.md`
- `positive-control-preliminary-2026-11-16.md`
- `positive-control-run-id-audit-2026-11-16.md`
- `positive-control-threshold-audit-2026-11-16.md`
- `proposal-completion-pulse-2026-11-16.md`
- `repository-hygiene-snapshot-2026-11-16.md`
- `roadmap-progress-regeneration-plan-2026-11-16.md`
- `state-root-validation-guide-2026-11-16.md`
- `stimulus-control-4-7-validation-procedure-2026-11-16.md`
- `unified-instance-config-status-2026-11-16.md`
- `voice-development-requirement-tightening-2026-11-16.md`
- `welfare-6-5-blocker-summary-2026-11-16.md`
- `welfare-6-5-scratch-90m-2026-11-16.md`
- `welfare-6-5-scratch-run-2026-11-16.md`
- `welfare-freeze-review-2026-11-16.md`
- `welfare-indicator-validation-boot-2026-11-16.md`
- `welfare-response-trigger-investigation-2026-11-16.md`
- `welfare-trigger-experiment-update-2026-11-16.md`
- `welfare-validation-boot-2026-11-16.md`
- `welfare-validation-clean-run-2026-11-16.md`
- `worker-brief-template-prose-hygiene-2026-11-16.md`
- `worktree-agent-triage-2026-11-16.md`
- `worktree-branches-merge-safety-2026-11-16.md`
