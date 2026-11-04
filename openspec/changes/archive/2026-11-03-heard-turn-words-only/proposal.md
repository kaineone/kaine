# The heard turn quotes only the words heard

## Why
The language module quotes every text leaf of an external-input event to the organ as heard speech. A transcription carries its words under `text` and, beside them, its channel (`source_label`), the speech-recognition model id (`model`) and the backend name (`backend`); a failed transcription also carries an `error` message. One transcription of "please feed the cat" therefore reached the organ as four heard lines: the words, `"operator_mic"`, `"Systran/faster-whisper-medium.en"` and `"speaches"`. The organ was told that someone said its own speech-recognition model's name. A chat event's sender name was quoted the same way.

The cause is that one function, `heard_texts`, serves two purposes. Redaction and storage need every outside string an event carries, metadata included, so they fail closed. The heard turn needs only the words someone said.

## What changes
- `kaine/faithful/external_input.py` gains `heard_words(event)`: the text leaves under a `HEARD_TEXT_FIELDS` key at any depth, on an external-input event and on any other module's event alike; none on the language module's own events. It uses the heard rule's own field set, the set the `heard-text-volatile-bus` change also uses, so there is no second list.
- The heard turn (`ContextAssembler._heard_event_lines`) quotes `heard_words`, never `heard_texts`.
- `heard_texts`, `is_heard_event`, the log redaction, the residual redaction and the episodic store are unchanged: every text leaf of an external-input event is still redacted and kept out of storage.
- No layout constant changes, so `layout_digest()` and `PERSONA_TEMPLATE_VERSION` stay as they are.

## Impact
- Specs: `language` (the heard turn's strings).
- Code: `kaine/faithful/external_input.py`, `kaine/modules/language/context.py`.
- Tests: `tests/test_heard_metadata_not_quoted.py`; `tests/test_external_input_heard_rule.py` checks the language module imports `heard_words` from the heard rule.
- Docs: `docs/09-modules/language.md`.
- Behaviour: an external-input event with no words under a heard-text field (an empty or failed transcription, or a chat event that puts its words under another key) is still heard, and the notes still end with "Someone else spoke to me.", but it contributes no quoted line. Words a producer publishes under a key outside `HEARD_TEXT_FIELDS` are not quoted; they are still redacted and never stored.
- Privacy code: the change takes an independent second review.
