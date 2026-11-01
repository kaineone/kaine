## ADDED Requirements

### Requirement: The heard turn quotes only the words heard
The heard turn SHALL quote, for each heard coalition event, only the strings `heard_words(event)` returns: the text leaves under a `HEARD_TEXT_FIELDS` key (`kaine/faithful/external_input.py`) at any depth. An external-input event's other fields are metadata and SHALL NOT be sent to the organ: a transcription's `source_label`, `model`, `backend` and `error`, and a chat event's sender.

#### Scenario: A transcription's metadata is not quoted
- **WHEN** a speak intent is realized, in felt or numeric rendering, from a coalition holding an `audition.transcription` with `text` "please feed the cat" and a unique `source_label`, `model` and `backend`
- **THEN** the heard turn holds `Someone else said, in their words and not mine: "please feed the cat".`, and none of the three metadata strings occurs in the system message, the prompt or the heard turn

#### Scenario: A failed transcription quotes nothing
- **WHEN** the coalition holds an `audition.transcription` with empty `text` and a unique `error` message, and the trigger is not heard
- **THEN** the heard turn is empty and the error message occurs nowhere in the organ's request

### Requirement: A heard event without words stays heard and redacted
A heard event with no words under a heard-text field SHALL still count as heard, so the notes end with `- Someone else spoke to me.`, and SHALL contribute no quoted line. Redaction and storage SHALL keep using every text leaf of an external-input event (`heard_texts`), metadata included.

#### Scenario: Redaction still covers the metadata
- **WHEN** `heard_texts` is applied to a transcription with words and a `source_label`, `model` and `backend`
- **THEN** it returns the words and the three metadata strings
