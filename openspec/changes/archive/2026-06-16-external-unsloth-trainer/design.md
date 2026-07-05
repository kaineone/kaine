# Design — out-of-process voice-alignment trainer

## Decision: subprocess-per-job, not a persistent service

Sleep-cycle training is infrequent (once per consolidation). A subprocess
spawned per job is simpler, fully isolated, and leaves no training process
resident on the GPU competing with the language organ for VRAM between sleeps.
(A persistent `unsloth-studio.service` exists on the reference host but is not
required; subprocess-per-job is the chosen path.)

## The IPC contract (filesystem job spec, no shared memory / no shared Python)

The runtime venv and the trainer env share nothing but the filesystem.

1. **Hypnos (runtime venv)** writes a job directory under `trainer_workdir`:
   - `pairs.jsonl` — the DPO preference pairs (`prompt`, `chosen`, `rejected`).
     This is the SAME data the in-process path builds; it never contains raw
     sense data (the pairs are organ utterances vs workspace-conditioned
     renderings).
   - `job.json` — base-model reference (the abliterated tag / local path),
     LoRA/DPO hyper-parameters, the target adapter output dir, a schema version.
2. **The external entry script** (run by `trainer_python`) reads `job.json` +
   `pairs.jsonl`, runs the real unsloth DPO, writes the adapter to the output
   dir, and writes `result.json` (`ok`, `adapter_dir`, `steps`, `loss`,
   `reason`). It imports only unsloth/trl/peft/datasets — never `kaine`.
3. **Hypnos** waits for exit, then validates: exit code 0 AND `result.json.ok`
   AND a non-empty adapter dir with the expected files. Any failure → raise
   (no fake success). On success it returns a `TrainOutcome` identical in shape
   to the in-process trainer, so the capability gate, abliteration gate, and
   adapter merge downstream are unchanged.

## Config (`[hypnos.voice_alignment]`)

- `trainer_backend = "in_process" | "subprocess"` — default `"in_process"`
  (ships unchanged; the reference host sets `"subprocess"` in its operator
  config).
- `trainer_python = ""` — path to the external interpreter (e.g. the Unsloth
  Studio python). Required when backend is `subprocess`; empty + subprocess =
  config error at boot (fail closed, mirrors the missing-extra guard).
- `trainer_workdir = "state/hypnos/voice_align_jobs"` — job-spec + adapter
  staging. Operator may redirect to a roomier disk (the reference host points it
  at the second SSD).

## Boundary & safety

- The external entry script is a standalone file invoked by path; it is NOT in
  the `kaine` import graph, so the import-linter contracts and the sidecar
  boundary are unaffected.
- `trainer_python` is operator-configured (not derived from observed content);
  the subprocess is invoked with an explicit argv (no shell), a timeout, and the
  job dir as CWD so unsloth's `unsloth_compiled_cache/` lands there, not in the
  repo.
- Privacy: `pairs.jsonl` carries only the preference-pair text already used for
  training; the job dir inherits the same at-rest handling as other Hypnos
  state. No new bus events; the existing voice-alignment / consolidation-
  divergence telemetry is unchanged.

## Out of scope

- Updating the Unsloth Studio version (operator-managed; the bridge is
  version-decoupled).
- Distributed/multi-host training; remote (non-local) trainer envs.
