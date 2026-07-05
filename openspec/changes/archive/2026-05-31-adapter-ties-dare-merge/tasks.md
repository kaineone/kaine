## 0. Operator decision

- [x] 0.1 AskUserQuestion: default `combination_type` —
      `"dare_ties"` (recommended; DARE drop+rescale then TIES
      trim/elect/merge) vs `"ties"` (pure TIES) vs `"dare_linear"`
      (DARE then linear average)
- [x] 0.2 AskUserQuestion: default `density` —
      `0.5` (recommended per DARE paper) vs operator's choice

## 1. Adapter merger implementation

- [x] 1.1 `kaine/lifecycle/adapter_merge.py` — `TiesDareAdapterMerger`
      class with lazy imports
- [x] 1.2 Combination-mode dispatcher (ties / dare_ties / dare_linear)
- [x] 1.3 Density + per-adapter weights plumbing
- [x] 1.4 Output layout: `<output_dir>/<merge_snapshot_id>/<timestamp>/`
- [x] 1.5 Fallback to FakeAdapterMerger when peft missing

## 2. Capability-loss veto

- [x] 2.1 Reuse `CapabilityEval` Protocol from voice-alignment-training
- [x] 2.2 Run eval on each parent adapter + merged adapter
- [x] 2.3 Reject + cleanup when (parent_mean - merged) > threshold

## 3. Config wiring

- [x] 3.1 `[lifecycle].adapter_merger = "ties_dare"` (operator opt-in)
- [x] 3.2 `[lifecycle.adapter_merge]` nested table:
      combination_type, density, weights, output_dir,
      capability_loss_threshold
- [x] 3.3 Update `kaine/lifecycle/manager.py::merger_from_name` to
      return TiesDareAdapterMerger when name == "ties_dare"
- [x] 3.4 ForkManager constructor reads the config block and passes
      the merger through

## 4. Tests

- [x] 4.1 `tests/test_adapter_ties_dare_unit.py` — FakePeftBackend
- [x] 4.2 `tests/test_adapter_ties_dare_capability_veto.py`
- [x] 4.3 `tests/test_lifecycle_adapter_merger_selection.py` —
      merger_from_name resolves "ties_dare"
- [x] 4.4 `tests/test_adapter_ties_dare_real_peft.py` —
      KAINE_HAS_PEFT=1 gated; rank-2 LoRA on a 3-layer linear stub

## 5. Docs

- [x] 5.1 `kaine/lifecycle/ADAPTER_MERGING.md`
- [x] 5.2 `DEPENDENCIES.md` — note peft enables both training and
      merging
- [x] 5.3 `ARCHITECTURE.md` — Layer 3 fork/merge update

## 6. Verification

- [x] 6.1 Full suite passes (no regression)
- [x] 6.2 `openspec validate adapter-ties-dare-merge --strict`
- [x] 6.3 Without opt-in, `FakeAdapterMerger` still default;
      existing fork/merge tests unchanged
- [x] 6.4 With opt-in + KAINE_HAS_PEFT=1, two rank-2 LoRA adapters
      merge end-to-end and load back via peft
- [x] 6.5 Commit, merge, archive, tag `v1.5-adapter-merge`

## Depends on

- `voice-alignment-training` must land first. Until the voice
  alignment trainer writes real LoRA adapters, there's nothing to
  merge.
