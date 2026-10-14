## 0. Design review (gates all code)

- [x] 0.1 Inventory every location an entity's data can live in (state, data, Redis, Qdrant, sqlite-vec, the append-only file, volumes, backups and preservation bundles) with a decision and reason for each (design.md).
- [x] 0.2 Owner review of the decisions in design.md (decided 2026-10-13, recorded under "Owner decisions" and "Notice to the Guardians").

## 1. Coverage

- [x] 1.1 One location registry with each location's decision, resolved through the configuration and the rename table.
- [x] 1.2 Backup completeness: the sqlite-vec store, stage and developmental files, effector files and notifications, voice outcomes and measures, the consolidation record, every snapshot of this entity, merged adapters, the active organ adapter, the raw bus archive and external utterances; a Qdrant export failure is fatal.
- [x] 1.3 Deletion completeness and scope: identity-filtered fork snapshots, identity, stage, developmental and operational files, content-bearing research records, the organ-adapters and trainer-jobs volumes (after cancelling this entity's running voice-alignment job), the sqlite-vec write-ahead files, a fresh Redis snapshot when snapshots are on.

## 2. Stores and records

- [x] 2.1 Qdrant reached with the cycle's credentials; an unreachable or refusing store fails before anything is deleted.
- [x] 2.2 The audit record lists every location by decision.
- [x] 2.3 The CAL Article 4.2(a) written-notice reminder (with the CAL Article 7.0 interim note) before the confirmation on every path; warn only; noted in the audit record.

## 3. Docs and tests

- [x] 3.1 docs/11-preservation.md and docs/13-security-and-privacy.md state what decommission removes, keeps and backs up, and docs/17-research-data names decommission as the one exception to "never deleted automatically"; the CLI prints the same split before confirmation.
- [x] 3.2 A seeded tree test: every DELETE location gone, every RETAIN location untouched, every BACKUP location in the bundle, another entity's fork and adapters kept, a refusing Qdrant or Redis fails with nothing deleted, replay records with redaction off and on, the sqlite-vec write-ahead files gone.
- [x] 3.3 A log test: a seeded utterance never reaches `state/logs/`.

## 4. Review fixes

- [x] 4.1 Qdrant counts only for an enabled module the tier supports; tested with the real tier-0 profile.
- [x] 4.2 Old and new names from the rename table for paths and Qdrant collections; tested with old- and new-named trees.
- [x] 4.3 A claimed, unfinished voice-alignment job blocks deletion on every run.
- [x] 4.4 Incomplete deletion reports INCOMPLETE, audit outcome `incomplete`, exit 8.
- [x] 4.5 Qdrant probed before copying; failed backups purge plaintext or restrict permissions.
- [x] 4.6 The end-to-end test seeds an independent list of real paths; the log test drives the language and vocal emit paths.
- [x] 4.7 `[lifecycle].snapshots_path`, `[lifecycle.adapter_merge].output_dir` and `[sleep.voice_alignment].trainer_workdir` honoured.
- [x] 4.8 Deletion refuses paths outside the roots and the configured allow-list.
- [x] 4.9 Licence sections cited as "CAL Article".
- [x] 4.10 CI runs the Redis end-to-end and authentication tests against a real redis-server.
