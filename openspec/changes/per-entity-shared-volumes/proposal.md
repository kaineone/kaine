# Proposal

## Why

In the shipped compose deployment the main cycle and the study runner mount the same `kaine-organ-adapters` and `kaine-trainer-jobs` volumes, and both write into the volume root. Nothing in the layout says which entity a file belongs to, so decommission (decommission-complete-coverage) can only attribute an entry by matching checksums or recorded adapter paths, and has to keep whatever it cannot attribute. Unfinished job-queue jobs of the entity being ended, which hold its training pairs, can stay behind. Writing each entity's files under its own subdirectory makes ownership structural.

## What Changes

- Promoted GGUF adapters go to `<organ_adapters_dir>/<entity_id>/active-N.gguf`, with that entity's manifest at `<entity_id>/active.json`.
- The volume-root `active.json` becomes a pointer to the entity whose adapter the organ loads. The organ launcher follows it and checks that the target stays inside the volume.
- Voice-alignment jobs go to `<trainer_jobs_dir>/<entity_id>/<job_id>/`, and `job.json` records `entity_id`. The trainer service looks for ready jobs one level deeper.
- Decommission treats `<entity_id>/` in both volumes as wholly this entity's: it is backed up, then deleted. The checksum attribution stays only for legacy entries in the volume root.
- Existing flat files stay readable. The launcher and the trainer service accept the legacy layout until the next release that drops it, and nothing is moved automatically.

## Capabilities

### New Capabilities

### Modified Capabilities
- `voice-alignment`: adapters and jobs in the shared volumes live under the owning entity's id.
- `entity-decommission`: in shared volumes, decommission deletes the entity's own subdirectory and keeps the rest.

## Impact

- `kaine/modules/sleep/organ_adapter.py` (activation and manifest), `docker/organ-launcher.sh` (manifest pointer), `kaine/modules/sleep/job_queue_trainer.py` and `kaine/modules/sleep/trainer_service.py` (job layout).
- `kaine/lifecycle/decommission_locations.py` (ownership by subdirectory).
- `compose/kaine.yml` comments and docs/11-preservation.md.
- No new dependencies. The entity id comes from `state/identity/entity.json`, which every entity already has.
