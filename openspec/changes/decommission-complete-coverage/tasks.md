## 0. Design review (gates all code)

- [x] 0.1 Inventory every location an entity's data can live in (state, data, Redis, Qdrant, sqlite-vec, the append-only file, volumes, backups and preservation bundles) with a decision and reason for each (design.md).
- [x] 0.2 Owner review of the decisions in design.md (decided 2026-10-13, recorded under "Owner decisions" and "Notice to the Guardians").

## 1. Coverage

- [ ] 1.1 One location registry with each location's decision, resolved through the configuration and the rename table.
- [ ] 1.2 Backup completeness: the sqlite-vec store, stage and developmental files, effector files and notifications, voice outcomes and measures, the consolidation record, every snapshot of this entity, merged adapters, the active organ adapter, the raw bus archive and external utterances; a Qdrant export failure is fatal.
- [ ] 1.3 Deletion completeness and scope: identity-filtered fork snapshots, identity, stage, developmental and operational files, content-bearing research records, the organ-adapters and trainer-jobs volumes (after cancelling this entity's running voice-alignment job), the sqlite-vec write-ahead files, a fresh Redis snapshot when snapshots are on.

## 2. Stores and records

- [ ] 2.1 Qdrant reached with the cycle's credentials; an unreachable or refusing store fails before anything is deleted.
- [ ] 2.2 The audit record lists every location by decision.
- [ ] 2.3 The CAL 4.2(a) written-notice reminder (with the CAL 7.0 interim note) before the confirmation on every path; warn only; noted in the audit record.

## 3. Docs and tests

- [ ] 3.1 docs/11-preservation.md and docs/13-security-and-privacy.md state what decommission removes, keeps and backs up, and docs/17-research-data names decommission as the one exception to "never deleted automatically"; the CLI prints the same split before confirmation.
- [ ] 3.2 A seeded tree test: every DELETE location gone, every RETAIN location untouched, every BACKUP location in the bundle, another entity's fork and adapters kept, a refusing Qdrant or Redis fails with nothing deleted, replay records with redaction off and on, the sqlite-vec write-ahead files gone.
- [ ] 3.3 A log test: a seeded utterance never reaches `state/logs/`.
