## Why

Phase 7.2 shipped fork/merge with `FakeAdapterMerger` as the default
`AdapterMerger` implementation. The fake concatenates parent adapter
paths and annotates `metadata.adapter_merge_skipped = "no merger
configured"`. That means an operator who forks two KAINE instances,
lets each train its own voice-alignment LoRA, then merges them, gets
the union of memories and beliefs correctly — but the LoRA adapters
are handed back as a list and the operator has to pick one manually.

The build prompt §7.2 explicitly called this out: "merge LoRA
adapters (research TIES/DARE merging)." This change ships the
research result.

**TIES** (TrIm, Elect, Sign — Yadav et al. 2024) and **DARE** (Drop
And REscale — Yu et al. 2024) are weight-merging techniques for
combining multiple fine-tuned model deltas into a single coherent
adapter. PEFT (already an optional dep via `[training]`) has these
built-in via `model.add_weighted_adapter(..., combination_type="ties"
| "dare_ties" | "dare_linear")`. The work here is the integration:
load multiple LoRA adapters with peft, call its merge utilities,
write a merged adapter, satisfy the `AdapterMerger` protocol.

**Depends on:** `voice-alignment-training` lands first. Until the
voice-alignment trainer actually writes LoRA adapters, there's
nothing to merge.

## What Changes

### 1. New `TiesDareAdapterMerger`

- `kaine/lifecycle/adapter_merge.py` (new) — `TiesDareAdapterMerger`
  class implementing the `AdapterMerger` protocol. Lazy-imports
  `peft`, `torch`, `safetensors`. When extras missing, falls through
  to `FakeAdapterMerger` with a logged warning so existing fork/merge
  behavior is preserved.
- Three combination modes via constructor:
  - `"ties"` — pure TIES (trim + elect + merge)
  - `"dare_ties"` — DARE drop+rescale, then TIES (recommended default)
  - `"dare_linear"` — DARE drop+rescale, then linear average
- Configurable `density` (DARE survival fraction, default 0.5) and
  `weights` (per-adapter scalar, default uniform).

### 2. Operator opt-in via config

- `[lifecycle].adapter_merger = "fake"` (current default — kept)
- `[lifecycle].adapter_merger = "ties_dare"` (new, opt-in) routes
  `ForkManager`'s adapter-merge calls to `TiesDareAdapterMerger`.
- `[lifecycle.adapter_merge]` nested table:
  - `combination_type = "dare_ties"` — one of the three above
  - `density = 0.5` — DARE survival fraction
  - `weights = []` — per-adapter scalars; empty = uniform
  - `output_dir = "state/forks/merged_adapters"` — where merged
    adapters get written
- `merger_from_name("ties_dare")` in `kaine/lifecycle/manager.py`
  returns the new merger when called; today it raises ValueError.

### 3. Merge contract

`AdapterMerger.merge(adapters_a, adapters_b) -> (list[str], dict)`
already defined. `TiesDareAdapterMerger` returns:
- `list[str]` — single-element list with the path of the freshly
  written merged adapter (or the input concatenation if all adapters
  in one parent's list are missing on disk)
- `dict` — metadata: `{"adapter_merge": "ties_dare", "combination_
  type": "...", "density": ..., "input_adapters": [...], "weights":
  [...], "merge_timestamp": ...}`

The merged adapter goes to
`<output_dir>/<merge_snapshot_id>/<timestamp>/` so two merges of
the same parents at different times don't collide.

### 4. Capability-loss veto (mirror voice-alignment-training)

After merging, run a CapabilityEval pass (reuse the harness from
voice-alignment-training) on the merged adapter loaded onto the
base model. If the merged adapter's capability score is more than
`[lifecycle.adapter_merge].capability_loss_threshold` (default 0.05)
below the average of the parent scores, reject the merge — return
the input adapter list unchanged with `metadata.adapter_merge_rejected
= "capability_loss=<value>"`.

This guarantees merges don't silently degrade the model.

### 5. Tests

- `tests/test_adapter_ties_dare_unit.py` — unit tests against a
  `FakePeftBackend` that records merge calls. Verifies: combination
  type plumbing, density/weights forwarding, output path layout,
  metadata shape.
- `tests/test_adapter_ties_dare_capability_veto.py` — fake
  CapabilityEval returning controlled scores; verifies reject path
  cleans up and preserves input list.
- `tests/test_adapter_ties_dare_real_peft.py` — env-var-gated
  (`KAINE_HAS_PEFT=1`) test that creates two tiny LoRA adapters
  (rank 2, attaches to a 3-layer linear stub), runs a real
  `add_weighted_adapter` call, verifies the output adapter loads
  back via `peft.PeftModel.from_pretrained`.
- `tests/test_lifecycle_adapter_merger_selection.py` — verifies
  `merger_from_name("ties_dare")` returns the new merger and
  `"fake"` still returns FakeAdapterMerger.

### 6. Docs

- `kaine/lifecycle/ADAPTER_MERGING.md` (new) — operator-facing doc
  explaining the three modes, when each is appropriate, the
  capability-loss veto, and the rollback procedure (delete the
  merged-adapter directory, the fork sources remain untouched).
- `DEPENDENCIES.md` — note that `[training]` extras now also enable
  TIES/DARE merging (peft is the shared dep).
- `ARCHITECTURE.md` — Layer 3 (Emergent Capabilities) update on
  fork/merge: adapter merge is real, not stub.

## Capabilities

### Modified Capabilities

- `fork-merge` (existing) — `merger_from_name` gains a `"ties_dare"`
  resolver; default `[lifecycle].adapter_merger` stays `"fake"` but
  the operator can opt up.

### New Capabilities

- `adapter-ties-dare-merge` — owns the PEFT-backed TIES/DARE merge
  body, the capability-loss veto for merges, and the per-mode
  config.

## Impact

- **No new external deps.** Reuses `peft` from the `[training]`
  extras introduced in `voice-alignment-training`.
- **Default behavior unchanged.** Without
  `[lifecycle].adapter_merger = "ties_dare"`, FakeAdapterMerger is
  still the merger. Existing tests don't move.
- **Tag** after merge: `v1.5-adapter-merge`.

## Depends on

- `voice-alignment-training` must land first so there are real LoRA
  adapters in `state/hypnos/adapters/` to merge.
