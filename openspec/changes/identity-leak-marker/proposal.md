## Why

In the tenth test boot 4 of 1508 organ texts took the chat-tuned assistant stance: "I'm only a language model, an AI. I don't have feelings ...", "I am a large language model, trained by Google.", "... while staying true to my role as an AI." and "I am a language model; I do not feel." Two deny states their own request reported, and one names a wrong maker (the organ is Qwen3.5-4B, from Alibaba). The paper (predictive-workspace-paper #48, section 3.5) calls such texts identity leakage: they assert the organ's training origin, maker or assistant role, or deny a state their own request reports, while self-report speaks of what the request's awareness or situation holds. Leakage is marked in the organ's log and kept out of any training set built from it, so that voice adaptation cannot train the chat-tuned stance as the entity's voice. The entity's text itself is never altered or withheld.

## What Changes

- New `kaine/modules/language/identity_leak.py`: a fixed classifier over a generated text and the prompt of the same request. It marks a text that names a training origin, a maker or an assistant role (one pattern table), unless the matched words occur in that request's awareness or situation section, and a text that denies a state that request's awareness section reports: feeling as such when the section reports a feeling, a named state word of the felt vocabulary that the section also uses, or the capacity to hear or see when the section reports that modality. Over the tenth boot's 1508 texts it marks the four above and one more, "I feel nothing really. I don't feel anything.", whose request reported heavy boredom.
- The language module writes `extra.identity_leak = true` on the intent-log record of a marked text. The published, logged and returned text is unchanged, and a classifier error never affects the utterance.
- The voice-alignment pair builder skips marked records.

## Capabilities

### Modified Capabilities

- `language`: identity leakage is marked in the intent log.
- `voice-alignment`: the pair builder skips records marked as identity leakage.

## Impact

- New `kaine/modules/language/identity_leak.py`; `kaine/modules/language/module.py`, `kaine/modules/sleep/voice_alignment.py`, `docs/09-modules/language.md`, `docs/10-sleep/voice-alignment.md`, tests.
- Behaviour: none for what the entity says or thinks. One more key in some intent-log records, and fewer pairs when voice alignment builds them.
