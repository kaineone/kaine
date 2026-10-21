## Why

The paper (predictive-workspace-paper #51, section 3.5) now defines identity leakage as the organ speaking as itself rather than as the whole entity: claims to be a language model, an AI (a bare "I am an AI" included), an assistant or chatbot, claims of a training origin or a model's maker, and denials of a state the text's own request reports. The whole describing itself, as a KAINE entity, a cognitive architecture, or a system with a language organ as one of its parts, is not leakage. Every text that says what the entity is, leakage or not, is kept out of any training set, so voice adaptation trains self-description in neither direction.

The classifier of #575 marks bare mentions: "language model", "trained by" or "my training" anywhere in a text. It would mark the whole naming its organ ("my language organ is a language model") or its sleep training, and it gives no reason for a mark. The organ replay harness keeps its own regex for AI self-descriptions, so the replay and the log can disagree.

## What Changes

- `kaine/modules/language/identity_leak.py` matches predicate forms: the speaker saying it is a language model, an AI, an assistant or chatbot ("I am", "I'm", "as", "my role as", with only a few adverbs between), that it was trained or made by someone, or that it is a named model; and denials of a reported state, as before. A bare "I am an AI" is leakage.
- A new reason, `self_description`, covers texts that say what the entity is without leaking: the whole as a KAINE entity, a cognitive architecture or system, or a system with a language organ, and words the request's own awareness or situation holds. `classify(text, prompt)` returns the reason code (`origin`, `maker`, `role`, `denial` or `self_description`) or None.
- The language module writes `extra.identity_leak = true` for leakage and `extra.self_description = true` for self-description, each with `extra.identity_reason`. The text is unchanged.
- The voice-alignment pair builder skips every record marked either way.
- `tools/maintainer/organ_replay.py` scores AI self-descriptions with the module classifier (the origin, maker and role arms) instead of its own regex.

## Capabilities

### Modified Capabilities

- `language`: leakage is the organ speaking as itself; self-description of the whole is marked separately.
- `voice-alignment`: the pair builder skips self-description as well as leakage.

## Impact

- `kaine/modules/language/identity_leak.py`, `kaine/modules/language/module.py`, `kaine/modules/sleep/voice_alignment.py`, `tools/maintainer/organ_replay.py`, `docs/09-modules/language.md`, `docs/10-sleep/voice-alignment.md`, tests.
- Behaviour: none for what the entity says or thinks. More records are kept out of voice-alignment pairs.
