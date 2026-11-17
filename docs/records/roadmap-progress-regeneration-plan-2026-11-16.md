# Roadmap progress regeneration plan (2026-11-16)

This record describes how to refresh docs/appendix-d-roadmap.md from OpenSpec task boards without hand-editing progress values or totals. It is a plan only: no documentation files are changed by this record.

## Goal

Refresh the Active changes progress column, drop rows whose changes are no longer active, add rows for active changes that are missing, and update the Backlog totals line, while preserving the human-written Summary text for retained rows.

## Sources of truth

- Active changes: directories directly under openspec/changes/ except archive.
- Archived changes: directories under openspec/changes/archive/.
- Progress: in each active change's tasks.md, count checkbox lines:
  - done: ^\s*- \[x\]
  - todo: ^\s*- \[ \]
  - format: DONE/TOTAL (PERCENT%), where PERCENT = round(100 * done / total) or 0 when total is 0.
- Archived count: number of directories in openspec/changes/archive/.
- Capability spec count: number of directories in openspec/specs/.
- Summaries: retained from existing rows; missing rows need a one-line summary supplied from the change proposal or design note.

## Non-edit posture

Do not run the regenerator against the repository yet. Preview it against a throw-away copy, review the diff, and only then apply it in a feature branch.

## Preconditions

1. Working tree is clean or all intended changes are committed.
2. openspec validate --all passes before and after.
3. A copy of docs/appendix-d-roadmap.md is saved outside the worktree for rollback.

## Execution sequence

### 1. Read-only preview

tmp=$(mktemp -d)
cp -a openspec "$tmp/openspec"
mkdir -p "$tmp/docs"
cp docs/appendix-d-roadmap.md "$tmp/docs/appendix-d-roadmap.md"
python3 tools/maintainer/regen_roadmap_progress.py "$tmp"
diff -u docs/appendix-d-roadmap.md "$tmp/docs/appendix-d-roadmap.md"

Expected output from the regenerator includes drop row lines for archived changes already present in the active table, ACTIVE BUT NOT LISTED for active changes with no row, and updated counts and totals.

### 2. Archive verification before regenerating

For every change currently listed in Active changes that the preview reports as dropped, confirm that it has a matching dated directory in openspec/changes/archive/. If a completed change is not archived, archive it with openspec archive before proceeding.

### 3. Add missing active rows

The regenerator does not add rows. Add one row per item in ACTIVE BUT NOT LISTED, using the same table shape.

Use the current task counts from the change's tasks.md for the second column; they will be regenerated exactly on the final run.

Currently missing as of this plan:
- episodic-recall-content
- organ-self-denial-ablation
- sam-voice-training
- stimulus-control-act
- unified-instance-configuration
- welfare-indicator-response

### 4. Regenerate progress values and totals

Run the regenerator against the real worktree:

python3 tools/maintainer/regen_roadmap_progress.py .

This rewrites only the Progress column for rows in Active changes and the Backlog totals sentence. It preserves summaries.

### 5. Reconcile archived-change status rows

Review the Open operator and device steps table separately. The regenerator does not touch it. Add any newly archived change that has an operator or device step, using the same From change and Step shape, and remove rows whose steps are complete.

## Verification

1. Re-run the read-only comparison from step 1 after the real run; the second preview should show no Progress changes and no ACTIVE BUT NOT LISTED lines.

2. Validate OpenSpec with openspec validate --all.

3. Check the counts independently with a small Python script. The printed active, archived, and spec counts must equal the Backlog totals sentence in the roadmap.

4. Build the documentation book if available (mdbook build docs) and check that the roadmap renders with no table shape errors.

5. Review git diff -- docs/appendix-d-roadmap.md before committing. Confirm that only the Progress column and totals sentence changed for existing rows, archived changes were removed, missing active changes were added, and no summary text was accidentally altered.

## Rollback

Restore the saved copy of docs/appendix-d-roadmap.md and discard the commit. The regenerator is idempotent, so a failed run can be repeated after correcting the row scaffolding.
