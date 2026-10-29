## Why

The self-facts replay (#586) tested giving the language organ the entity's launch name and identity facts as situation facts, under a rule fixed before the run. No arm won, so the organ is not told the name. The persona still opens with "My name is <name>." whenever `persona_name` is set or the self-model document carries a name. The self-model module assigns a launch name at its first boot, so enabling it would put the name into every organ request.

## What Changes

- The persona no longer carries a name line. `_name_from` and its stale comment are removed. No source, whether `persona_name` or the self-model document, can put the entity's name into the organ's system text or prompt.
- `[language].persona_name` is retired. A config that still sets it boots with a warning, and the value is ignored.
- `PERSONA_TEMPLATE_VERSION` becomes "7". The persona digest keeps its shape, with null in the name slot, so a config that never set `persona_name` keeps its digest.
- The entity keeps its name in its identity and its self-model, where the console and the records read it.

## Capabilities

### Modified Capabilities

- `language`: the organ's request carries no name.

## Impact

- `kaine/modules/language/context.py`, `kaine/modules/language/module.py`, `kaine/boot/factories/language.py`, `docs/09-modules/language.md`, `docs/appendix-a-configuration/modules.md`, tests.
- Behaviour: with the self-model enabled, or with `persona_name` set, the organ's system text loses its opening name sentence. Otherwise the request is unchanged.
- Probe conditions: the persona digest changes only for a config that set `persona_name`. The version bump makes every stored individuation reference report `conditions_changed` at its next look, the designed path for a changed persona, as with the earlier bumps.
