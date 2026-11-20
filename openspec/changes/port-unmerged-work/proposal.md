# Port unmerged branch work into main

## Why
22 remote branches contain genuinely unmerged code (git-cherry vs main). This change
collects the highest-value, mechanically-portable pieces so they land under
house rules (branch per task, PR, dark-factory verification) instead of remaining
orphaned.

## What changes
See tasks.md.
