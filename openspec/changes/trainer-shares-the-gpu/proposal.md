# Proposal

## Why

The first real GPU runs of the voice trainer (the 4B organ base on a 12 GB card that also drives the desktop) showed two faults.

- Loading the bf16 base failed with `CUDA out of memory` while 9.7 GiB of the card was free. During loading, transformers reserves the model's whole footprint (7.8 GiB) in one allocation, and other processes' scattered allocations left no single block that large. The identical load succeeded minutes earlier and succeeded again with PyTorch's expandable-segments allocator, which maps memory in pieces. The trainer always shares its GPU with something (a desktop, a sleeping organ), so the default allocator makes training depend on what else happens to be on the card.
- When that happened, the result said only "does not fit … peak 0.00 GiB allocated", and nothing was printed. The real error (the allocation size, the free memory, where it failed) was swallowed, and finding it took a wrapper script.

## What Changes

- The trainer sets `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before torch touches CUDA, unless the environment already sets `PYTORCH_CUDA_ALLOC_CONF` (an operator's own setting wins).
- An out-of-memory result keeps its "does not fit … no fallback was attempted" reason and appends the original error's type and message (truncated). The traceback is printed to stderr.

## Capabilities

### New Capabilities

### Modified Capabilities
- `voice-alignment-training`: the trainer uses the expandable-segments allocator by default and reports the real error when training does not fit.

## Impact

- `scripts/sleep_external_train.py` (`main` and the out-of-memory result), `tests/test_external_trainer_hygiene.py`, `tests/test_training_core.py`.
- No configuration key, no dependency, no change to the result schema's fields.
