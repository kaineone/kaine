## Why

The dashboard's welfare_counts_from_jsonl takes the maximum over the last 500 lines and ignores the restart reset, so lines counting 5, then a reset, then 0 give 5. The reset-aware reader in the same file (#475) gives 0. The dashboard also builds a SidecarRegistry (kaine/dashboard/__main__.py:331) that it never starts, so the evaluation tab's live branch never runs.

## What Changes

- welfare_counts_from_jsonl goes through the reset-aware reader.\n- The evaluation tab reads what the cycle publishes, as #584 did for backend failures, or the dead live branch and its unused registry are removed and the tab says where its numbers come from.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: the dashboard's welfare counts honour restart resets, and the dead live evaluation branch is fixed

## Impact

- dashboard-welfare-reset-aware0
- Behaviour: dashboard-welfare-reset-aware1
