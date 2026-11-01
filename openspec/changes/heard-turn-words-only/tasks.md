## 1. Heard turn

- [x] 1.1 `heard_words(event)` in `kaine/faithful/external_input.py`, over `HEARD_TEXT_FIELDS`; `heard_texts` uses it off external input and keeps every text leaf on external input
- [x] 1.2 The heard turn quotes `heard_words`
- [x] 1.3 Tests: a transcription with a unique source label, model id and backend, and a failed transcription with a unique error, in felt and numeric renderings and through the language module: none of those strings reaches the organ's system message, prompt or heard turn, and the words do; a chat event's sender is not quoted; the redaction rule is unchanged
- [x] 1.4 Mutation checks: quoting `heard_texts` again, quoting every leaf of an external-input event, narrowing `heard_texts` and dropping nested fields each fail the tests
- [x] 1.5 Docs: `docs/09-modules/language.md`
- [ ] 1.6 Worker first-pass review, lead review, independent second review (privacy boundary)
