<!-- change sleep-ignition-audit -->

## Outputs — hypnos.ignition_audit (sleep-time ignition audit)

| Event | Stream | Content | Persisted |
| --- | --- | --- | --- |
| `hypnos.ignition_audit` | `hypnos.out` | Content-free counts, entry_ids, event types, salience values, `sleep_index` | Merged into the PhaseResult metadata, riding `hypnos.sleep.completed` into the sleep_snapshots JSONL |

Unconditional on every sleep, the audit covers the window since the previous
sleep (`_last_sleep_at`) and classifies each realized speech/action (intents
on `volition.out` realized via `external_speech` / `internal_speech` /
`vox.synthesized` / `praxis.action`, excluding `realization_failed`) into
exactly one of three categories:

- **input-triggered** — the intent's `entry_id` resolves to a coalition member
  whose source/type is `audition.transcription` or `mundus.chat`, or such a
  type was in the winning coalition of the triggering broadcast;
- **drive-triggered** — `thymos.drive` in the coalition path;
- **self-initiated** — neither (the honest default for missing links).

`intent.act` events on `nous.out` are counted separately as **unrealizable**
(no effector reads `nous.out`) and never counted among executed actions.

Persisted metadata fields: `sleep_index`, `realized_total`, `input_triggered`,
`drive_triggered`, `self_initiated`, `unrealizable_nous_intents`,
`realization_failed_count`, plus per-category `entry_ids` lists, `event_types`,
and `saliences`. The payload never contains text, transcripts, or latent
vectors. Under the base thesis (conversation surface, transcription, and
mundus all off) the audit reports `input_triggered == 0` every sleep, proving
the invariant.
