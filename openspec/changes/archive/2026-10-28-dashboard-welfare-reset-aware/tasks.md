## 1. Implementation

- [x] 1.1 Check history for prior work: the reset-aware reader came with #475 and the cycle-published pattern with #584; the dashboard registry has no earlier fix
- [x] 1.2 Route welfare_counts_from_jsonl through the latest restart reset
- [x] 1.3 Remove the never-started SidecarRegistry and the registry parameters from the evaluation tab
- [x] 1.4 Add tests for the reset case and for the absence of the registry, and mutation-check them
- [x] 1.5 Update the evaluation template source lines and docs/05-dashboard.md
