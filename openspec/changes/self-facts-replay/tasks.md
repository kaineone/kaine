## 1. Pre-registration

- [x] 1.1 Write and commit the arms, case sets, metrics and decision rule before any run

## 2. Harness

- [x] 2.1 Add the `N0` to `N4` arms, the user turn, and the `provoke` subcommand to `organ_replay.py`
- [x] 2.2 Add the identity metrics and `score --rule self-facts`
- [x] 2.3 Tests for the arms, the provocation set, the metrics and the rule

## 3. Replay

- [x] 3.1 Run both case sets on the pinned organ under the GPU lock and stop the organ afterwards
- [x] 3.2 Score with the committed rule, read about 50 texts by hand, and write `results.md`
