## Why

The dashboard's welfare_counts_from_jsonl took the maximum over the newest 500 lines and ignored the restart reset, so lines counting 5, then a reset, then 0 gave 5. The reset-aware reader in the same file (#475) gives 0.

The dashboard also built a SidecarRegistry in kaine/dashboard/__main__.py and never started it. The evaluation tab preferred that registry's counters, so a branch labelled live would have shown zeros or nothing, and the dashboard process cannot see the cycle's observers anyway.

## What Changes

- welfare_counts_from_jsonl counts from the latest restart reset onward.
- The dashboard no longer builds a SidecarRegistry. The evaluation tab reads only the rollups the cycle's observers write under data/evaluation/, and the welfare and prediction-error panels say which rollup they read.
- The registry parameter is removed from the evaluation router and aggregate functions, with the tests that fed them a stub registry.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: welfare counts honour restart resets, and the evaluation tab shows only data a running component produces

## Impact

- kaine/experiment/welfare_counts.py, kaine/evaluation/dashboard_tab.py, kaine/dashboard/__main__.py, the evaluation template, docs/05-dashboard.md, tests/test_dashboard_observability.py.
- The welfare and prediction-error panels show values from the rollups only, with the source line naming the rollup directory.
