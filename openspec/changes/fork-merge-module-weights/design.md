# Design: weight-bearing module state merges by an explicit choice

Code facts are cited at `origin/main` cb41895b, read on 2026-10-31.

## Context

### The bug

`ForkManager.merge` (`kaine/lifecycle/manager.py`) merges each module's state with that module's strategy, or with `UnionMergeStrategy` when it has none (`strategies.py:429-437` lists strategies for episodic memory, planning, self-model, affect and social cognition only). The union strategy's documented semantics are: keys in both take b's value, nested dicts merge recursively, lists are concatenated and deduplicated by `repr` (`strategies.py:71-105`; pinned by `tests/test_fork_merge_strategies.py::test_union_concatenates_lists_dedup_preserving_order`). That is right for lists of records and wrong for weights.

A read-only probe on 2026-10-31 (no entity, no services; scripts kept outside the repo) ran the real classes through `UnionMergeStrategy().merge`:

| Module state | Parents | Merged | Restore |
|---|---|---|---|
| Vision `forward_model.layers` (`LatentForwardModel`, `vision/forward.py:420-502`) | 2 layers each | 4 layers, equal to a's layers followed by b's | `matches_state_shape` (`:435`) reads only `layers[0]` and `layers[-1]` and accepts; `load_state_dict` (`:467`) reads the first two: the result equals parent a, not b |
| Interoception `forward_model.weight` (`SubstrateForwardModel`, `interoception/forward.py:699-740`) | 8 rows each | 16 rows | `load_state_dict` raises `ValueError: expected weight shape (8, 4), got (16, 4)`; `ForkManager.restore` logs the failed `deserialize` and the module keeps none of its restored state |
| Interoception `expected_error.expected`, `.spread` | 8 numbers each | 9 numbers each (dedup by `repr`) | garbled statistics |

Audition's utterance and acoustic forward models (`audition/forward.py:460-509`) serialize like vision's. Sequence's prediction head (`sequence/network.py:180`) serializes like interoception's readout.

Related keys travel separately today. Interoception's readout is trained on the reservoir that `reservoir_seed` generates (`interoception/module.py:1098-1100`), and so is sequence's head (`sequence/module.py:377-378`). The union merge takes b's seed (a scalar) and a mix of both parents' weight lists, so even a correct-shaped result would pair one parent's readout with the other's reservoir. The layout keys (`feature_layout`, `featurizer_layout`) and the encoder binding (`encoder_model_id` in vision's state, `forward_model_features` in audition's) belong with the weights for the same reason.

When a strategy raises, merge logs it and takes parent a's state (`manager.py:402-404`): a second silent choice.

### The rule this breaks

`2026-10-01-world-model-identity` set the identity rules for learned weights: persist, encrypt, copy into forks, refuse a merge without an operator choice, covered by decommission. The operator's outcome of 2026-10-31 restates them for every learned component (decision 4). The world model follows them through `world_model_from` (`manager.py:361-388`; spec `entity-preservation`, "Fork and merge snapshots carry module artifacts"). The processors' forward models are learned weights too, and they are the entity's individual way of predicting its senses.

## Decisions

### 1. A declared weight group per module

`kaine/lifecycle/strategies.py` gains `MODULE_WEIGHT_GROUPS: dict[str, tuple[str, ...]]`, keyed by module name, listing the top-level keys of the module's serialized state that hold learned parameters and the keys they were trained against. The starting inventory, from the code:

| Module | Weight group |
|---|---|
| `vision` | `forward_model`, `encoder_model_id` |
| `audition` | `forward_model`, `forward_model_features`, `acoustic_forward_models` |
| `interoception` | `forward_model`, `reservoir_seed`, `feature_layout`, `expected_error`, `self_rhythm` |
| `sequence` | `pred_head`, `reservoir_seed`, `featurizer_layout` |
| `planning` | `learned` |

Task 1.1 extended the starting inventory by two keys. Interoception's `self_rhythm` holds the self-rhythm oscillator's plastic time constant (`ln_tau`) with the per-unit arrays (`mem`, `weights`) and RNG state it evolved with; the union merge concatenated those arrays to twice the population. Planning's `learned` holds the learned transition prior (`pB`) and the belief carried with it; its specialised strategy picked a parent by posterior certainty, an automatic choice of learned parameters, which the identity rule does not allow. The remaining specialised strategies (episodic memory, self-model, affect, social cognition) merge records, counts and statistics, not learned parameters.

Task 1.1 confirms it by reading every stock module's `serialize` and `deserialize`, including modules with a specialised strategy (affect, planning, self-model, social cognition, episodic memory), and the content code's head blocks when `workspace-content-code` lands. `buffer_summary` is not in a group: it is content-free (change `latent-content-privacy`) and nothing reads it.

The declarations are data, not methods on the module class, because a merge can run in a process with no live modules (the dashboard builds its own `ForkManager`, `kaine/dashboard/__main__.py:182`).

