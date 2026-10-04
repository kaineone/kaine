# Keep install, transfer and breadth features at the edge

## Why

The complexity audit of 2026-10-03 (W7) found that the core runtime reaches into edge packages. `kaine.boot` imports `kaine.setup.speech_models` at four sites. `kaine.cycle.__main__` imports `kaine.setup.organ` at two. Edge packages hold install, setup, transfer and distributed features that the cognitive runtime should never depend on. Today nothing stops a new import from coupling them further.

## What changes

- The speech-model defaults the runtime needs (`DEFAULT_STT`, `DEFAULT_TTS`, `speech_model_dir`) move to `kaine/model_paths.py`. `kaine.setup.speech_models` re-exports them.
- The organ content check and the organ revision reader that the cycle needs (`OrganContentResult`, `CONTENT_PROBE_TIMEOUT_S`, `verify_organ_generates`, `ORGAN_REVISION_STATE_PATH`, `read_revision_state`) move to a new `kaine/organ_probe.py`. `kaine.setup.organ` re-exports them.
- A new `lint-imports` contract forbids `kaine.boot`, `kaine.cycle` and `kaine.workspace` from importing:
  - `kaine.setup`;
  - `kaine.distributed`;
  - `kaine.transfer`;
  - `kaine.remote`;
  - `kaine.install_target`;
  - `kaine.wheel_index`;
  - `kaine.research.claude_science_export`.

  The one declared exception is `kaine.cycle.__main__ -> kaine.remote.bridge`, which the boot-phase refactor (W5) will move into an optional-components phase. The contract covers direct imports. Two indirect chains through the modules remain and move with the host-probe and organ-gate consolidation (W6):
  - the sherpa speech modules' model check (`kaine.setup.speech_models.verify_model_dir`);
  - the Hypnos organ window's server control (`kaine.setup.model_server`).


## Impact

One test fixture swapped `kaine.organ_window_state` in `sys.modules` and then popped it, instead of restoring it. Later tests then imported a second copy of the module that their patches never reached, so they passed or failed depending on test order. The fixture now restores the original.


No behaviour change: the moved code is unchanged, and the old import paths still work through re-exports. `lint-imports` is a required CI gate, so the boundary is enforced from now on.
