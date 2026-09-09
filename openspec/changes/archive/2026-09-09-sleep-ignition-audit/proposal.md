## Why

The operator requires that sleep cycles check for ignition events in the thymos workspace that triggered the entity to speak or any other module to act on an input. Ignition in this system is precisely an uninhibited experiential workspace broadcast (`is_experiential == True AND inhibited == False`, syneidesis.py:65-145); the winning coalition is `snapshot["selected"]` (engine.py:802), and realized outcomes are marked by `external_speech`/`internal_speech` (lingua), `vox.synthesized`, `praxis.action`, or `realization_failed`.

Today there is no way to answer, from the research record alone: what ignited this entity during waking, and was any of it caused by external input? Under the base thesis (conversation surface off, transcription off, mundus off) input-triggered ignition must be structurally zero — but nothing proves that invariant. This change adds a per-sleep ignition audit that classifies every realized speech/action since the previous sleep and proves the invariant every cycle.

## What Changes

- Add `kaine/modules/hypnos/ignition_audit.py`: pure functions over event lists computing a THREE-WAY classification of each realized speech/action since the last sleep:
  - **input-triggered**: the intent's `entry_id` resolves to a coalition member whose source/type is an external-input type (`audition.transcription`, `mundus.chat`), or such a type was in the winning coalition of the triggering broadcast;
  - **drive-triggered**: `thymos.drive` in the coalition path;
  - **self-initiated**: neither (the default under `SelfInitiatedReportPolicy`).
- Under the base thesis, the input-triggered count MUST be zero; the audit records it explicitly so every sleep's snapshot proves the invariant.
- Count separately `intent.act` events published on `nous.out` (nous/module.py:171-183): no effector reads `nous.out`, so these are **unrealizable**; they must NOT be counted as executed, but their count is reported as a wiring signal.
- Wire the audit into the Hypnos sleep pipeline, unconditionally on every sleep, following the consolidation-divergence precedent exactly: content-free bus event `hypnos.ignition_audit` on hypnos.out; merged into PhaseResult metadata so it rides `hypnos.sleep.completed` → sleep_snapshots JSONL; carries `sleep_index` for ordering.
- History reading: the audit keeps its own cursors on `volition.out`, `lingua.external`, `lingua.internal`, `praxis.out`, and reads `workspace.broadcast` via bus.subscribe_workspace/xrange with a last_id (NOT bus.range, which cannot decode broadcast entries; client.py:226-267). Bounded window: since the previous sleep (`self._last_sleep_at`).
- Content-free: counts, entry_ids, event types, salience values, sleep_index only. NEVER text, transcripts, latents. Export-eligible research-log data.
- Add a `_TAXONOMY` entry in `kaine/evaluation/observers/research_event_observer.py` with an explicit numeric/categorical allowlist. Hypnos (kaine.modules) must NOT import kaine.evaluation; the taxonomy entry is consumer-side.

## Impact

- **Specs**: `hypnos-consolidation` gains one ADDED requirement ("Sleep-time ignition audit").
- **Code**: new `kaine/modules/hypnos/ignition_audit.py`; `hypnos/module.py` (cursors, pipeline call, bus event, phase metadata); `kaine/evaluation/observers/research_event_observer.py` (taxonomy entry).
- **Docs**: `hypnos.md` (outputs table), `research-event-streams.md`.
- **Invariants proven**: input-triggered ignition is structurally zero under the base thesis, verified every sleep; unrealizable nous intents surface as a distinct wiring signal.

