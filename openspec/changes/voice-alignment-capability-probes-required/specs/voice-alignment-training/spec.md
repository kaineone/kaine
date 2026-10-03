## MODIFIED Requirements

### Requirement: Capability-loss veto prevents adapter promotion
The trainer SHALL run a capability-eval pass on both the pre-
training and post-training models, compute
`capability_loss = score_before - score_after`, and promote the
adapter ONLY when `capability_loss <= config.capability_loss_threshold`.
Rejection SHALL `shutil.rmtree` the tmp directory and set
`accepted=False` with `reason` containing the numeric loss. The
capability probe set SHALL contain at least one usable probe: boot SHALL
refuse to start voice alignment on any trainer backend when it does not
(`EmptyCapabilityProbeSetError`), and a trainer that finds it empty at
training time SHALL reject the adapter rather than score both models 0.

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

#### Scenario: Boot refuses an empty capability probe set
- **WHEN** voice alignment is enabled and operator-approved and `[hypnos.voice_alignment].capability_probe_path` names an empty or missing file, on any trainer backend
- **THEN** boot raises `EmptyCapabilityProbeSetError` naming the path

#### Scenario: The external trainer rejects on an empty capability probe set
- **WHEN** the external trainer script receives a job whose capability probe set has no usable probe
- **THEN** the adapter is not promoted and the result's reason says the capability probe set is empty
