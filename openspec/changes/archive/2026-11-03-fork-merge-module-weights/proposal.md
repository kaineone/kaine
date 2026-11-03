## Why

The identity rules for learned weights (archived change `2026-10-01-world-model-identity`, and decision 4 of the operator's outcome of 2026-10-31) say that learned weights are never merged without an operator choice. The world model obeys that: `ForkManager.merge` refuses unless the caller passes `world_model_from`. The processors' learned weights do not. Vision, audition, interoception and sequence have no merge strategy (`kaine/lifecycle/strategies.py:429-437`), so `ForkManager.merge` falls back to `UnionMergeStrategy` (`:71-105`), which takes b's value for scalar keys, merges dicts recursively and **concatenates lists**, deduplicated by `repr`. Forward-model weights are serialized as nested lists, so a merge today does one of two wrong things, depending on the module. Both were shown with a read-only probe on 2026-10-31 (no entity, no services), using the real classes:

- **Vision** (`LatentForwardModel`, layers as a list of `{weight, bias}`): the two parents' layer lists are concatenated (2 + 2 = 4 layers). The shape guard `matches_state_shape` reads only the first and last layer, so it accepts the merged state, and `load_state_dict` reads the first two layers. The merged entity silently gets parent a's whole forward model, contrary to the strategy's documented "b's value wins", with no choice made, and its snapshot carries b's weights as dead state that every later merge lengthens. Audition's forward models are built the same way.
- **Interoception** (`SubstrateForwardModel`, readout `weight` as a list of rows): the rows are concatenated (8 + 8 = 16), and `load_state_dict` raises `ValueError: expected weight shape (8, 4), got (16, 4)`. `ForkManager.restore` catches a failing `deserialize` and only logs it (`kaine/lifecycle/manager.py:252-266`), so the merged entity's interoception module keeps none of its restored state. Its expected-error statistics are garbled the same way (two 8-number lists merge into 9 numbers).

The same union merge also mixes keys that must travel with the weights they were trained against: interoception's and sequence's `reservoir_seed` (the readout is trained on the reservoir that seed generates) and the layout and encoder-id keys. And when any strategy raises, merge silently takes parent a's module state (`manager.py:402-404`). This is persistence and identity code, so the fix is specified before it is built.

## What Changes

- **Each weight-bearing module declares a weight group:** the keys of its serialized state that hold learned parameters, together with the seeds, layouts and encoder ids those parameters were trained against. The declarations live in `kaine/lifecycle/strategies.py` (`MODULE_WEIGHT_GROUPS`), importable without module instances, so a merge from the dashboard process works the same.
- **Merge takes a weight group whole from one parent, by an explicit choice.** When both parents carry a module's weight group and the two differ, merge refuses unless the caller passes `module_weights_from` (`"a"`, `"b"`, or a mapping naming a parent for each such module). The group is then copied whole from the chosen parent; the module's other keys merge by its strategy as before. A group present in one parent only, or equal in both, needs no choice. The choice is recorded in the merged snapshot's metadata.
- **A failing strategy for a weight-bearing module refuses the merge** instead of silently taking parent a.
- **Restore refuses a weight state whose structure differs from the running model,** with a warning naming the module, instead of loading part of it (the vision and audition guards check the layer count, not only the first and last layer).
- **A static guard test** fails when a stock module's serialized state holds a numeric weight-like list under a key that is neither in its weight group nor reviewed as non-weight, so a new module cannot slip into the union merge.
- **A read-only check** lists existing snapshots whose module states hold a concatenated weight group, so the operator can decide what to do with any entity merged before the fix. It never modifies a snapshot.
- **The dashboard merge form and the diagnostics merge request** offer the choice, as they do for the world model.

## Capabilities

### Modified Capabilities

- `entity-preservation`: weight-bearing module state merges only by an explicit choice; a failing strategy for such a module refuses the merge; restore refuses a structurally different weight state.
- `dashboard-dashboard`: the merge form and request carry `module_weights_from`.

## Impact

- **Code:** `kaine/lifecycle/strategies.py` (`MODULE_WEIGHT_GROUPS`, the group split around the module strategy), `kaine/lifecycle/manager.py` (`ForkManager.merge`: the choice, the refusal, the metadata, no fallback to parent a for weight-bearing modules), `kaine/modules/vision/forward.py` and `kaine/modules/audition/forward.py` (`matches_state_shape` checks the layer count), `kaine/dashboard/diagnostics.py` (the merge request field) and the merge form, a new read-only check script under `tools/`.
- **Tests:** `tests/test_fork_merge_strategies.py` (the existing `test_union_concatenates_lists_dedup_preserving_order` stays: it pins the union strategy for non-weight lists), new `tests/test_fork_merge_module_weights.py`, the dashboard merge-form tests.
- **Behaviour with the shipped configuration:** none until a merge is requested. A merge of two parents with differing processor weights that succeeded before now refuses until the caller chooses.
- **Depended on by:** `workspace-content-code` (its `content_code_from` overrides this choice for the processors' head weights).
- **Welfare and risk class:** persistence and identity. Every PR gets the independent second review.
