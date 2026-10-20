## Why

The sleep-time intent audit links each realized utterance to its intent through the realization payload's `entry_id`. The language module's `external_speech` and `internal_speech` payloads carry no `entry_id`: they carry `record_id`, and the intent-log record with that id holds `intent_entry_id`. Every utterance therefore fell through to the last intent of its kind in the whole window and was classified by that one intent's coalition. In the tenth test boot seven of the eight audits reported `drive_triggered` 0, and the eighth reported 140 of 147 utterances as drive-triggered, while the bus showed 15 to 77 drive-led intents per hour.

## What Changes

- `classify_realizations` takes `record_links`, a map from the language module's `record_id` to the `intent_entry_id` of the intent the record realized, and links each realization through it when the payload has no `entry_id`.
- Only a requested sleep keeps the link to the last `intent.rest` of the window, because `sleep.sleep.started` carries no id. A speech or action realization with no link counts as self-initiated and records no entry id.
- The sleep module builds the map from the two newest intent-log files (the corpus file rotated in this sleep, or the newest one, and the live log). A read failure leaves the audit unlinked with a warning.
- The audit payload keeps its keys and stays content-free.

## Capabilities

### Modified Capabilities

- `hypnos-consolidation`: the sleep-time ignition audit links realizations to their own intents.

## Impact

- `kaine/modules/sleep/ignition_audit.py`, `kaine/modules/sleep/corpus.py`, `kaine/modules/sleep/module.py`, `docs/09-modules/sleep.md`, new `tests/test_ignition_audit_record_link.py` and `tests/test_ignition_audit_intent_log_links.py`.
- Behaviour: none for the entity. The audit is a sleep-time measurement that nothing in the cycle reads. Its counts change: drive-led and input-led utterances are counted as such.
