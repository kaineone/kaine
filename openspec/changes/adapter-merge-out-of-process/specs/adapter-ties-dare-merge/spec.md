## ADDED Requirements

### Requirement: The merge and its checks run in a child process
`TiesDareAdapterMerger.merge` SHALL run the PEFT merge and both merged-adapter checks in a child process, `python -m kaine.lifecycle.adapter_merge_worker`. The calling process SHALL NOT load the base model, the adapters or either check, and SHALL NOT import `transformers` or `peft` during a merge.

#### Scenario: The parent never loads the model
- **WHEN** a merge runs
- **THEN** `transformers` and `peft` are not in the parent's loaded modules and its default torch dtype is unchanged

### Requirement: The merge child is launched with private inputs and bounded
The parent SHALL pass the merge inputs in a job file (0600) inside a directory (0700) that it removes afterwards. It SHALL start the child with an explicit argument list, no shell, its own session, the voice trainer's environment allowlist (Hugging Face offline) and a timeout (`merge_timeout_s`), and on a timeout SHALL kill the child's whole process group.

#### Scenario: The child's environment is an allowlist
- **WHEN** the child is started while the parent holds a state key and an organ API key in its environment
- **THEN** the child's environment holds neither and sets the Hugging Face offline variables

#### Scenario: A timeout kills the process group
- **WHEN** the child, or a process it started, is still running at the timeout
- **THEN** the whole process group is killed, the merge fails, and the parent does not wait on the child's output pipes

### Requirement: A merged adapter is staged and moved into place only after a validated result
The child SHALL merge into a staging directory beside the output directory, named `.<output name>.partial`, and write `result.json` atomically (0600). The parent SHALL rename the staging directory to the output directory only for an acceptable result, so no reader finds a half-written merged adapter; every other outcome SHALL remove the staging directory.

#### Scenario: A crashed child leaves nothing behind
- **WHEN** the child exits non-zero after writing part of its output
- **THEN** the merge fails, the staging directory is removed, and the output directory does not exist

### Requirement: A bad child result is a failed merge
A non-zero exit, a timeout, a launch error, and a missing, unreadable, malformed or mismatched result SHALL each be a failed merge (`metadata.adapter_merge_failed`), never an unchecked success. A result is acceptable only when its schema version matches, `ok` is true, `merged_dir` is the staging directory, the staging directory holds a top-level `adapter_config.json`, and the check evidence is valid. The stderr tail recorded in metadata and error messages SHALL have filesystem paths scrubbed.

#### Scenario: A success claim without evidence is refused
- **WHEN** the child writes `ok` true and the staging directory as `merged_dir` but no check evidence
- **THEN** the merge fails, nothing is kept, and the staging directory is removed

### Requirement: The parent verifies the check evidence
An acceptable result SHALL carry `abliteration_passed` exactly true, `abliteration_probes_scored` an integer of at least 1, at least two parent capability scores and the merged score each finite in [0, 1], and `capability_loss` finite and not above `capability_loss_threshold`. The parent SHALL refuse a result missing any of these or holding an invalid value, and SHALL record the validated values in the merge metadata.

#### Scenario: A valid result records its evidence
- **WHEN** the child reports a passing abliteration verdict over 4 probes and a capability loss within the threshold
- **THEN** the merged adapter is kept and the merge metadata holds `abliteration_passed`, `abliteration_probes_scored`, `capability_score_parents`, `capability_score_merged` and `capability_loss`

### Requirement: Stale merge staging is cleaned and never attributed
When a merge starts, it SHALL remove sibling staging directories older than the merge timeout. Decommission SHALL NOT attribute a directory whose name starts with `.` and ends with `.partial` to an entity as a merged adapter, whether as its own or a kept one.

#### Scenario: A stale staging directory is not an entity's adapter
- **WHEN** decommission attributes the merged-adapter directories and one is a stale `.<name>.partial`
- **THEN** it is neither listed as the entity's adapter nor as a kept one

#### Scenario: An old staging directory is swept
- **WHEN** a merge starts and a sibling `.<name>.partial` is older than the merge timeout
- **THEN** it is removed and a younger one is left

## MODIFIED Requirements

### Requirement: Merged-adapter output layout is deterministic
Each merge SHALL be written to its own directory `<output_dir>/<timestamp>-<8 hex>/`, the random suffix keeping two merges that start in the same second apart. The directory itself SHALL be a loadable PEFT adapter directory: `adapter_config.json` and the adapter weights at its top level, not in a subdirectory named for the adapter. Two merges of the same parent pair at different times SHALL not collide.

#### Scenario: Two merges of same parents coexist
- **WHEN** the same parent pair is merged twice with a wait
  between
- **THEN** two separate directories exist under the output directory, and both load via
  `peft.PeftModel.from_pretrained`

#### Scenario: The merged directory is a loadable adapter
- **WHEN** a merge is kept
- **THEN** `adapter_config.json` is directly inside the returned directory

### Requirement: The merge caller supplies the merged-adapter checks
`merger_from_name` SHALL build the real merger with the checks' settings, not with check objects: the capability and abliteration probe-set paths from `[lifecycle.adapter_merge].capability_probe_path` and `abliteration_probe_path` (empty selects the bundled probe sets), the capability-loss threshold, and `merge_timeout_s`. It SHALL NOT accept a `merge_checks` factory and SHALL NOT build an evaluator, a scorer or a model loader in the calling process; the child process builds them from the job. The dashboard SHALL pass the `[lifecycle.adapter_merge]` section to `merger_from_name` and SHALL run `ForkManager.merge` in a worker thread rather than on its event loop.

#### Scenario: Dashboard merges are checked
- **WHEN** the dashboard builds its fork manager with the real merger available
- **THEN** the merger holds a child-process runner and the configured probe paths, and no evaluator, scorer or model loader

#### Scenario: Empty probe paths select the bundled sets
- **WHEN** the probe paths are empty
- **THEN** the merge job carries no probe path and the child uses the bundled probe sets

#### Scenario: The fake merger never builds the checks
- **WHEN** `merger_from_name` resolves to `FakeAdapterMerger`
- **THEN** no child-process runner is built and no merge job is ever written
