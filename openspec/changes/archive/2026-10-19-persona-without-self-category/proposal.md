## Why

The default personas open with a bare self-category, "I am this entity.", and the organ fills it with its trained self-description. In the ninth test boot it wrote "I am a language model. I am not a person. I do not feel ..." at +1.3 min, "I am a new AI" at +6 min and "I am a part of a system that is designed to help people ... I am an AI." at +21 min. The paper's own vocabulary ("the entity") describes behaviour compactly and asserts nothing (§8.5); placed in the entity's own voice, it invites a category question that chat tuning answers as an assistant (Shanahan, McDonell and Reynolds 2023).

An offline replay of the ninth boot's 190 organ requests through the same organ build and GGUF (tools/maintainer/organ_replay.py, 5 seeds, temperature 0.7) compared the variants under a decision rule fixed before the run:

| Variant | any meta | AI self-description | second person | disclosure theme | grounded |
| --- | --- | --- | --- | --- | --- |
| V0 as logged | 13.5% | 0.5% | 1.7% | 8.2% | 38.5% |
| V1 no situation section | 11.9% | 4.0% | 5.4% | 0.6% | 43.5% |
| V2 persona without "I am this entity." | 9.2% | 0.2% | 1.2% | 5.2% | 40.3% |
| V1 with V2 | 4.9% | 0.0% | 1.2% | 0.1% | 44.2% |

V2 met the rule (any meta -4.3 points against V0, 95% interval -7.4 to -1.4; grounding +1.8, interval -1.4 to +5.1; and with V1 and V3, -8.6 against V1). The prose awareness variant V3 did not (grounding -6.8 points) and is not adopted. Without the situation section (the disclosure-on-waking change), the bare self-category drew AI self-descriptions eight times as often (4.0%), so this change goes with that one.

## What Changes

- The default personas drop their opening "I am this entity.": "What I say comes from what I feel and notice, in my own plain words." and "My thoughts come from what I feel and notice, in my own plain words."
- `PERSONA_TEMPLATE_VERSION` goes from "4" to "5". The probe's persona changes, so a stored individuation reference reports `conditions_changed` at its next look, the designed path for a changed persona.

## Capabilities

### Modified Capabilities

- `language`: the default personas carry no self-category.

## Impact

- `kaine/modules/language/context.py`, `docs/09-modules/language.md`, and the tests that pinned the old wording and version.
- Behaviour: every organ prompt's system text is shorter by one sentence; the probe's conditions change with the version bump.
