# Lifecycle — TIES/DARE adapter merging (real by default when installed)

When two KAINE forks each train their own voice-alignment LoRA
adapter (see [VOICE_ALIGNMENT.md](
../modules/hypnos/VOICE_ALIGNMENT.md)), merging the forks back
together produces two parents' worth of adapters. When the PEFT
extra (`kaine[training]`) is installed, `adapter_merger = "auto"`
(the default) combines them for real; without the extra — or with
`adapter_merger = "fake"` forced explicitly — the no-op
`FakeAdapterMerger` just concatenates the path lists and leaves
the operator to pick one manually.

`TiesDareAdapterMerger` combines them into a single coherent
adapter via PEFT's `add_weighted_adapter` API, using one of three
weight-merging recipes from the literature:

- **`ties`** — TIES (TrIm, Elect, Sign — Yadav et al. 2024).
  Trims small parameter changes, elects the sign per-parameter
  from the larger-magnitude contributor, then merges the survivors.
- **`dare_ties`** (default, recommended). DARE (Drop And REscale —
  Yu et al. 2024) drops a fraction of parameter changes and
  rescales the survivors, then runs TIES. The drop+rescale
  reduces parameter interference; TIES handles sign conflicts.
- **`dare_linear`**. DARE drop+rescale followed by linear
  averaging. Cheaper than `dare_ties` but more interference-prone.

## Configuration

Default `[lifecycle].adapter_merger = "auto"` — detects the PEFT
extra at merger-resolution time (`merger_from_name`, reusing
`adapter_merge.check_peft_available`) and picks `TiesDareAdapterMerger`
when it's importable, `FakeAdapterMerger` otherwise. Set the value
explicitly to force one or the other regardless of what's installed:
`"ties_dare"` always resolves to the real merger class (its own
per-merge fallback still applies if PEFT turns out missing at merge
time); `"fake"` is the explicit dev/no-extra selection.

```toml
[lifecycle]
adapter_merger = "auto"   # or "fake" / "ties_dare" to force one explicitly

[lifecycle.adapter_merge]
combination_type = "dare_ties"
density = 0.5
weights = []                  # empty = uniform
output_dir = "state/forks/merged_adapters"
capability_loss_threshold = 0.05
base_model_path = "/abs/path/to/hf-format/base-model"
```

The real merger also requires the `[training]` extras
(`pip install -e .[training]`) — same dependency stack as
voice-alignment training. Without the extras, `"auto"` resolves
straight to `FakeAdapterMerger`; without `base_model_path` configured,
`TiesDareAdapterMerger` logs a warning and falls back to
`FakeAdapterMerger` per merge so fork/merge keeps working either way.

When both parents carry trained adapters and no real merge is
possible, `ForkManager.merge()` fails loud
(`UnmergedAdaptersError`) rather than silently producing an
unmerged "merged" snapshot — see the "Fail-loud guard" section
below.

## Fallback paths

The merger transparently falls back to `FakeAdapterMerger` (with
metadata explaining why) in any of these cases:

- Fewer than 2 distinct adapter paths across the two parents.
- Fewer than 2 of those paths exist on disk.
- The `[training]` extras (`peft`, `torch`) are not installed.
- `base_model_path` is unset.
- PEFT's `add_weighted_adapter` raises during the merge.

In every fallback case, the merged-snapshot metadata carries an
`adapter_merge_skipped` or `adapter_merge_failed` field explaining
the reason. The original adapter paths from the two parents are
returned via the standard `FakeAdapterMerger` concatenation.

## Fail-loud guard

`ForkManager.merge()` refuses to produce a "merged" snapshot whose
adapters were never actually weight-combined: if both parents carry
trained adapters and the resolved merger falls back to the
`FakeAdapterMerger` path (extras missing, `base_model_path` unset,
etc.), it raises `UnmergedAdaptersError` instead of silently
unioning the two adapter path lists. The error names the extra to
install (`pip install -e .[training]`) and the config keys to set.
Operators who deliberately want the union behavior (e.g. picking the
better adapter by hand afterward) pass `allow_unmerged_adapters=True`
to `merge()`.

## Capability-loss veto

When a `CapabilityEval` collaborator is configured (alongside a
`model_loader` callable), the merger scores each parent adapter
and the freshly-merged adapter, then rejects the merge if the
merged score is more than `capability_loss_threshold` below the
mean of the parent scores. Rejection cleans up the merged
adapter directory and returns the `FakeAdapterMerger` result with
`adapter_merge_rejected` and capability-score fields populated.

This guarantees that an interference-induced regression doesn't
silently get promoted. The default threshold is `0.05` (same as
voice-alignment training).

## Output layout

```
<output_dir>/
  <merge_timestamp>/        ← single merge output
    adapter_config.json
    adapter_model.safetensors
    ...
```

Two merges at different times don't collide. The operator can
inspect, delete, or compare merges by timestamp.

## Rollback

If a merged adapter misbehaves once loaded into Lingua:

1. Stop KAINE.
2. `rm -rf <output_dir>/<bad-timestamp>/`.
3. Re-point Lingua at one of the parent adapters (or the previous
   `current` adapter from voice-alignment training).
4. Restart KAINE.

The two parent adapter directories are never modified by this
merger — the source-of-truth weights stay where Hypnos / your
training pipeline put them.

## What this is NOT

- **Not a model merger.** It only merges LoRA *adapters*, not full
  base-model weights. The base model is loaded read-only via
  `transformers.AutoModelForCausalLM.from_pretrained`.
- **Not automatic across all forks.** Operator-initiated only; the
  ForkManager calls into the merger when the operator triggers a
  merge between two snapshots.
- **Not a sleep-cycle phase.** Unlike voice-alignment training,
  there's no scheduler firing this. It runs when (and only when)
  the operator triggers `ForkManager.merge`.
