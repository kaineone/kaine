# Each voice-alignment trainer backend works with the hot-swap modes it can serve

## Why
Voice alignment has three trainer backends (`in_process`, `subprocess`, `job_queue`) and four hot-swap modes (`manual`, `reload_endpoint`, `restart_service`, `organ_adapter`). A documentation audit found combinations that boot but cannot work:

- **`organ_adapter` needs a GGUF adapter**, and only the trainer service behind `job_queue` converts the adapter to GGUF. With `in_process`, `UnslothDPOTrainer` calls the hot swap without the organ volume or URL, so activation fails with "organ_adapters_dir not configured" after every accepted training run. With `subprocess`, nothing is dispatched at all.
- **The `subprocess` backend never dispatches any hot swap.** An accepted adapter is promoted on disk, but `reload_endpoint` and `restart_service` never notify the server, so the organ keeps serving the old voice.
- **The GPU window brackets job-queue training.** With `job_queue` on a single GPU, `run_with_organ_window` tries to stop and restart the model server through the host-side lifecycle from inside the cycle's container, where there is no server to stop. It is a no-op today, but it is the wrong owner: the trainer service already waits until the organ reports it is asleep and the GPU has room.

Research impact: none in practice. The running MoC7 study is unaffected (pinned image). Its configuration uses `job_queue` with `organ_adapter`, where the bracket was already a no-op; it now records `skipped_reason` instead of attempting it.

## What changes
- Boot refuses `hot_swap_mode = "organ_adapter"` unless `trainer_backend = "job_queue"`, naming both keys and why.
- `SubprocessVoiceTrainer` dispatches the configured hot swap after an accepted, promoted adapter, with the same arguments and failure handling as `UnslothDPOTrainer` (a failed notification is logged and the adapter stays promoted).
- `run_with_organ_window` takes the trainer backend and does not bracket `job_queue` training (`skipped_reason`: the trainer service coordinates with the organ's own sleep), alongside the existing multi-GPU and `manual` exemptions.

## Impact
- Code: `kaine/boot.py` (validation, passing the backend to the window), `kaine/modules/hypnos/subprocess_trainer.py`, `kaine/modules/hypnos/organ_window.py`.
- Specs: `voice-alignment-training` (ADDED).
- Docs: the voice-alignment page's backend and hot-swap tables.
