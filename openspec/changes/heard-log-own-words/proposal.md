## Why

The ninth test boot logged "heard speech placeholder applied to residual text in log" three times. In each case the language module's own earlier utterance was in the coalition, and its `user_input` (the felt phrase that moved it to speak) or its `faithful_rendering` (its own redacted awareness lines) matched text in the new prompt. The residual pass replaced those matches with `[heard speech]`, so the intent log recorded the entity's own words as another speaker's. The organ received the true prompt and no heard speech leaked; the defect is wrong provenance in the log that the held voice-alignment trainer reads, and a false alarm on a warning that exists to catch heard-text residue.

Both fields are redacted when the language module publishes them (`user_input` against heard and foreign field texts, `faithful_rendering` as the logged working memory). Publishing already uses heard texts and foreign field texts as its redaction set; the log's residual pass used a wider set that also held the language module's own field values.

## What Changes

- The residual pass over the logged prompt, faithful rendering, heard turn and numeric rendering uses the same set as publishing: texts of external-input events plus heard-field values from events other than the language module's own.
- Each event's rendering is still redacted on its own, so an older own event that carries heard text in a field is still kept out of the log.

## Capabilities

### Modified Capabilities

- `language`: the intent log's residual redaction leaves the entity's own already-redacted words in place.

## Impact

- `kaine/modules/language/module.py`, `docs/09-modules/language.md`, new `tests/test_heard_log_own_words.py`.
- Behaviour: the organ's prompts and published events are unchanged. The intent log keeps the entity's own felt phrases and awareness lines where they were replaced before, and the warning fires only for heard text from outside.
