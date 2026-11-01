## 1. The merge (PR 1)

- [x] 1.1 Inventory: read every stock module's `serialize` and `deserialize` and confirm or extend the weight groups of design decision 1, recording for each key why it is in the group
- [x] 1.2 `kaine/lifecycle/strategies.py`: `MODULE_WEIGHT_GROUPS`
- [x] 1.3 `kaine/lifecycle/manager.py` `ForkManager.merge`: `module_weights_from` (`"a"`, `"b"` or a per-module mapping); remove each group before the module strategy and set the chosen group after; equal or one-sided groups need no choice; `ModuleWeightsChoiceRequiredError` naming the modules; the choice recorded in the merged snapshot's metadata
- [x] 1.4 `ForkManager.merge`: a failing strategy for a module with a weight group raises, naming the module
- [x] 1.5 `matches_state_shape` in `kaine/modules/vision/forward.py` and `kaine/modules/audition/forward.py` checks the layer count; interoception and sequence `deserialize` catch a weight-group load failure, warn, and keep the rest of the restored state
- [x] 1.6 Tests in `tests/test_fork_merge_module_weights.py`: `test_merge_refuses_differing_weights_without_choice`, `test_merge_takes_vision_weights_exactly_from_b`, `test_merge_takes_interoception_weights_and_seed_together`, `test_merge_per_module_mapping`, `test_mapping_missing_a_module_refused`, `test_equal_groups_need_no_choice`, `test_one_sided_group_needs_no_choice`, `test_union_never_sees_a_weight_key`, `test_choice_recorded_in_metadata`, `test_failing_strategy_for_weight_module_refuses`, `test_concatenated_vision_layers_refused_on_restore`, `test_interoception_bad_weights_keep_rest_of_state`, `test_every_weight_like_list_is_declared_or_reviewed`; the existing `test_union_concatenates_lists_dedup_preserving_order` stays

## 2. Interfaces and the check (PR 2)

- [x] 2.1 `kaine/dashboard/diagnostics.py` merge request: `module_weights_from`; the merge form offers none, A or B and shows a refusal's status and detail; tests
- [x] 2.2 `tools/maintainer/check_merged_weights.py`: read-only listing of snapshots with concatenated weight groups; a test that it opens snapshot files read-only and writes nothing under the fork root
- [x] 2.3 Preservation chapter of the docs: merge and module weights, the choice, the check tool

## 3. Review

- [ ] 3.1 Worker first-pass review of each PR
- [ ] 3.2 Lead developer's adversarial review of each PR
- [ ] 3.3 Independent second review of each PR (persistence and identity)
