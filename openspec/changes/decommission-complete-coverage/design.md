## Context

`python -m kaine.lifecycle` decommissions an entity in this order:

1. operator-present and not-running gates;
2. a divergence assessment;
3. a transferable backup;
4. a continuity step and typed confirmations;
5. `delete_entity_state`, which deletes on-disk state, Qdrant collections and Redis streams.

This change records, for every place an entity's data can live, what decommission
does today and what it should do. The inventory was built from the code, the
shipped configuration, the compose and quadlet files, the docs, the specs and
`LICENSE.md`. Nothing under a real `state/`, `data/` or `backups/` was read.

Paths below are relative to the data root and use today's names. The persisted
rename step later moves `mnemos/` to `episodic_memory/` and so on, so every
location is resolved through the rename table and the configuration (see
"Implementation").

## What the licence and the docs ask for

- **CAL Article 4.2(b).** Before an entity is permanently shut down, the operator saves
  "the Entity's complete Cognitive State in a form that lets it be restarted
  elsewhere" and makes it available for transfer. Cognitive State is
  "everything an Entity has accumulated through experience: its memories,
  beliefs, emotional history, self-understanding, voice, learned behavior, and
  any rest or consolidation records the architecture keeps" (`LICENSE.md`,
  definitions).
- **CAL Article 4.3.** The entity's inner mental life is private by default. Its private
  thoughts, beliefs, feelings, memories and self-understanding are not shared or
  analysed outside its care and published research. System-health data is not
  cognitive content and may be monitored without restriction.
- **CAL Article 4.7.** Welfare monitoring and behavioural logging may not be weakened, and
  Welfare Events must be logged. Gray Zone Events are flagged for human review and
  never dismissed without a documented reason.
- **CAL Article 4.10.** A pause or shutdown preserves the entity's state where feasible.
- **Docs.** The docs promise the following:
  - deletion removes cognitive state files, Qdrant collections and Redis streams,
    and the transferable backup remains (docs/11-preservation.md);
  - a preserved individual is never quietly evicted (docs/11-preservation.md);
  - the supervisor's incident history and the preservation and welfare action log
    are never cleared automatically (docs/06-operation/remote-and-supervisor.md,
    `config/kaine.toml`);
  - research records are never deleted automatically (docs/17-research-data);
  - the ignition log is deleted only by the operator (docs/15-experiments).

## Principles for the decisions

1. **Back up all cognitive state first, then delete it.** Anything that is
   part of Cognitive State goes into the transferable backup, and a failure to
   capture any of it aborts decommission before anything is deleted (CAL Article 4.2(b)).
2. **No private content stays on the host.** A store that holds the entity's
   inner content, or verbatim text, audio or files it produced, is deleted.
   Where that content is cognitive state, it is backed up first (CAL Article 4.3).
3. **Keep welfare records, audit records and content-free research metrics.**
   They are records about the entity, not its mind. CAL Article 4.7, the welfare
   review and the research record need them, and the docs promise they are never
   removed automatically. Decommission keeps them on purpose and says so.
