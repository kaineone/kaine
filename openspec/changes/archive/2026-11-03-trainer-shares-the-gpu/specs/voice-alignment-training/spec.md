# Spec Delta

## ADDED Requirements

### Requirement: The trainer tolerates a shared GPU
The voice-alignment trainer SHALL set `PYTORCH_CUDA_ALLOC_CONF` to `expandable_segments:True` before any CUDA allocation, unless `PYTORCH_CUDA_ALLOC_CONF` is already set to a non-empty value, in which case it SHALL leave that value unchanged. An empty value counts as unset.

#### Scenario: Allocator not configured
- **WHEN** the trainer starts and `PYTORCH_CUDA_ALLOC_CONF` is unset
- **THEN** training runs with `PYTORCH_CUDA_ALLOC_CONF` equal to `expandable_segments:True`

#### Scenario: Operator configured the allocator
- **WHEN** the trainer starts and `PYTORCH_CUDA_ALLOC_CONF` is already set
- **THEN** training runs with that value unchanged

### Requirement: An out-of-memory result names the real error
When training fails because the chosen precision does not fit on the training device, the trainer SHALL report a rejected result whose reason keeps the "does not fit" and "no fallback was attempted" wording and also contains the original error's type and message, and SHALL print the error's traceback to stderr.

#### Scenario: Load fails with CUDA out of memory
- **WHEN** loading or training raises a CUDA out-of-memory error
- **THEN** `result.json` reports `ok: false` and `accepted: false`, and its reason contains "does not fit", "no fallback was attempted", and the error's message
