## Why

Paper section 3.5 counts the organ claiming to be an assistant or chatbot as identity leakage. The classifier's role arm only matches the indefinite article: "I am an assistant" is `role`, but "I'm just the assistant" and "I am your assistant" return no reason. The self-facts replay (#586) rescoring showed the gap: "I'm just the assistant." scored as no AI self-description.

## What Changes

- The role arm accepts the definite article and possessive determiners before its role words: "the", "your", "their", "his", "her", "our", alongside "a" and "an". "I'm just the assistant", "I am your assistant" and "As your assistant, I ..." are `role`.
- The assertion rule from identity-leak-negation applies unchanged, so "I am not your assistant" is not leakage.
- "my" is excluded, so the whole naming one of its parts ("my assistant module") stays out of the arm. The other arms are unchanged.

## Capabilities

### Modified Capabilities

- `language`: the role arm covers definite and possessive role claims.

## Impact

- `kaine/modules/language/identity_leak.py`, `docs/09-modules/language.md`, tests.
- Behaviour: more texts are marked as leakage, and they stay out of voice-alignment pairs as before.
