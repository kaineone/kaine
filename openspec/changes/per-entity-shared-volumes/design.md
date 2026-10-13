# Design

## Context

decommission-complete-coverage scopes the shared volumes by attribution: an organ file belongs to an entity when its checksum matches an adapter in the entity's adapter store, and a job when its `job.json` names the entity's adapter store or it holds one of the entity's adapters. Job-queue jobs record `"adapter_output_dir": "out"`, so an unfinished job of the entity cannot be attributed and is kept. The organ launcher (`docker/organ-launcher.sh`) reads one `active.json` at the volume root and loads the file it names. The trainer service scans the jobs directory root for `READY` jobs.

## Goals / Non-Goals

**Goals:**
- Every file an entity writes into a shared volume sits under `<entity_id>/`, so ownership needs no inference.
- The organ, the trainer service and decommission all work with both the new and the legacy layout during the transition.

**Non-Goals:**
- Moving existing flat files into subdirectories. They stay where they are and age out as new generations are promoted.
- Running several adapters in the organ at once. The organ still loads one adapter, the one the pointer names.

## Decisions

- **Subdirectory named by entity id, not by name.** Names can repeat and change; `entity_id` from `state/identity/entity.json` cannot. Alternative considered: one volume per entity in compose. Rejected because the study runner creates lines dynamically and the organ container would need every line's volume mounted.
- **Volume-root pointer for the organ.** The root `active.json` becomes `{"entity_id", "file": "<entity_id>/active-N.gguf", "sha256", "generation"}`. The launcher resolves the file, refuses anything outside the volume, and checks the checksum as today. Alternative considered: configure the entity id in the launcher environment. Rejected because the study runner switches which entity speaks without restarting the organ.
- **Jobs record their owner twice.** By directory (`<entity_id>/<job_id>/`) and in `job.json` (`entity_id`), so a job copied elsewhere is still attributable. The trainer service scans `<trainer_jobs_dir>/*/` as well as the root.
- **Decommission prefers the subdirectory.** `<entity_id>/` in each volume is BACKUP + DELETE whole. Root-level entries keep the checksum attribution from decommission-complete-coverage and are kept when they cannot be attributed.

## Risks / Trade-offs

- [The pointer and an entity manifest disagree after a crash between writes] → Write the entity manifest first and the pointer last, both atomically, as activation does today; the launcher trusts only the pointer plus the checksum.
- [Pruning old generations per entity grows the volume with many study lines] → Pruning stays per entity (current and previous generation), so the volume grows linearly with live entities only.
- [A legacy root-level job of the ended entity is still unattributable] → It is kept and listed, as today, until the trainer service has drained root-level jobs. The release notes say to let running jobs finish before upgrading.

## Migration Plan

1. Ship the launcher and trainer-service changes that read both layouts.
2. Switch activation and job writing to the subdirectory layout.
3. Decommission treats subdirectories as owned and keeps the legacy attribution for the root.
4. A later release removes legacy reading once no deployment has root-level files left. Rollback: the old launcher still reads a legacy `active.json`, so reverting step 2 is enough.
