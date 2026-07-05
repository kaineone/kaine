## ADDED Requirements

### Requirement: UnslothDPOTrainer.train executes a real DPO step
The `UnslothDPOTrainer.train(pairs, config)` method SHALL load the
base model via Unsloth's `FastLanguageModel`, attach a LoRA adapter
sized by `config.lora_rank`, build a `Dataset` from the DPO pairs,
run `trl.DPOTrainer` with the configured `beta`, `learning_rate`,
`max_samples`, and `seed`, and write the resulting adapter to
`<adapter_output_dir>/<timestamp>.tmp/` before any evaluation. The
returned `TrainingResult` SHALL carry `dpo_loss`, `samples_used`,
and the adapter path.

#### Scenario: Real training writes a tmp adapter
- **WHEN** the trainer runs on a FakeUnslothBackend with two valid
  DPO pairs and a base model path
- **THEN** the backend records a DPOTrainer.train() call and a
  `<adapter_output_dir>/<timestamp>.tmp/` directory exists with the
  serialized LoRA weights

### Requirement: Capability-loss veto prevents adapter promotion
The trainer SHALL run a capability-eval pass on both the pre-
training and post-training models, compute
`capability_loss = score_before - score_after`, and promote the
adapter ONLY when `capability_loss <= config.capability_loss_threshold`.
Rejection SHALL `shutil.rmtree` the tmp directory and set
`accepted=False` with `reason` containing the numeric loss.

#### Scenario: Adapter rejected on capability drop
- **WHEN** post-training capability is 0.40 and pre-training was
  0.60 (loss = 0.20) and `capability_loss_threshold = 0.05`
- **THEN** the tmp adapter directory is removed, the final adapter
  directory is not created, the `current` symlink is unchanged,
  and `TrainingResult.accepted` is False

#### Scenario: Adapter promoted on minor capability drop
- **WHEN** post-training capability is 0.58 and pre-training was
  0.60 (loss = 0.02) and threshold is 0.05
- **THEN** `os.replace(tmp_dir, final_dir)` runs and the
  `<adapter_output_dir>/current` symlink atomically updates to
  point at the new final directory

### Requirement: Atomic adapter promotion via rename
Adapter promotion SHALL use `os.replace` to move
`<timestamp>.tmp/` to `<timestamp>/`, and SHALL update
`<adapter_output_dir>/current` via a temp-symlink + `os.replace`
sequence so concurrent readers (Lingua/Unsloth Studio in any future
auto-reload mode) never see a partial state.

#### Scenario: No partial-state window
- **WHEN** the promotion sequence is interrupted at any point
- **THEN** either the old `current` symlink is still valid, or the
  new final directory is fully written and `current` points at it
  — never both broken at once

### Requirement: Operator-opt-in safety gate
The voice-alignment phase SHALL fire training only when BOTH
`[hypnos.voice_alignment].enabled = true` AND
`KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` are set. When either
condition is missing, the phase SHALL log a clear remediation line
and return a `PhaseResult` with metadata `{"skipped": "<reason>"}`.

#### Scenario: Config off
- **WHEN** `enabled = false` and the env var is set
- **THEN** the trainer is not constructed, no DPO step runs, and
  the phase result metadata contains `"skipped": "config disabled"`

#### Scenario: Env var off
- **WHEN** `enabled = true` and the env var is unset
- **THEN** the trainer is not constructed, no DPO step runs, and
  the phase result metadata contains `"skipped": "operator
  approval not granted (set KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1)"`

### Requirement: Adapter retention bounded
A retention policy SHALL keep at most
`[hypnos.voice_alignment].adapter_retention` accepted adapters
(default 5) under `adapter_output_dir`. Older accepted adapters
SHALL be evicted after every successful promotion. The `current`
symlink is never evicted.

#### Scenario: Eviction on overflow
- **WHEN** 6 adapters are accepted in sequence and retention is 5
- **THEN** only the 5 most-recent timestamp directories remain;
  `current` points at the newest

