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

- **CAL 4.2(b).** Before an entity is permanently shut down, the operator saves
  "the Entity's complete Cognitive State in a form that lets it be restarted
  elsewhere" and makes it available for transfer. Cognitive State is
  "everything an Entity has accumulated through experience: its memories,
  beliefs, emotional history, self-understanding, voice, learned behavior, and
  any rest or consolidation records the architecture keeps" (`LICENSE.md`,
  definitions).
- **CAL 4.3.** The entity's inner mental life is private by default. Its private
  thoughts, beliefs, feelings, memories and self-understanding are not shared or
  analysed outside its care and published research. System-health data is not
  cognitive content and may be monitored without restriction.
- **CAL 4.7.** Welfare monitoring and behavioural logging may not be weakened, and
  Welfare Events must be logged. Gray Zone Events are flagged for human review and
  never dismissed without a documented reason.
- **CAL 4.10.** A pause or shutdown preserves the entity's state where feasible.
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
   capture any of it aborts decommission before anything is deleted (CAL 4.2(b)).
2. **No private content stays on the host.** A store that holds the entity's
   inner content, or verbatim text, audio or files it produced, is deleted.
   Where that content is cognitive state, it is backed up first (CAL 4.3).
3. **Keep welfare records, audit records and content-free research metrics.**
   They are records about the entity, not its mind. CAL 4.7, the welfare
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
| `state/lingua/utterance_outcomes.jsonl`, `voice_measures*.json(l)` | voice outcomes and measures | deleted, **not backed up** | BACKUP + DELETE | part of the developing voice (CAL 4.2(b)) |
| `state/hypnos/adapters/` | learned voice adapters | backed up, deleted | BACKUP + DELETE | unchanged |
| `state/hypnos/consolidation_divergence.json` | consolidation record | **kept** | BACKUP + DELETE | a consolidation record is cognitive state by definition |
| `state/hypnos/organ_window.json` | organ residency window | kept | DELETE | operational state a later entity would inherit |
| `state/phantasia/` (checkpoint and sidecar) | world-model weights | backed up, deleted | BACKUP + DELETE | unchanged |
| `state/mnemos/mnemos.db` (sqlite-vec, the default store on tiers 0 and 1) | **the episodic memory** | **neither** | BACKUP + DELETE | memories are cognitive state; today the whole memory survives on two tiers |
| `state/mnemos/store_health.json` | store health | kept | DELETE | this entity's store metadata |
| `state/individuation/` | maturation reference, ledger, reports, maturation adapter | backed up (fatal), deleted | BACKUP + DELETE | unchanged |
| `state/forks/<id>/` snapshots of **this** entity | full module state | latest backed up; whole dir deleted | BACKUP + DELETE, this entity's only | all of the entity's snapshots are its state; the backup carries them, not only the latest |
| `state/forks/<id>/` of **other** entities and preserved forks | another individual | **deleted** (whole dir) | RETAIN | a preserved or individuated fork is a separate entity (CAL 4.6); deleting it here breaches docs/12-forks-and-merges.md |
| `state/forks/merged_adapters/` | merged voice adapters | deleted, not backed up | BACKUP + DELETE (this entity's) | learned voice |
| `state/lifecycle/stage.json` and `gestation_*.json`, `birth_request.json`, `birth_ack.json` | developmental stage and progress | **kept** | BACKUP + DELETE | developmental state is in preservation bundles already; left behind, a new boot would inherit the stage |
| `state/identity/entity.json` | entity id and lineage | read into the manifest, **kept** | DELETE (id kept in the backup manifest and the audit record) | left behind, the next entity in this state root would reuse the decommissioned id |
| `state/perception/` | locus runtime and desire | deleted | DELETE | operational; unchanged |
| `state/praxis/files/` | files the entity wrote | **kept** | BACKUP + DELETE | the entity's own output and learned behaviour |
| `state/praxis/notifications.log` | notifications the entity sent | **kept** | BACKUP + DELETE | entity-written content |
| `state/praxis/audit.log` | hash-chained action audit, no content | kept | RETAIN | accountability record of what the entity did; required to audit its actions after the fact |
| `state/vox/*.wav` | the entity's speech audio (bounded) | **kept** | DELETE | rendered output, not state; private content |
| `state/hypnos/voice_align_jobs/` (`kaine-trainer-jobs` volume) | training pairs (plaintext utterances) while a job runs, metadata after | **kept** | DELETE | transient training data with private content; the trained adapters are backed up |
| `state/hypnos/voice_alignment_audit.jsonl` | adapter verdicts, no content | kept | RETAIN | welfare and audit record of voice changes |

### Cycle and welfare records (state/cycle, state/preservation)

| Location | Holds | Today | Decision | Reason |
|---|---|---|---|---|
| `state/cycle/runtime.json` | run state | deleted | DELETE | unchanged |
| `state/cycle/incidents/*.jsonl` | supervisor and unattended-gate incidents | kept | RETAIN | welfare and safety record; "never deleted automatically"; CAL 4.7 |
| `state/cycle/preservation/*.jsonl` | divergence and welfare monitor actions | kept | RETAIN | welfare action log; "never cleared"; CAL 4.7 |
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
| `state/research/raw_bus_archive/` | **verbatim bus traffic**, inner content included | **kept** | BACKUP + DELETE | private content (CAL 4.3); research on it needs the entity, so it travels with the backup |
| `state/research/external_utterances/` | what the entity said outward | **kept** | BACKUP + DELETE | the entity's expression; same reason |
| `data/evaluation/<observer>/` (metrics) | content-free measures | kept | RETAIN | research records, "never deleted automatically"; health and metric data is not cognitive content (CAL 4.3) |
| `data/evaluation/replay/` when `replay_redact_content = false` | verbatim memory text | kept | DELETE (content records only) | private content; the redacted default is metrics and stays |
| `data/evaluation/welfare/` | gray-zone and welfare events | kept | RETAIN | CAL 4.7: Welfare Events are logged and reviewed |
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
| Other Redis databases (ignition-study lines), `kaine:study:owner` | other study entities | kept | RETAIN | separate entities with their own state roots |
| `kaine-organ-adapters` volume (`active-N.gguf`, `active.json`) | the entity's active voice adapter | **kept** | BACKUP + DELETE | learned voice; left behind, the next entity would speak with it |
| `state/logs/` (cycle and dashboard stdout) | operational logs | kept | RETAIN | health data; logs carry no content by policy (to be verified by the implementation's test) |
| `state/model-server/`, `state/residency/`, `state/models/` | host and model metadata | kept | RETAIN | not entity data |

### Backups and preservation bundles

| Location | Holds | Today | Decision | Reason |
|---|---|---|---|---|
| `backups/entity_<name>_<utc>/` (this decommission's backup) | the transferable cognitive state | written | RETAIN | CAL 4.2(b): saved and available for transfer |
| `backups/preservation_<id>_<name>/` | earlier whole-individual bundles | kept | RETAIN | "never quietly evicted" (docs/11-preservation.md); the operator removes them deliberately after a transfer |
| Off-host batch working directories, study line trees under `studies/` | other entities or forks | out of reach | RETAIN (out of scope) | separate entities; decommissioned one at a time |

### Decisions the owner should confirm

1. **Raw bus archive and external utterances go with the entity.** They are the
   largest content stores. Keeping them on the host as research data would
   contradict CAL 4.3, and deleting them without a backup would lose part of the
   record a revived entity might want. The design backs them up and deletes them.
2. **The effectors' audit log stays.** It holds hashes and action metadata, no
   content, and it is the only after-the-fact record of what the entity did in the
   world.
3. **Identity and stage files are deleted.** Today they survive, and a new entity
   in the same state root would inherit the old id. The id stays in the backup
   manifest and the audit record.
4. **Other entities' fork snapshots stay.** Today the whole `forks/` directory is
   deleted, including preserved or individuated forks. They are separate entities.
5. **Content-bearing research records are deleted, metrics stay.** The test is
   whether a record holds the entity's content. Metrics, welfare flags and run
   metadata stay; verbatim text, audio and files go (after backup when they are
   cognitive state).
6. **Rendered speech audio is deleted without a backup.** It is output, not state,
   and its retention is already bounded.

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
- **Audit record.** Each run appends one content-free record (what was removed,
  kept and backed up, when, the outcome and the backup path) to
  `state/audit/decommission.jsonl`, which is kept. `decommission-clears-bus-streams`
  starts this record.
- **Docs.**
  - docs/11-preservation.md and docs/13-security-and-privacy.md list what
    decommission removes and what it keeps, and why.
  - The CLI prints the same split before the typed confirmation.
- **Tests.**
  - A seeded state, data and volume tree checks that every DELETE location is gone,
    every RETAIN location is untouched, and every BACKUP location is in the bundle.
  - Another entity's fork survives.
  - A store that refuses authentication fails the run with nothing deleted.

## Open question outside the data inventory

CAL 4.2(a) asks for written notice to the Guardians before an entity is ended.
The CLI offers a transfer e-mail only on the diverged path. Whether the CLI should
require a notice for every decommission is a process decision for the owner and
is not part of this inventory.
