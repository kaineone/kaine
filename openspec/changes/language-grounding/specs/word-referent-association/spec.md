## ADDED Requirements

### Requirement: Heard words strengthen associations with co-active prototypes

When speech-to-text and `[language.grounding].word_learning` are on, each transcription SHALL strengthen the association between each of its content-word types and each prototype active within the configured window around it, and every association SHALL decay with the configured time constant. Function words SHALL be identified by their spread across situations, not by an authored list.

#### Scenario: Cross-situational pairs are recovered offline

- **WHEN** the learner runs on the scripted narrated-clip benchmark, in which each word co-occurs with its referent across ambiguous scenes
- **THEN** the learned names recover the benchmark's word-referent pairs above the shuffled-pairing control, by the margin in the validation record

### Requirement: Word learning persists no heard speech

The learner SHALL persist only association weights and, when `[language.grounding].persist_lexicon` is true, the strings of word types that have become learned names. It SHALL NOT persist a transcript, an utterance, word order or timing. With `persist_lexicon` false, word types SHALL persist only as salted hashes.

#### Scenario: No transcript in the learner's store

- **WHEN** the learner's persisted store is read after a conversation
- **THEN** it holds association weights and lexicon entries only, and no sequence of words from any utterance

#### Scenario: Hashed lexicon

- **WHEN** `persist_lexicon` is false
- **THEN** the store holds no word strings, and the renderer says a word exists for a prototype without stating it

### Requirement: A learned name requires strength and specificity

A word SHALL be a learned name for a prototype only when its association exceeds the configured strength and its share of both the word's and the prototype's associations exceeds the configured specificity.

#### Scenario: A word heard with everything names nothing

- **WHEN** a word co-occurs equally with every active prototype
- **THEN** it is not a learned name for any of them