### Requirement: Capability-eval harness is pluggable
The trainer SHALL accept a `capability_eval: CapabilityEval`
collaborator via `__init__`. The default `LocalProbeSetCapabilityEval`
SHALL read `kaine/modules/hypnos/eval_probes/default.jsonl` and
compute `correct / total` against the model. The operator MAY
substitute their own evaluator by passing one explicitly or by
overriding the probe-set path via
`[hypnos.voice_alignment].capability_probe_path`.

#### Scenario: Custom evaluator honored
- **WHEN** an operator-provided CapabilityEval is passed to
  `UnslothDPOTrainer.__init__` and the trainer is run
- **THEN** the custom evaluator's `eval()` method is invoked twice
  (pre-training and post-training) and its returned scores feed the
  capability-loss check

### Requirement: Lingua hot-swap mode is operator-configurable
`[hypnos.voice_alignment].hot_swap_mode` SHALL accept one of
`"manual"` (default), `"reload_endpoint"`, or `"restart_service"`.
On adapter accept:
- `manual` — write a marker file
  `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` and log a line
  pointing the operator at the manual reload step. No service call.
- `reload_endpoint` — POST to a configured Unsloth Studio reload
  endpoint with the new adapter path.
- `restart_service` — invoke `systemctl --user restart` against a
  configured unit name.

#### Scenario: Manual mode is the default
- **WHEN** an operator inspects shipped `config/kaine.toml`
- **THEN** `[hypnos.voice_alignment].hot_swap_mode = "manual"`

#### Scenario: Manual mode writes the marker
- **WHEN** an adapter is accepted under `hot_swap_mode = "manual"`
- **THEN** `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` exists
  and contains the path of the newest accepted adapter

### Requirement: Optional `[training]` extras gate failures loudly
The trainer SHALL lazy-import `unsloth`, `trl`, `peft`, and
`datasets` inside `train()`. When any is missing, `train()` SHALL
return `TrainingResult(accepted=False, reason="<extras name> not
installed — pip install -e .[training]")` rather than raising. The
phase SHALL log the message and continue the rest of the sleep
cycle.

#### Scenario: Missing extras don't crash sleep
- **WHEN** `[hypnos.voice_alignment].enabled = true` and the env
  var is set but `unsloth` is not installed
- **THEN** `train()` returns a TrainingResult with `accepted=False`
  and `reason` naming the `training` extras group, and the sleep
  cycle's other phases (memory consolidation, belief revision,
  affect reset, temporal recalibration) still complete

### Requirement: TrainingResult populates voice-tracking fields
The returned `TrainingResult` SHALL include the fields the
evaluation sidecar's `voice_tracking.py` already consumes from the
published `hypnos.cycle_complete` event:
`pairs_processed`, `pairs_above_threshold`, `dpo_loss`,
`adapter_accepted`, `capability_score_before`,
`capability_score_after`, `mean_intent_expression_similarity_before`,
`mean_intent_expression_similarity_after`. Today these are zero or
missing because the trainer is a stub; this change SHALL make them
real.

#### Scenario: Sidecar sees real numbers
- **WHEN** a real training pass completes and the
  `hypnos.cycle_complete` event is published
- **THEN** the evaluation sidecar's `voice_tracking-<date>.jsonl`
  contains an entry with non-None `dpo_loss`, `mean_similarity_before`,
  and `mean_similarity_after` fields

### Requirement: VOICE_ALIGNMENT.md document ships alongside code
The repository SHALL ship `kaine/modules/hypnos/VOICE_ALIGNMENT.md`
covering: what voice alignment changes about Lingua's behavior, the
opt-in procedure, the capability-loss veto, the three hot-swap
modes and how to switch between them, and the rollback procedure
(delete the latest adapter, restart Unsloth Studio).

#### Scenario: Document exists
- **WHEN** an operator checks out the change
- **THEN** `kaine/modules/hypnos/VOICE_ALIGNMENT.md` is present
  and references both the config gate and the env-var gate
