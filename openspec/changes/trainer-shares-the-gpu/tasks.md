# Tasks

## 1. Trainer

- [x] 1.1 `main` sets `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` with `setdefault` before `_train` runs. Verify with a hygiene test for both the unset and the preset case.
- [x] 1.2 The out-of-memory result's reason appends the original error's type and message (truncated), and the traceback goes to stderr. Verify with the fake-stack OOM test.

## 2. Checks

- [x] 2.1 A real GPU run of the 4B base in bf16 succeeds on the shared desktop card without an allocator setting in the environment.
- [x] 2.2 `openspec validate trainer-shares-the-gpu --strict` passes.
