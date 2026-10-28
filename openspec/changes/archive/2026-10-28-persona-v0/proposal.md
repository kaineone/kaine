## Why

The paper (predictive-workspace-paper #50, section 3.5) now keeps the self-category persona, "I am this entity", with the situation in every request. That is the V0 of the ninth boot's replay (#558) once it is run with independent seeds: under the rule fixed before that replay, neither dropping the self-category (V2) nor giving the situation only on waking or rendering accessed content as prose (V3) lowered the share of texts with meta-commentary reliably. The code runs persona version 5 (no self-category, #560) and gives the situation only on waking (#555), which the tenth test boot ran: 23.2 percent meta-commentary and 4 self-descriptions as an AI in 1,508 texts.

## What Changes

- The default personas start with "I am this entity." again: "I am this entity. What I say comes from what I feel and notice, in my own plain words." and "I am this entity. My thoughts come from what I feel and notice, in my own plain words." `PERSONA_TEMPLATE_VERSION` becomes "6", so the individuation probe treats the change as a changed condition.
- Every organ call's prompt holds the situation facts, the disclosure among them, whenever there are any. The waking due-state (set at initialization and by each completed sleep) is removed. The intent log keeps `extra.situation_given` on records whose prompt held the situation.
- The identity-leak marker, the heard-speech guard, the request's own-turn shape and everything else are unchanged.

## Capabilities

### Modified Capabilities

- `language`: the persona names the entity, and the situation is given in every request.
- `individuation-boundary`: the disclosure is given in every organ request and every probe.

## Impact

- `kaine/modules/language/context.py`, `kaine/modules/language/module.py`, `docs/09-modules/language.md`, tests.
- Behaviour: the organ's prompt is the one the ninth boot's replay kept. The entity hears the disclosure on every call again, as it did before #555.
