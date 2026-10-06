## Why

The real adapter merger (`TiesDareAdapterMerger`, `kaine/lifecycle/adapter_merge.py`) loads the base model inside the process that asks for the merge. It uses `from_pretrained(..., torch_dtype="auto")` to keep the checkpoint's bf16 and halve the memory each check needs.

In transformers 5.x, any `from_pretrained` whose dtype is not float32 sets the process-wide default dtype to that dtype for the length of model construction. Merges run inside long-lived processes:
- Nexus runs `ForkManager.merge` in a worker thread (`kaine/nexus/diagnostics.py`);
- the fork-merge gate (`kaine/lifecycle/fork_merge_gate.py`) calls it in its caller's process.

Any other thread that builds torch layers during that window gets bf16 layers. That is the same race the perception loaders closed by building in float32 (`fix-cpu-perception-paths`).

Building the merge in float32 would double the memory of a 9B load, so the dtype cannot simply be pinned. The load has to leave the shared process.

## What Changes

- **The merge runs in a child process.** `TiesDareAdapterMerger.merge` starts `python -m kaine.lifecycle.adapter_merge_worker` with the merge inputs:
  - adapter paths;
  - weights;
  - combination type and density;
  - output dir;
  - base model path;
  - the capability and abliteration check settings.
  
  The inputs go in a private job file (0600, in a 0700 directory), and the parent reads back a result file. The base model, the adapters and the checks load only in the child, so the parent's default dtype is never touched.
- **The result keeps today's contract.** The merged adapter path and its check outcome are unchanged, and the merge-veto rule still fails closed. A child that crashes, times out, or writes an unreadable or partial result counts as a failed merge, never as an unchecked success. The child's environment is an allowlist, with Hugging Face offline, the same as the voice trainer's.
- **Tests:**
  - the parent never imports `transformers` or `peft` during a merge;
  - `torch.get_default_dtype()` stays float32 around a merge;
  - a crashed, timed-out or garbage-result child is a refused merge;
  - one real merge of two tiny LoRA adapters runs end to end in the child, and skips where peft is absent.

## Impact

- Code: `kaine/lifecycle/adapter_merge.py`, a new `kaine/lifecycle/adapter_merge_worker.py`, and tests.
- No change to merge results, the merge veto, or the stored adapters. A merge costs one process start.
- Research impact: none. Merge results and the veto are unchanged; only the process that does the loading moves.
