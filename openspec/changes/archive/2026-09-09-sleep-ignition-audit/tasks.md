## Phase 1 — Audit core (pure functions)

- [x] 1.1 Create `kaine/modules/hypnos/ignition_audit.py` with pure functions over event lists (no bus dependency): classification of realized volition intents into input-triggered / drive-triggered / self-initiated using entry_id → coalition member resolution and broadcast coalition membership
- [x] 1.2 Encode external-input types as constants: `audition.transcription`, `mundus.chat`; drive type `thymos.drive`
- [x] 1.3 Handle realization markers: `external_speech` (lingua.external), `internal_speech` (lingua.internal), `vox.synthesized` (vox.out), `praxis.action` (praxis.out); exclude `realization_failed`
- [x] 1.4 Count `intent.act` on `nous.out` separately as unrealizable (never counted as executed)
- [x] 1.5 Build the content-free payload: counts, entry_ids, event types, salience values, sleep_index only

## Phase 2 — Hypnos wiring

- [x] 2.1 Add per-stream cursors in hypnos/module.py for `volition.out`, `lingua.external`, `lingua.internal`, `praxis.out` following the persisted-cursor read pattern of `_soma_consumer_loop` (module.py:202-263)
- [x] 2.2 Read `workspace.broadcast` via bus.subscribe_workspace/xrange with last_id (NOT bus.range — it cannot decode broadcast entries; client.py:226-267)
- [x] 2.3 Bound the window to since `self._last_sleep_at` (module.py:161)
- [x] 2.4 Call the audit unconditionally in the sleep pipeline, following `_emit_consolidation_divergence` precedent exactly: content-free `hypnos.ignition_audit` on hypnos.out, merged into PhaseResult metadata, carrying sleep_index
- [x] 2.5 Verify hypnos does not import kaine.evaluation (module boundary)

## Phase 3 — Research-event taxonomy

- [x] 3.1 Add a `_TAXONOMY` entry for `hypnos.ignition_audit` in `kaine/evaluation/observers/research_event_observer.py` with an explicit numeric/categorical allowlist (counts, entry_ids, event types, salience values, sleep_index)
- [x] 3.2 Add a registry note if the observer requires registration of new event types

## Phase 4 — Tests

- [x] 4.1 Classification fixture tests using the REAL payload shapes: realized speak self-initiated; drive-triggered via `thymos.drive` in coalition; input-triggered via `audition.transcription` entry and via coalition membership of `mundus.chat`
- [x] 4.2 Base-thesis invariant test: input-triggered count is zero with conversation surface, transcription, and mundus off
- [x] 4.3 Unrealizable nous test: `intent.act` on `nous.out` counted separately, not as executed
- [x] 4.4 Content-free allowlist test: payload contains only allowlisted keys; rejects/omits any text, transcript, or latent field
- [x] 4.5 Pipeline test: audit runs every sleep, `hypnos.ignition_audit` emitted, PhaseResult metadata rides `hypnos.sleep.completed` into sleep_snapshots JSONL with sleep_index ordering

## Phase 5 — Docs

- [x] 5.1 Update hypnos.md outputs table with `hypnos.ignition_audit` and its persisted metadata fields
- [x] 5.2 Document `hypnos.ignition_audit` in research-event-streams.md (content-free, export-eligible, three-way classification, unrealizable nous count)