Alternatives considered:

- *A specialised strategy per module.* Rejected as the main mechanism: four near-identical strategies, each a place to forget the seed. The group split keeps the existing strategies for the non-weight keys.
- *Change the union strategy to take b's list instead of concatenating.* Rejected: it would silently pick parent b, which is the same rule broken the other way, and it would change the merge of lists of records that union is right for.

### 2. Merge takes a weight group whole from a chosen parent

For each module present in both parents with a declared group:

1. If the group's values are deeply equal in both parents (for example, both forked from one snapshot and not trained since), the group is copied from either.
2. If only one parent's state holds the group, it is copied from that parent.
3. Otherwise merge needs a choice. `ForkManager.merge` gains `module_weights_from`: `"a"`, `"b"`, or a mapping from module name to `"a"` or `"b"`. A string applies to every module that needs a choice; a mapping must name each such module. Without a sufficient choice, merge raises `ModuleWeightsChoiceRequiredError` naming the modules, and writes no merged snapshot.

The group's keys are removed from both parents' states before the module's strategy runs on the rest, and the chosen group is set on the result afterwards, deep-copied. So the union strategy never sees a weight key. The merged snapshot's metadata records `module_weights_from` per module, and which modules needed no choice and why.

A module present in only one parent is still taken whole from that parent, as now.

### 3. A failing strategy for a weight-bearing module refuses the merge

For a module with a declared group, a strategy that raises makes the merge raise, naming the module, instead of taking parent a. Modules without a group keep today's behaviour, which this change does not revisit.

### 4. Restore refuses a structurally different weight state

`LatentForwardModel.matches_state_shape` and `AuditoryForwardModel.matches_state_shape` check that the number of layers equals the network's number of linear layers, besides the first and last shapes. A state that fails is discarded with a warning naming the module and the mismatch, and the model re-learns from scratch, as for an encoder-dimension mismatch today. This stops a concatenated state, from before this fix, from loading half of itself silently. Interoception and sequence already raise on a shape mismatch; their `deserialize` paths catch that for the weight group only, warn, and keep the rest of the module's restored state, so one bad group does not cost the module everything.

### 5. A guard against new modules slipping through

`tests/test_fork_merge_module_weights.py` builds every stock module entity-free, serializes it, and walks its state. For a module without a specialised strategy, a nested numeric list (a list of lists of numbers, or a list of 16 or more numbers) under a top-level key that is neither in the module's weight group nor in a reviewed `NON_WEIGHT_LIST_KEYS` set fails the test, naming the module and the key.

### 6. Snapshots merged before the fix

Merges are rare and operator-driven, but any already made may hold concatenated groups. A read-only tool, `tools/maintainer/check_merged_weights.py`, lists snapshots under the fork root whose module states hold a weight group longer than one parent's would be (more layers than the network, more rows than the feature dimension), decrypting with the configured key. It never writes, moves or deletes a snapshot (fork snapshots hold preserved entities and are never touched by infrastructure, spec `entity-preservation`, "Infrastructure never deletes fork snapshots"). What to do with a listed snapshot is the operator's choice.

### 7. The interfaces

The diagnostics merge request (`kaine/dashboard/diagnostics.py:77`, beside `world_model_from`) gains `module_weights_from`, and the merge form offers the choice, none, A or B, as it does for the world model. A refusal shows the status code and the server's detail, which names the modules.

### 8. The content code

`workspace-content-code` adds each processor head's base block to that processor's weight group, and its `content_code_from` overrides `module_weights_from` for those keys, because a head's base block and code block were trained together and the code block travels with the encoders.

## Risks

- **A merge that worked before now refuses.** That is the point: it never worked as documented. The refusal names the modules and the choice.
- **An incomplete inventory.** A module whose weights are not declared still falls to the union merge. The guard test of decision 5 is the check, and task 1.1 reads every module.
- **Choosing per module mixes parents.** A caller can take vision from a and interoception from b. Each group is internally consistent, and the modules' weights do not read each other's, so this is allowed; the content code's heads are the exception and are overridden together (decision 8).

## Migration and ordering

1. PR 1: `MODULE_WEIGHT_GROUPS`, the group split in `ForkManager.merge`, the choice and its refusal, the metadata, the strategy-failure refusal, the layer-count guards, the group-only catch in interoception and sequence, the tests.
2. PR 2: the diagnostics request field and the merge form; the read-only check tool.
3. Before `workspace-content-code` PR 3.

## Welfare and admissibility

- Persistence and identity code: every PR gets the independent second review.
- Nothing changes for a running entity; only a merge, which an operator requests, behaves differently.
- No snapshot is modified, moved or deleted by the change or by its tool.

## Implementation estimate

Two worker PRs of about 200 to 400 changed lines each, tests included. About one day elapsed with the second review.
