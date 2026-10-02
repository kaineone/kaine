# The Nexus merge form can choose which world model continues

## Why
`ForkManager.merge` refuses to merge two snapshots that both carry a Phantasia world model unless the caller names which parent's world model continues (`world_model_from = "a"` or `"b"`); the merge API accepts the field and answers `409` without it. The dashboard's merge form sends only the two snapshot ids and a label, so a merge of two parents with world models cannot be done from the dashboard at all. When the API refuses, the form shows only the status code ("failed: 409"), not the reason the server gave, so the operator cannot tell what to change.

Research impact: none. Studies do not merge forks, and the running MoC7 study uses a pinned image.

## What changes
- The merge form gets a labelled "world model from" select with three options: none (the field is left out), A, or B. The submitted body carries `world_model_from` only when A or B is chosen.
- When the merge API answers with an error, the form shows the status and the server's `detail` text.
- `allow_unmerged_adapters` stays API-only: it keeps unmerged adapter weights in the merged snapshot, which the operator should choose deliberately rather than with a checkbox.
