# Tasks

## 1. Organ adapters

- [ ] 1.1 Activation writes `<volume>/<entity_id>/active-N.gguf` and `<entity_id>/active.json`, then the volume-root pointer; verify with a unit test that two entities activating into one volume keep separate files.
- [ ] 1.2 The organ launcher follows the pointer, refuses a target outside the volume, and still reads a legacy root manifest; verify with launcher tests for the new layout, the legacy layout and an escaping pointer.

## 2. Voice-alignment jobs

- [ ] 2.1 Job-queue and subprocess jobs are written to `<trainer_jobs_dir>/<entity_id>/<job_id>/` with `entity_id` in `job.json`; verify with a unit test of the job layout.
- [ ] 2.2 The trainer service claims ready jobs under entity subdirectories and at the root; verify with a trainer-service test covering both.

## 3. Decommission

- [ ] 3.1 The registry treats `<entity_id>/` in both volumes as BACKUP + DELETE and keeps the checksum attribution for root-level entries; verify with a test where a study line's subdirectory survives and an unfinished job of the entity is backed up and deleted.
- [ ] 3.2 docs/11-preservation.md and the compose comments describe the layout; verify by reading the rendered docs page.
