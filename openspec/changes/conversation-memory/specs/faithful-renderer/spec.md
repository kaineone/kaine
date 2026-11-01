## ADDED Requirements

### Requirement: A remembered conversation renders as past and attributed
The felt renderer SHALL render conversation recall content in past tense, naming the speaker by a phrase and never quoting heard words:
- an utterance trace as "I remember, <age phrase>, <speaker phrase> spoke to me: I took it that <gist>.", then "I said: "<said>"." when it holds a reply;
- an episode trace as "I remember, <age phrase>, talking with <speaker phrase>: <account>.".

The digit guard SHALL apply.

#### Scenario: Remembered content is attributed
- **WHEN** a recall's content comes from an utterance trace of the operator
- **THEN** the rendered line begins "I remember," and names "the operator" as the one who spoke

### Requirement: A withheld gist renders without invention
A conversation trace whose gist or account is withheld SHALL render as "I remember <speaker phrase> spoke to me, but not what I took from it.".

#### Scenario: A withheld gist is not invented
- **WHEN** a recalled utterance trace has `gist: null`
- **THEN** the line says the entity remembers being spoken to and not what it took from it

### Requirement: Speaker phrases come from the speaker label
The speaker phrase SHALL be:
- "the <label>" for the configured speaker label;
- "someone in what I was watching" for a `media:` channel of the audition module;
- "someone in the world" for in-world chat.

#### Scenario: A film voice is not the operator
- **WHEN** a recalled utterance trace has speaker `media:playlist`
- **THEN** the line names "someone in what I was watching"
