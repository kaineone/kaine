# Voice alignment refuses to run its capability veto on an empty probe set

## Why
Voice alignment promotes a trained adapter only if two checks pass: the abliteration veto and the capability-loss veto. The abliteration probe set must be non-empty. Boot checks it for every trainer backend, and the scorer raises `EmptyAbliterationProbeSetError`. The capability probe set has no such guard. `LocalProbeSetCapabilityEval` scores an empty or missing set as 0.0 for the model before training and for the model after it, and the external trainer script (`scripts/hypnos_external_train.py`, used by the `subprocess` and `job_queue` backends) does the same. The loss is then 0.0, so the capability veto passes every adapter while the audit trail records a passed check. A typo in `[hypnos.voice_alignment].capability_probe_path`, or a probe file that is empty or has no usable lines, silently switches off half of the promotion gate.

The same gap in the merged-adapter checks was closed by `merge-veto-fails-closed`, which added `LocalProbeSetCapabilityEval(require_probes=True)` and `EmptyCapabilityProbeSetError`.

Research impact: none for the running MoC7 study. It uses the bundled 12-probe set at a pinned image, so its gate is intact. For future runs the behaviour changes only when the probe set is empty or missing: boot refuses, where today it starts with a capability veto that always passes.

## What changes
- **Boot.** Every trainer backend (`in_process`, `subprocess`, `job_queue`) checks, beside the existing abliteration check, that the capability probe set has at least one usable probe, and raises `EmptyCapabilityProbeSetError` with the path otherwise.
- **In-process trainer.** `UnslothDPOTrainer`'s default evaluator is built with `require_probes=True`, so an empty set at training time rejects the adapter.
- **External trainer script.** An empty usable capability probe set rejects the adapter (not promoted), with the reason in the result, as an empty abliteration set already does.
- The gate-parity test covers the new rule on both paths.
