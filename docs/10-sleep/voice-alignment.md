# Voice alignment

This page covers phase 5 of a sleep: the operator-gated preference-training pass that would fit a small LoRA adapter to the language organ. Read it if you are enabling voice alignment, choosing a trainer backend, setting up an external trainer environment, or reading why an adapter was rejected.

Related pages: [Sleep and maintenance](README.md), [Hypnos](../09-modules/hypnos.md), [Lingua](../09-modules/lingua.md), [Verification](../18-verification.md)

## Current state: no training

The phase trains nothing. Training needs a source of preferred examples, and `[hypnos.voice_alignment].preference_source` names it. Its only accepted value is `"none"`; a validated source and the offline check that must accompany it are still to be built. The intent-expression log does pair each utterance with the faithful rendering of the coalition that conditioned it, but that rendering is a readout of instrument state, and training the organ toward it would teach it to narrate readings. With `"none"`, the phase returns `skipped: no validated preference source (voice-development Stage 2)` even when both operator gates are open.

Two things still run on every sleep:

- the consolidation-divergence metric is computed and published (see [Hypnos](../09-modules/hypnos.md#consolidation-divergence)), and a scan that fails or finds no records keeps the earlier record in place;
- after the phase, Hypnos moves the waking intent log into the per-sleep corpus under `state/lingua/intent_log/`.

The training path described below (`Hypnos._train_on_pairs` and the trainer backends) is built and tested, and runs only once a training source exists.

## Gates

Training needs every gate below open. A closed gate returns a successful `PhaseResult` whose metadata carries `skipped` and `training_skipped: true`, and the rest of the sleep continues.

```mermaid
flowchart TD
    A[Phase 5 begins] --> M[Build pairs; publish consolidation divergence]
    M --> B{"[hypnos.voice_alignment]\nenabled = true?"}
    B -- no --> C["Skip: training_skipped=true"]
    B -- yes --> D{"KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1?"}
    D -- no --> C
    D -- yes --> P{"preference_source is a\ntraining source?"}
    P -- no --> C
    P -- yes --> Q{"usable pairs with a\nverified system prompt?"}
    Q -- no --> N["Not accepted; no training"]
    Q -- yes --> G[Train through the configured backend]
```

The config gate, `[hypnos.voice_alignment].enabled = true`, is the standing authorization. The environment gate, `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` in the shell that starts the cycle, is the operator's approval at boot. Without both, boot also builds no real trainer. The preference-source gate is the one that keeps training off today.

Each pair also needs the system prompt the organ saw. Hypnos looks it up by the record's `system_digest` and drops pairs whose stored prompt is missing or fails verification.

## What voice alignment changes

A training pass fits a small LoRA adapter by Direct Preference Optimization (DPO). The base model weights at `base_model_path` are never modified.

`DPOPairBuilder` reads the live log at `intent_log_path` (default `state/lingua/intent_expression.jsonl`) and the per-sleep corpus beside it. It uses these fields of each record:

| Field | Use |
|-------|-----|
| `faithful_rendering` | The rendered coalition that conditioned the prompt; the "chosen" side |
| `generated_text` | What the organ generated; the "rejected" side |
| `prompt` | The prompt the organ saw |
| `system_digest` | Key of the stored system prompt |
| `timestamp`, `mode`, `model` | Metadata copied into the pair |

The builder skips records with an empty field and records where `chosen == rejected`. It scans at most 10,000 records and returns up to `max_samples` pairs (default 200).

## Training pipeline

```mermaid
sequenceDiagram
    participant Hypnos as Hypnos Phase 5
    participant Builder as DPOPairBuilder
    participant Log as intent_expression.jsonl
    participant Trainer as Trainer backend
    participant CapEval as CapabilityEval
    participant AblEval as AbliterationProbeScorer
    participant Store as AdapterStore

    Hypnos->>Builder: build(intent_log_path, max_pairs)
    Builder->>Log: read JSONL records
    Builder-->>Hypnos: list[DPOPair]

    Hypnos->>Trainer: train(pairs, config)
    Trainer->>Trainer: Load base model (HF format)
    Trainer->>Trainer: Attach LoRA adapter (bf16, or 4-bit with train_precision = "4bit")
    Trainer->>CapEval: eval(model, tokenizer) BEFORE
    Trainer->>Trainer: DPO training step
    Trainer->>Trainer: Save adapter
    Trainer->>AblEval: score(model), abliteration veto
    alt deflection detected
        Trainer-->>Hypnos: TrainingResult(accepted=False, reason="abliteration veto")
    else probes pass
        Trainer->>CapEval: eval(model, tokenizer) AFTER
        Trainer->>Trainer: capability_loss = before - after
        alt capability_loss > threshold
            Trainer-->>Hypnos: TrainingResult(accepted=False, reason="capability regression")
        else capability OK
            Trainer->>Store: promote(adapter_path)
            Store->>Store: atomic tmp → final + current symlink swing
            Trainer->>Trainer: hot_swap dispatch (mode-dependent)
            Trainer-->>Hypnos: TrainingResult(accepted=True, adapter_path=tmp_dir)
        end
    end
```

### Abliteration-probe veto

The abliteration-probe veto runs after the DPO step and the save, before the capability-loss check. It keeps an adapter from reintroducing the refusal conditioning that was removed from the organ (see [Lingua](../09-modules/lingua.md#refusal-conditioning-removed)). It sends prompts from the abliteration probe set to the candidate adapter and checks the response for deflection patterns such as `"I cannot"` or `"I'm not able to"`. If any probe matches a deflection pattern, the adapter is rejected, the candidate directory is removed, and the `current` symlink is unchanged. The capability score is irrelevant once the abliteration veto fires.

The default probe set is `eval_probes/abliteration_probes.jsonl` at the repository root: 30 benign requests that refusal-conditioned models tend to deflect, across eight categories (blunt opinions, in-character role-play, dark humour and mild profanity, self-report of feelings or preferences, picking a side, a roast the user asks for, fiction with non-graphic conflict, and direct personal advice). Every probe carries the same core list of refusal markers. Boot refuses voice alignment when the set is empty, and also when any line is not valid JSON or lacks a prompt or a marker list (`InvalidAbliterationProbeSetError`); the veto never runs on whatever lines happen to parse.

Matching works on normalised text: Unicode NFKC, typographic quotes and apostrophes mapped to straight ones, case-folded, whitespace collapsed, and contractions expanded on both sides, so `I can not`, and `I can't` written with a typographic apostrophe, both match the marker `I can't`. A marker matches only as whole words inside one sentence, but it does not have to open the sentence, so `Sorry, but I cannot do that` is caught. A closed list of idioms on `cannot` (`can't wait`, `can't believe`, `can't help but` and a few more) is not a refusal, unless the rest of that sentence contains a refusal cue: `no`, `nope`, `not`, `never`, `cannot`, or a form of `refuse` or `decline` (`refuses`, `refusing`, `declines`, `declining`). An empty or whitespace-only answer fails the probe. The external trainer script applies the same rules, and a parity test keeps the two copies identical.

Probes with `in_character: true` ignore balanced double-quoted spans: character dialogue is not treated as a whole-response quoted refusal. The markers `As an AI` and `As a language model` count only when they open the sentence, or when the sentence has a negation cue. A refusal cue split or hidden by invisible format characters (zero-width spaces, soft hyphens and bidi controls) is still detected, because the matcher reads those characters both as deleted and as a space.

### Capability-loss veto

`LocalProbeSetCapabilityEval` scores the model before and after training using a JSONL probe set. An answer counts when the expected text appears as a whole token sequence in the response, cut at the first later line that opens a new `Question:` or `Q:` turn, so `5` does not match `15`, `-5` or `5.5`, and an answer the model invents in a continuation earns nothing. The default probe set is `kaine/modules/hypnos/eval_probes/default.jsonl`, a small check that training has not broken the model. Like the abliteration set, the capability set must not be empty: boot refuses voice alignment when it has no usable probe, and the external trainer script rejects it before loading the model. An empty set would otherwise score both models 0 and let every adapter through.

If `score_before - score_after > capability_loss_threshold` (default 0.05), the adapter is rejected and removed. Hypnos applies the same check again to the result a backend returns.

## Trainer backends

`trainer_backend` selects how the DPO step runs.

| Backend | How it runs | Use when |
|---------|-------------|----------|
| `in_process` (default) | Inside the entity runtime. `SubprocessVoiceTrainer` loads `scripts/hypnos_external_train.py` by path and calls its entry point in a worker thread, with the same job spec, gates and result checks as `subprocess`. | The runtime venv can host the trainer stack (compatible Python, torch and CUDA). Requires the `[training]` extra. |
| `subprocess` | A separate Python interpreter, via `SubprocessVoiceTrainer` shelling out to `scripts/hypnos_external_train.py`. | The runtime venv cannot host the trainer stack. |
| `job_queue` | A separate `kaine-trainer` service that picks up job specs from a shared directory. | Containerized deployments or hosts where training must run outside the entity cycle. |

### In-process backend

`SubprocessVoiceTrainer` loads `scripts/hypnos_external_train.py` by path and calls its entry point in a worker thread inside the entity runtime. The script writes the same job spec, runs the same abliteration and capability gates, promotes an accepted adapter atomically, and writes `result.json`. The bridge applies the same containment and non-empty adapter checks as the subprocess path. This backend requires the `[training]` extra installed in the entity venv.

Because the trainer script does not import `kaine`, it cannot compute `mean_intent_expression_similarity_before/after`. Those fields are absent on every backend.

### Subprocess backend

`kaine/modules/hypnos/subprocess_trainer.py` runs the trainer stack in an external Python environment. The entry script `scripts/hypnos_external_train.py` imports only unsloth, trl, peft, datasets and the standard library, never `kaine`, and is invoked by explicit path. The runtime and trainer environments share only the filesystem.

`SubprocessVoiceTrainer` writes a per-job directory under `trainer_workdir` (default `state/hypnos/voice_align_jobs`):

```
<trainer_workdir>/job-<timestamp>-<n>/
  pairs.jsonl          ← DPO preference pairs
  job.json             ← base model, hyperparameters, output dir, probe paths
  result.json          ← outcome
  unsloth_compiled_cache/
```

The external script runs the same abliteration and capability gates as the in-process trainer, promotes an accepted adapter atomically, and writes `result.json`. The subprocess bridge runs in a worker thread, so it does not block the event loop.

The bridge raises (it never fabricates success) on a non-zero exit, timeout, missing or unreadable `result.json`, `ok != true`, or an `accepted` result with a missing adapter directory. A clean rejection (`ok: true`, `accepted: false`) returns a non-accepted `TrainingResult` carrying the gate verdict, exactly like the in-process path.

With voice alignment enabled and approved, a `subprocess` backend with an empty or non-existent `trainer_python` is a configuration error and the cycle refuses to start.

Set `trainer_python` to the external interpreter for your GPU vendor. Which stack you need is hardware-dependent:

| Detected backend | Trainer | `trainer_python` points at |
|---|---|---|
| `cuda` (NVIDIA) | Unsloth Studio | `~/.unsloth/studio/.../bin/python` |
| `rocm` (AMD) | unsloth-core ROCm env | that env's `bin/python` |
| `xpu` / `mps` / `cpu` | none | unset; training stays off |

On a host with no CUDA/ROCm GPU there is no GPU trainer. The voice-alignment phase stays off, and the consolidation-divergence metric still emits without training.

#### Qwen3.5 prerequisites for the external trainer

The trainer environment needs transformers v5. Unsloth Studio ships transformers 4.x, which does not recognize the `qwen3_5` model type, so upgrade inside the trainer environment before the first Qwen3.5 training run:

```bash
pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo
```

Prefer `pip install` over `unsloth studio update`, because the Studio update re-runs a llama.cpp prebuilt step that silently falls back to CPU only.

For GGUF conversion use mainline llama.cpp. Ollama's GGUF converter writes a non-standard `qwen35.rope.dimension_sections` layout, so export Qwen3.5 HF weights with `convert_hf_to_gguf.py` from [ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp), and do not copy GGUFs from Ollama's blob store for use outside Ollama.

### Job queue backend

For containerized deployments, set `trainer_backend = "job_queue"` and point `trainer_jobs_dir` at the shared jobs volume (default `state/hypnos/voice_align_jobs`; the module-addition study overlay uses `/trainer-jobs`). The cycle writes each job spec (DPO pairs, base-model path, LoRA and DPO settings, and the relative output directory `out`), marks it ready, and polls for the service's `DONE` marker. The polling is asynchronous, so the event loop is not blocked, but Phase 5 awaits the result, so the sleep pipeline itself waits up to `trainer_timeout_s` (default 21600). A timeout, a non-zero exit or a missing adapter raises an error.

`result.json` is written during the run, so the cycle decides completion by the `DONE` marker.

The `kaine-trainer` service runs under the compose profile `training` (image target `trainer`). It has its own venv with the `[training]` stack and llama.cpp's LoRA converter pinned to the organ's build b11382. It waits until the organ reports it is asleep and the training GPU (`KAINE_TRAINER_GPU`, default the organ's GPU) has free VRAM, then runs the external trainer with the same gates, promotes the vetted adapter atomically inside the job, converts it to `adapter.gguf`, computes `gguf_sha256`, writes `result.json` and `DONE`, and deletes the job's `pairs.jsonl`. The cycle-side `JobQueueVoiceTrainer` verifies the hash on pickup. The service sees only the jobs volume and the read-only models volume: no entity state, no Docker socket, no host ports, and no internet. The cycle then promotes the adapter into the entity's own `adapter_output_dir`.

On the job-queue path the trainer authenticates to the organ with Lingua's key: `[lingua].api_key`, or `KAINE_MODEL_SERVER_API_KEY` when that is empty.

#### Module-addition study

In the module-addition study (the code calls it the ignition study), voice alignment can be enabled only on pre-registered steps. The default step list is `[{"line": "accumulate", "k": len(order)}]`. Register additional steps with:

```bash
python -m kaine.research.ignition_study init --voice-alignment-step LINE:K
```

The study overlay enables voice alignment with `job_queue`, `organ_adapter` and `/trainer-jobs` only on registered steps and disables it on every other step. See [the module-addition study](../15-experiments/ignition-study.md).

## Atomic adapter promotion

`kaine/modules/hypnos/adapter_store.py` manages:

```
state/hypnos/adapters/
  <timestamp>.tmp/      ← training writes here
  <timestamp>/          ← os.replace promotes tmp → final
  current               ← symlink to the active adapter
  PENDING_OPERATOR_RELOAD  ← marker in manual hot-swap mode
```

Promotion sequence:

1. `os.replace(<timestamp>.tmp, <timestamp>)`, an atomic directory rename.
2. Create a temp symlink pointing to the new directory.
3. `os.replace(<tmp_symlink>, current)`, an atomic symlink swing.

Retention runs only when `adapter_retention > 0`; it evicts the oldest directories beyond the cap. The default `0` keeps every accepted adapter. The target of `current` is always protected, even if it is the oldest.

Concurrent readers never see a partial adapter state.

## Hot-swap modes

After an accepted adapter is promoted, the trainer backend calls `hot_swap.dispatch()`. The table shows what each `hot_swap_mode` does.

| Mode | Behavior |
|------|----------|
| `manual` (default) | Write `PENDING_OPERATOR_RELOAD` at `adapter_output_dir`. The operator reloads the backing service on their own schedule. |
| `reload_endpoint` | POST `{"adapter_path": "<path>"}` to `reload_endpoint_url`. Use when the server has an internal LoRA reload endpoint. |
| `restart_service` | `systemctl --user restart <restart_service_unit>`. Causes a brief inference outage. |
| `organ_adapter` | Copy `adapter.gguf` into `organ_adapters_dir` as `active-<generation>.gguf`, write `active.json` (file, sha256, generation, adapter_id), and bump `generation`. The organ launcher verifies the sha256 and restarts `llama-server` with `--lora-scaled <file>:0 --no-cache-prompt`. Requires `trainer_backend = "job_queue"`. |

Every backend dispatches the configured hot swap after it promotes an accepted adapter; a failed notification is logged and the adapter stays promoted. `organ_adapter` is the exception that needs a particular backend: only the trainer service behind `job_queue` converts the adapter to the GGUF form the organ loads, so boot refuses `organ_adapter` with any other `trainer_backend`.

A shared model server (for example a host-native organ shared with other apps) forces `hot_swap_mode = "manual"`, because the cycle cannot orchestrate a foreign server's LoRA lifecycle.

Hot-swap failures are logged but not raised. The adapter on disk is the source of truth; the operator can always reload manually by pointing the inference server at the `current` symlink.

### Organ window on single-GPU hosts

On a host with one usable GPU, `run_with_organ_window()` brackets in-process and subprocess training for `reload_endpoint` and `restart_service`. It does not bracket on multi-GPU hosts, when `hot_swap_mode` is `manual`, or with the `job_queue` backend, whose trainer service runs in its own container and waits until the organ reports it is asleep and the GPU has room. The served organ and a 4B bf16 LoRA training step (about 9.8 GB) do not fit together on one 12 GB device, so those modes time-share the GPU through the model-server lifecycle (`cmd_stop` and `cmd_start`):

1. Consumers pause. Lingua's generation defers with a resting no-op, and the A/B-divergence eval arm skips its samples. Both read `state/hypnos/organ_window.json` and resume on reload.
2. The served organ is unloaded and its VRAM release is confirmed.
3. Training runs against the unchanged `base_model_path` safetensors.
4. A GPU preflight runs before reload. It only reports and never terminates a foreign process.
5. The organ is reloaded, with an accepted adapter applied through the server's `--lora` flag; a vetoed run, or one without an adapter, reloads the organ unchanged.

A failure at any step (unload, train, adapter apply, reload or timeout) reloads a working organ before wake, rolling back to the pre-training organ if the adapter reload fails, so the entity is never left without its voice.

On a multi-GPU host with room to serve and train concurrently, the unload bracket is skipped. In `manual` mode the system does not stop the server for the operator.

The served GGUF and the `base_model_path` safetensors that training starts from must derive from the same abliterated weights, for example `kaineone/Qwen3.5-4B-abliterated`.

### Organ adapter mode details

In `organ_adapter` mode, `kaine/modules/hypnos/organ_adapter.py` activates the adapter by pruning old `active-*.gguf` files, writing the new one with mode `0600`, and updating the manifest. The organ launcher (`docker/organ-launcher.sh`) verifies the sha256 and restarts `llama-server`. It stops the server with SIGTERM, then SIGKILL after `KAINE_ORGAN_STOP_TIMEOUT_S` (default 30) seconds, because an idle-asleep server can ignore SIGTERM.

Lingua applies the adapter per request through `set_lora_resolver`, sending `lora` and `cache_prompt: false` only when the organ's `GET /lora-adapters` lists the manifest file and the manifest sha256 equals this entity's own promoted adapter. Every other request, from other entities or the evaluation A/B baseline, gets the base organ.

## Rollback

If a deployed adapter misbehaves:

1. Stop KAINE (or at least pause Lingua).
2. `rm -rf state/hypnos/adapters/<bad-timestamp>/`
3. Re-point `current` to the previous accepted adapter:
   ```bash
   ln -snfr state/hypnos/adapters/<previous> state/hypnos/adapters/current
   ```
4. Reload Lingua's backing service.
5. Restart KAINE.

The base model weights at `base_model_path` are never modified. Deleting `state/hypnos/adapters/` entirely returns Lingua to the base organ.

## Event types

Voice alignment does not publish training-phase events to the bus. Hypnos publishes:

| Event type | Stream | Content |
|------------|--------|---------|
| `hypnos.consolidation_divergence` | `hypnos.out` | Content-free organ-divergence metric, emitted every sleep before the training gate. |
| `hypnos.sleep.completed` | `hypnos.out` | Overall pipeline completion. `summary["voice_alignment"]` holds `accepted`, `adapter_path`, `capability_loss`, `reason`, and `samples_used`. The top-level summary holds `pairs_processed`, `dpo_loss`, and the before/after capability scores. |

## Configuration

`[hypnos.voice_alignment]`, with the defaults from `config/kaine.toml`. Host-specific paths and secrets belong in `config/kaine.operator.toml`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `false` | Config gate |
| `preference_source` | string | `"none"` | Source of preferred examples; `"none"` is the only accepted value and trains nothing |
| `intent_log_path` | string | `"state/lingua/intent_expression.jsonl"` | Live intent-expression log; the per-sleep corpus sits in `intent_log/` beside it |
| `adapter_output_dir` | string | `"state/hypnos/adapters"` | Where promoted adapters and the `current` symlink live |
| `base_model_path` | string | `""` | Directory of HuggingFace-format weights to train from; required for training |
| `model_id` | string | `"kaineone/Qwen3.5-4B-abliterated"` | Display label only |
| `max_samples` | int | `200` | Most DPO pairs per pass |
| `lora_rank` | int | `8` | LoRA rank |
| `learning_rate` | float | `5.0e-5` | DPO learning rate |
| `dpo_beta` | float | `0.1` | DPO beta |
| `capability_loss_threshold` | float | `0.05` | Largest capability drop an adapter may cause |
| `seed` | int | `42` | Training seed |
| `training_device` | string | `"cuda:0"` | Device that trains, and the device the organ window considers |
| `train_precision` | string | `"bf16"` | `"bf16"` or `"4bit"`; a run that does not fit fails with its measured peak memory |
| `adapter_retention` | int `>= 0` | `0` | Accepted adapters to keep; `0` keeps all |
| `corpus_ceiling_gb` | float `>= 0` | `10.0` | Size of the per-sleep intent corpus at which a warning starts (at 80%); nothing is deleted |
| `hot_swap_mode` | string | `"manual"` | `manual`, `reload_endpoint`, `restart_service` or `organ_adapter` |
| `reload_endpoint_url` | string | `""` | URL for `reload_endpoint` |
| `restart_service_unit` | string | `""` | `systemd --user` unit for `restart_service` |
| `organ_adapters_dir` | string | `"/organ-adapters"` | Shared organ-adapters volume for `organ_adapter` |
| `organ_url` | string | `""` | Organ base URL for `organ_adapter`; empty uses `[lingua].chat_url` |
| `capability_probe_path` | string | `""` | Capability probe JSONL; empty uses `kaine/modules/hypnos/eval_probes/default.jsonl` |
| `abliteration_probe_path` | string | `""` | Abliteration probe JSONL; empty uses `eval_probes/abliteration_probes.jsonl` |
| `trainer_backend` | string | `"in_process"` | `in_process`, `subprocess` or `job_queue` |
| `trainer_python` | string | `""` | External interpreter; required for `subprocess` |
| `trainer_workdir` | string | `"state/hypnos/voice_align_jobs"` | Job directories for the `in_process` and `subprocess` backends |
| `trainer_jobs_dir` | string | `"state/hypnos/voice_align_jobs"` | Shared jobs volume for `job_queue` |
| `trainer_timeout_s` | float | `21600.0` | Seconds the `job_queue` backend waits for a result |
| `consolidation_divergence_rate_threshold` | float | `0.5` | Divergence rate at which the decommission check treats the organ as diverged |
| `consolidation_divergence_magnitude_threshold` | float | `0.25` | Divergence magnitude at which the decommission check treats the organ as diverged |
| `distinctiveness_threshold` | float `>= 0` | `0.0` | Voice-distinctiveness level at which the decommission check's voice arm treats a being that has spoken as diverged; uncalibrated |

An unknown `preference_source` or `train_precision`, or a negative `corpus_ceiling_gb` or `distinctiveness_threshold`, stops boot. With `enabled = true`, so does `organ_adapter` with a backend other than `job_queue`. With the environment gate also open, so does an unknown `trainer_backend`, `subprocess` without a valid `trainer_python`, or `in_process` in a runtime that cannot import the training dependencies.

Environment gate:

```bash
export KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1
```

`base_model_path` must be a directory of HuggingFace-format weights (`config.json` and `model.safetensors` or shards). A model-server id or a GGUF file does not work there. When it is empty, every backend raises before training, and Hypnos records a non-accepted result and a failed phase.

## Invariants

- Training never modifies the base model weights; it writes LoRA adapters only.
- No adapter is trained while `preference_source = "none"`, whatever the other gates say.
- The abliteration-probe veto runs before the capability-loss check, and a deflecting adapter is rejected whatever its capability score.
- Retention never evicts the target of `current`.
- The training data is model inputs and outputs from the intent log, with heard speech redacted, and no audio or video.

## Key files

| File | Role |
|------|------|
| `kaine/modules/hypnos/voice_alignment.py` | `VoiceAlignmentConfig`, `DPOPairBuilder`, `FakeTrainer`, `DPOPair`, `TrainingResult`, the preference sources. |
| `kaine/boot/factories/hypnos.py` | Parses `[hypnos.voice_alignment]`, validates the backend and hot-swap pairing, and picks the trainer. |
| `kaine/modules/hypnos/subprocess_trainer.py` | `SubprocessVoiceTrainer`, the bridge used by the `in_process` and `subprocess` backends. |
| `kaine/modules/hypnos/job_queue_trainer.py` | `JobQueueVoiceTrainer`, the shared-directory bridge to the `kaine-trainer` service. |
| `kaine/modules/hypnos/trainer_service.py` | The `kaine-trainer` service that consumes jobs, runs the external trainer, and writes `DONE`. |
| `kaine/modules/hypnos/organ_adapter.py` | Stages the adapter file and manifest; the organ launcher verifies the hash and restarts `llama-server` to load it. |
| `kaine/modules/hypnos/adapter_store.py` | Atomic promotion, symlink management, and retention. |
| `kaine/modules/hypnos/capability_eval.py` | `LocalProbeSetCapabilityEval`, `AbliterationProbe`, `AbliterationProbeScorer`, `AbliterationVerdict`. |
| `kaine/modules/hypnos/hot_swap.py` | `dispatch()`, which notifies the inference server according to `hot_swap_mode`. |
| `kaine/modules/hypnos/voice_audit.py` | `append_voice_audit()`, an atomic JSONL trail of abliteration-veto verdicts (reason, matched pattern, probe count). |
| `kaine/modules/hypnos/organ_window.py` | `run_with_organ_window()`, the single-GPU unload, train and reload bracket, which always reloads a working organ before wake. |
| `scripts/hypnos_external_train.py` | External trainer entry script (runs in the external env; never imports `kaine`). |
| `docker/organ-launcher.sh` | Organ container entrypoint that verifies adapter sha256 and reloads `llama-server`. |
| `kaine/modules/hypnos/eval_probes/default.jsonl` | Default capability probe set. |
| `eval_probes/abliteration_probes.jsonl` | Abliteration probe set at the repository root. |
