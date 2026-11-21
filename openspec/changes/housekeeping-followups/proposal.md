# Housekeeping follow-ups and unwired code

## Why
The scout audits (maternal voice, stimulus, audition, voice development,
general hygiene) flagged remaining mechanical, code-level items that are
unblocked and do not need a GPU or operator hardware. This change collects
them so the dark factory can run them without human intervention.

## What changes
- Fix Sam generator checkpoint assertions and --reference-dir gating.
- Implement render_maternal_voice_sam adapter-boundary validation.
- Fix mixed sync/async pytestmark in stimulus tests.
- Remove leftover placeholder shebang/license gaps (already partially done).
- Wire first-hours criterion, per-pass mode, feed colour interpolation
  (already done in this pass).
- openspec validate all active changes.

## Scope
Low-risk code hygiene and wiring. No new features, no GPU work.
EOF