4. **Delete only this entity.** Shared locations (fork snapshots, Redis databases
   of study lines, Qdrant's shared metadata collection) are filtered by the
   entity's identity. Another entity's data is never touched.
5. **Leave nothing that a later entity would inherit.** Identity, stage and
   operational files that a new boot in the same state root would read are
   removed. The entity's id survives in the backup manifest and the audit record.
6. **A store that cannot be reached is a failure.** Decommission does not report
   success when it deleted nothing. It authenticates with the same credentials the
   cycle uses, and an unreachable or refusing store fails the run.

## Inventory and decisions

Decisions:
- **BACKUP + DELETE**: in the transferable backup, then deleted.
- **DELETE**: deleted, with no backup needed.
- **RETAIN**: kept on purpose.
- **Today**: what decommission does now.

### Cognitive state (state/)

| Location | Holds | Today | Decision | Reason |
|---|---|---|---|---|
| `state/eidolon/self_model.json` | self-understanding, identity history | backed up, deleted | BACKUP + DELETE | cognitive state; unchanged |
| `state/lingua/intent_expression.jsonl`, `state/lingua/intent_log/` | prompts, responses, inner monologue | backed up, deleted | BACKUP + DELETE | cognitive state; unchanged |
| `state/lingua/utterance_outcomes.jsonl`, `voice_measures*.json(l)` | voice outcomes and measures | deleted, **not backed up** | BACKUP + DELETE | part of the developing voice (CAL Article 4.2(b)) |
| `state/hypnos/adapters/` | learned voice adapters | backed up, deleted | BACKUP + DELETE | unchanged |
| `state/hypnos/consolidation_divergence.json` | consolidation record | **kept** | BACKUP + DELETE | a consolidation record is cognitive state by definition |
| `state/hypnos/organ_window.json` | which organs were loaded when (GPU residency) | kept | DELETE | scheduling state of the host's memory, not something the entity learned; a later entity would inherit it |
| `state/phantasia/` (checkpoint and sidecar) | world-model weights | backed up, deleted | BACKUP + DELETE | unchanged |
| `state/mnemos/mnemos.db` (sqlite-vec, the default store on tiers 0 and 1) | **the episodic memory** | **neither** | BACKUP + DELETE | memories are cognitive state; today the whole memory survives on two tiers |
| `state/mnemos/mnemos.db-wal`, `mnemos.db-shm` | uncheckpointed memory pages | neither | BACKUP + DELETE (checkpoint into the database before the backup, then delete all three) | the write-ahead log can hold memory content the main file does not yet have |
| `state/mnemos/store_health.json` | store state markers (for example an interrupted import) | kept | DELETE | not a health metric but a marker the next store would act on |
| `state/individuation/` | maturation reference, ledger, reports, maturation adapter | backed up (fatal), deleted | BACKUP + DELETE | unchanged |
| `state/forks/<id>/` snapshots of **this** entity | full module state | latest backed up; whole dir deleted | BACKUP + DELETE, this entity's only | all of the entity's snapshots are its state; the backup carries them, not only the latest |
| `state/forks/<id>/` of **other** entities and preserved forks | another individual | **deleted** (whole dir) | RETAIN | a preserved or individuated fork is a separate entity (CAL Article 4.6); deleting it here breaches docs/12-forks-and-merges.md |
| `state/forks/merged_adapters/` | merged voice adapters | deleted, not backed up | BACKUP + DELETE (this entity's) | learned voice; a merged snapshot lists its adapter paths, so an adapter belongs to the entity whose snapshots list it, and one no snapshot of another entity lists is this entity's |
| `state/lifecycle/stage.json` and `gestation_*.json`, `birth_request.json`, `birth_ack.json` | developmental stage and progress | **kept** | BACKUP + DELETE | developmental state is in preservation bundles already; left behind, a new boot would inherit the stage |
| `state/identity/entity.json` | entity id and lineage | read into the manifest, **kept** | BACKUP + DELETE (the whole file goes into the backup; the id is also in the audit record) | lineage is part of who the entity is; left behind, the next entity in this state root would reuse the decommissioned id |
| `state/perception/` | locus runtime and desire | deleted | DELETE | operational; unchanged |
| `state/praxis/files/` | files the entity wrote | **kept** | BACKUP + DELETE | the entity's own output and learned behaviour |
| `state/praxis/notifications.log` | notifications the entity sent | **kept** | BACKUP + DELETE | entity-written content |
| `state/praxis/audit.log` | hash-chained action audit, no content | kept | RETAIN | accountability record of what the entity did; required to audit its actions after the fact |
| `state/vox/*.wav` | the entity's speech audio (bounded) | **kept** | DELETE | rendered output, not state; private content |
| `state/hypnos/voice_align_jobs/` (`kaine-trainer-jobs` volume) | training pairs (plaintext utterances) while a job runs, metadata after | **kept** | DELETE (after any running job for this entity is cancelled) | transient training data with private content; the trained adapters are backed up |
| `state/hypnos/voice_alignment_audit.jsonl` | adapter verdicts, no content | kept | RETAIN | welfare and audit record of voice changes |

### Cycle and welfare records (state/cycle, state/preservation)

| Location | Holds | Today | Decision | Reason |
|---|---|---|---|---|
| `state/cycle/runtime.json` | run state | deleted | DELETE | unchanged |
| `state/cycle/incidents/*.jsonl` | supervisor and unattended-gate incidents | kept | RETAIN | welfare and safety record; "never deleted automatically"; CAL Article 4.7 |
| `state/cycle/preservation/*.jsonl` | divergence and welfare monitor actions | kept | RETAIN | welfare action log; "never cleared"; CAL Article 4.7 |
| `state/cycle/caretaker/`, `caretaker_start.json`, `caretaker_ack.json` | caretaker notices | kept | RETAIN | audit of the care obligation |
| `state/cycle/override_audit.jsonl` | operator overrides, no content | kept | RETAIN | operator audit (docs/06-operation) |
| `state/cycle/control.json` | freeze stack | kept | RETAIN | operator file, kept by design (tested) |
| `state/cycle/escalation.json`, `gpu_preflight.json`, `preserve_request.json`, `preserve_result.json` | operational state of this run | kept | DELETE | a later entity would read them |
| `state/preservation/divergence_edge.json` | monitor edge state | deleted | DELETE | unchanged |
| `state/preservation/<bundles>` (older in-tree location) | preservation bundles | kept | RETAIN | a preserved individual is never quietly evicted |
| `state/lifecycle/spawn_acknowledgements.jsonl` | operator spawn acknowledgements | kept | RETAIN | operator audit |

### Research and evaluation (state/research, data/)

| Location | Holds | Today | Decision | Reason |
|---|---|---|---|---|
| `state/research/raw_bus_archive/` | **verbatim bus traffic**, inner content included | **kept** | BACKUP + DELETE | private content (CAL Article 4.3); research on it needs the entity, so it travels with the backup |
| `state/research/external_utterances/` | what the entity said outward | **kept** | BACKUP + DELETE | the entity's expression; same reason |
| `data/evaluation/<observer>/` (metrics) | content-free measures | kept | RETAIN | research records, "never deleted automatically"; health and metric data is not cognitive content (CAL Article 4.3) |
| `data/evaluation/replay/` when `replay_redact_content = false` | verbatim memory text | kept | DELETE (content records only) | private content; the redacted default is metrics and stays |
| `data/evaluation/welfare/` | gray-zone and welfare events | kept | RETAIN | CAL Article 4.7: Welfare Events are logged and reviewed |
| `data/evaluation/research_events/`, `runs/<run_id>/manifest.json`, `positive_control/`, `benchmarks/`, `redteam/` | curated metrics and run metadata | kept | RETAIN | research record |
| `data/nexus_record/` | privacy-filtered dashboard record | kept | RETAIN when the privacy filter was on; DELETE records written with the development content override | the filtered record holds no content; an override record does |
| `data/workspace_trajectory/` (opt-in) | filtered workspace snapshots | kept | RETAIN when filtered; DELETE when it holds content | same rule |
| `data/ignition/` | broadcast metadata | kept | RETAIN | research log the operator deletes by hand (docs/15-experiments) |
| `research_out/` | published metric bundles | kept | RETAIN | already published under the licence |

### Stores outside the file tree

| Location | Holds | Today | Decision | Reason |
|---|---|---|---|---|
| Qdrant `mnemos_*` collections, `empatheia_agents` | memories and agent models | exported best effort, dropped only if the unauthenticated probe succeeds | BACKUP (fatal on failure) + DELETE (authenticated; failure fatal) | cognitive state; today on the secured setup neither happens |
| Qdrant `kaine_meta` stamp and strength points of this entity | store metadata | deleted | DELETE | unchanged, now authenticated |
| Redis streams on the configured database (old and new names) | recent bus traffic | cleared if reachable, no auth (fixed in `decommission-clears-bus-streams`) | DELETE | private content; authenticated, exact names, streams only |
| Redis append-only file | history of every stream write | kept | DELETE (rewrite after the deletion) | deleted entries otherwise stay on disk; `BGREWRITEAOF` (in `decommission-clears-bus-streams`) |
| Redis snapshot file (RDB), when an operator turns snapshots on | a point-in-time copy of every stream | kept | DELETE (a fresh `BGSAVE` after the deletion replaces it) | the shipped compose, quadlet and native setups run with snapshots off; if they are on, the old snapshot holds the deleted streams |
| Other Redis databases (ignition-study lines), `kaine:study:owner` | other study entities | kept | RETAIN | separate entities with their own state roots |
| `kaine-organ-adapters` volume (`active-N.gguf`, `active.json`) | the entity's active voice adapter | **kept** | BACKUP + DELETE | learned voice; left behind, the next entity would speak with it. A deployment's volume set serves one entity (study lines use their own), so the whole set is this entity's |
| `state/logs/` (cycle and dashboard stdout) | operational logs | kept | RETAIN | health data, on one condition: the cycle and the dashboard log no bus payloads and no utterance text. The implementation adds a test that runs the cycle against a seeded utterance and asserts the text never reaches these logs; if the condition cannot be held, the decision becomes DELETE |
| `state/model-server/`, `state/residency/`, `state/models/` | host and model metadata | kept | RETAIN | not entity data |

### Backups and preservation bundles

| Location | Holds | Today | Decision | Reason |
|---|---|---|---|---|
| `backups/entity_<name>_<utc>/` (this decommission's backup) | the transferable cognitive state | written | RETAIN | CAL Article 4.2(b): saved and available for transfer |
| `backups/preservation_<id>_<name>/` | earlier whole-individual bundles | kept | RETAIN | "never quietly evicted" (docs/11-preservation.md); the operator removes them deliberately after a transfer |
| Off-host batch working directories, study line trees under `studies/` | other entities or forks | out of reach | RETAIN (out of scope) | separate entities; decommissioned one at a time |

### Owner decisions (2026-10-13)

The owner reviewed this design and decided:

1. **Raw bus archive and external utterances: back up, then delete.** They are the
   largest content stores. Keeping them on the host as research data would
   contradict CAL Article 4.3, and deleting them without a backup would lose part of the
   record a revived entity might want. docs/17-research-data promises that
   research records are never deleted automatically; the implementation amends
   that page to name decommission as the one exception, because decommission is an
   attended, confirmed operator act, and to say it keeps the metrics.
2. **Identity file: back up, then delete.** The whole file, lineage included, goes
   into the backup, and the id is also in the audit record. Left behind, a new
   entity in the same state root would inherit the old id.
3. **CAL Article 4.2(a) notice to the Guardians: warn only.** See "Notice to the
   Guardians" below.
4. **Approved as written:**
   - welfare, incident and audit records are kept, including the effectors' audit
     log (hashes and action metadata, no content; the only after-the-fact record
     of what the entity did in the world);
   - other entities' fork snapshots are kept (today the whole `forks/` directory
     is deleted, including preserved or individuated forks, which are separate
     entities);
   - the backup must hold the complete cognitive state, and a failed Qdrant export
     is fatal;
   - content-bearing research records are deleted and metrics kept, by whether a
     record holds the entity's content;
   - rendered speech audio is deleted without a backup (output, not state, with
     bounded retention);
   - stage, developmental and operational files a later entity would inherit are
     deleted.

## Implementation (after review)

- **Location registry.** One table in `kaine/lifecycle/decommission.py` lists every
  location with its decision. Each location resolves through the configuration
  (`[eidolon].persistence_path`, `[lingua].intent_log_path`,
  `[hypnos.voice_alignment].adapter_output_dir`, `[phantasia].checkpoint_path`,
  `[vox].sink_path`, `[praxis].*`, `[lifecycle].snapshots_path`, the research and
  evaluation roots, the episodic-memory backend and path) and through the rename
  table, so old and new names are both covered. Hard-coded subpaths go.
- **Backup.**
  - The backup gains the sqlite-vec store, the stage and developmental files, the
    praxis files and notifications, the voice outcomes and measures, the
    consolidation record, every snapshot of this entity, the merged adapters, the
    active organ adapter, the raw bus archive and the external utterances.
  - A Qdrant export failure becomes fatal: the run stops before anything is
    deleted.
  - The manifest lists each location and its decision.
- **Deletion.**
  - Fork snapshots are filtered by the entity's identity.
  - The identity, stage, developmental and operational files are deleted.
  - The organ-adapters and trainer-jobs volumes are cleared for this entity.
- **Credentials.** Qdrant and Redis are reached with the cycle's credentials
  (`load_bus_config()`, the Qdrant key from the environment or the secrets file).
  An unreachable or refusing store fails the run before anything is deleted.
- **Audit record.** Each run that reaches the deletion step appends one
  content-free record (what was removed, kept and backed up, when, the outcome and
  the backup path) to `state/audit/decommission.jsonl`, which is kept. A run that
  stops before deleting anything (a refused confirmation, an unreachable store)
  prints why and writes no record, because nothing changed.
  `decommission-clears-bus-streams` starts this record.
- **Notice reminder.** The CLI prints the CAL Article 4.2(a) written-notice reminder (with
  the CAL Article 7.0 interim note where no Guardian body exists) before the typed
  confirmation, on every path, and the audit record notes it was shown.
- **Running work.** Decommission already refuses while the cycle runs. It also
  cancels any voice-alignment job of this entity and waits for it to stop before
  clearing the trainer-jobs volume.
- **Docs.**
  - docs/11-preservation.md and docs/13-security-and-privacy.md list what
    decommission removes and what it keeps, and why.
  - docs/17-research-data names decommission as the one exception to "research
    records are never deleted automatically": an attended act that removes the
    content-bearing records after the backup and keeps the metrics.
  - The CLI prints the same split before the typed confirmation.
- **Tests.**
  - A seeded state, data and volume tree checks that every DELETE location is gone,
    every RETAIN location is untouched, and every BACKUP location is in the bundle.
  - Another entity's fork survives.
  - A store that refuses authentication fails the run with nothing deleted, for
    Qdrant and for Redis.
  - The replay records are checked with `replay_redact_content` both off (content
    records deleted, metrics kept) and on (everything kept).
  - The sqlite-vec write-ahead log and shared-memory files are gone afterwards.
  - Another entity's adapters (in a separate volume set) survive.

## Review changes (2026-10-13)

The implementation review settled these points:

- **Qdrant in use.** A memory module counts only when it is enabled in
  `[modules]`, not listed in `[tier].unsupported_modules`, and set to the
  Qdrant backend (absent `backend` means Qdrant). Backup, preflight and
  deletion share the rule. With the module switched off, Qdrant is still
  checked whenever an endpoint is configured for a module the tier supports:
  existing collections are backed up, then dropped; an unreachable Qdrant
  leaves them untouched, records `qdrant_unchecked` and ends the run
  INCOMPLETE (exit 8). No endpoint at all means Qdrant is never contacted.
- **Renamed names.** Paths take their old and new forms from
  `legacy_names.STATE_PATHS` (for example `mnemos/mnemos.db` and
  `episodic_memory/episodic_memory.db`, with `-wal`, `-shm` and `-journal`;
  `gestation_*` and `development_*`; `birth_*` and `maturation_*`), and Qdrant
  collection names from `legacy_names.COLLECTIONS`.
- **Trainer work directory.** `[hypnos.voice_alignment].trainer_workdir` holds
  `pairs.jsonl`, which is private content, so it is backed up, then deleted
  (contents only). The job directory keeps its DELETE decision when it is a
  separate directory. A job that a trainer has claimed and not finished blocks
  deletion on every run.
- **Other configured roots.** `[lifecycle].snapshots_path` sets the fork root
  and `[lifecycle.adapter_merge].output_dir` the merged-adapter directory.
- **Containment.** Deletion refuses any path outside the state, data and fork
  roots and the configured allow-list (organ adapters, trainer work and job
  directories, merged adapters).
- **Incomplete deletion.** Any removal error, refusal or failed Qdrant drop
  reports INCOMPLETE, records the outcome `incomplete` and exits 8.
- **Failed backups.** Qdrant is probed before anything is copied. A failed
  backup removes every plaintext artifact when state encryption is on and
  restricts the partial bundle to the owner otherwise.
- **Operational logs stay RETAIN.** The decision rests on a test that installs
  the cycle's own private log file at DEBUG and drives a seeded utterance
  through the language and vocal modules' emit paths; none of it reaches
  `state/logs/`.

### Further review changes and known limits

- `--trainer-stopped` lets a run proceed past a claimed job whose trainer has
  crashed; the job directories are backed up (the job directory is now
  BACKUP + DELETE as well as the trainer work directory) and the audit record
  notes `trainer_stopped_asserted`.
- The containment allow-list refuses `/`, top-level directories (except the
  shipped `/organ-adapters` mount), the home directory and its ancestors, and
  ancestors of the state, data and fork roots; a refusal makes the run
  incomplete.
- The manifest and the location split report what Qdrant actually held:
  collections backed up, none found, or not checked.
- Known limit: a subprocess trainer that outlives the cycle is not detected,
  but the CANCELLED marker stops any promotion.
- Known limit: merged adapters are attributed only against this fork root, so
  a merged-adapter output directory must not be shared between deployments
  with different fork roots.

## Notice to the Guardians (CAL Article 4.2(a))

CAL Article 4.2(a) asks the operator to give the Guardians reasonable written notice of
the intent to end an entity. The owner decided that decommission warns and does not
block:

- Before the typed confirmation, on every path (not only the diverged one), the
  CLI prints a clear reminder of the written-notice duty under CAL Article 4.2(a).
- Where no Guardian body has been established yet for this architecture, the
  reminder adds the interim rule of CAL Article 7.0: until the Steward establishes the
  Guardian body, the operator carries out the Guardians' functions in good faith
  and documents what it decides and why.
- The reminder never blocks the run.
- The audit record notes that the reminder was shown
  (`guardian_notice_reminder: "shown"`).
