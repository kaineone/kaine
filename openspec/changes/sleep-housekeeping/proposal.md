## Why

The tenth test boot wrote about 1.7 GB of research event log a day, and nothing removed it: `retention_days = 0` keeps research records forever, so a long run fills the disk the entity runs on. The paper (predictive-workspace-paper #49, section 3.5 and A.5 "Housekeeping", Table A1) now makes this part of sleep. Every sleep, last before the affective reset, runs housekeeping: oldest data first, it brings the bytes on each resource (disk, host memory) of regenerable or spent data and unexported study records within a per-resource budget `B^hk_j`, moving study records to an archive volume the operator mounts, and stops when that is done or when `Delta_hk` has passed. An excess left over, or left by an aborted sleep, carries over. The pressure `P^hk_t = sum_j max(0, S^hk_j / B^hk_j - 1) + max(0, S/B - 1)`, the last term the episodic stores' excess over their budget (A.10), is an interoceptive input to fatigue. Housekeeping never touches the memory stores, the world model, the self-model and identity, voice adapters or preservations.

## What Changes

- New `kaine/modules/sleep/housekeeping.py`. It accounts the study records under the allowed roots (`data/evaluation`, which holds the research event log and the evaluation sinks, and `data/workspace_trajectory`, the broadcast log) and, when the operator has set `archive_dir`, moves closed daily files there oldest first, each copied and checked before the local file is removed, until the disk bytes are within `disk_budget_bytes` or `time_allowance_s` has passed. Host memory is accounted as the bus's memory use against `memory_budget_bytes`. The report carries the bytes before and after, the files and bytes moved, why it stopped, and the pressure `P^hk`, whose episodic term uses the stores' bytes from the same sleep's downscaling and `[episodic_memory].storage_budget_bytes` (0 without the module).
- Housekeeping acts only on regular files inside the allowed roots. Anything else, a symlink, a path that resolves outside, or a path under `state/` (the memory stores, world model, self-model, identity, voice adapters and preservations live there), is refused with an error, and the archive directory may not lie inside an allowed root or under `state/`.
- The sleep module runs housekeeping at the end of the pipeline, after the voice and corpus work and before the affective reset, and adds its report to the `sleep.sleep.completed` summary under `housekeeping`. A failure is logged and never stops the sleep. An aborted sleep skips it, so the excess stays and the next sleep meets it.
- New `[sleep.housekeeping]` table: `enabled = true`, `disk_budget_bytes`, `memory_budget_bytes`, `time_allowance_s`, `archive_dir` (empty: no archive mounted, nothing is moved). The research event log's `retention_days = 0` stays; its files come under the disk budget and are moved to the archive before they leave the host.

## Not in this change

The paper leaves these open, so they are reported to the lead instead of built:
- The weight with which fatigue integrates `P^hk_t` beside `nu^act_t`. The pressure is computed and reported; it does not yet reach fatigue.
- The awake floor: where it runs, which recorders "study recording" covers, and when recording resumes.
- Which concrete files are regenerable or spent on disk (runtime logs, caches, rotated archives), and which bus entries are spent in memory below the streams' count caps. Only study records are reclaimed, and the bus keeps its count trimming.
- The floor's free-space reserve.

## Capabilities

### Modified Capabilities

- `sleep`: every sleep runs housekeeping last before the affective reset.

## Impact

- New `kaine/modules/sleep/housekeeping.py`; `kaine/modules/sleep/module.py`, `kaine/boot/factories/sleep.py`, `config/kaine.toml`, `docs/09-modules/sleep.md`, `docs/appendix-a-configuration/perception-and-sleep.md`, new tests.
- Behaviour: with no archive directory set (the shipped default) housekeeping only measures. With one set, closed study-record files leave the host's data tree for the archive, oldest first, once the disk budget is exceeded. Nothing under `state/` is touched.
