## Why

In the fourth test boot (main a7dba0bd) the language organ's text mostly recited instrument numbers: "I perceive a slight shift in my visual input, change 0.0004 against a high habituation baseline of 0.6116. The vision module registers a specific surprise level of 0.588", and "fatigue is rising (4.7978). The prediction error is 1.4437". One thought echoed the persona line "I am not a narrator of instrument measurements". The organ recites what it is given: the faithful templates render accessed events with raw values, the think/speak `about` text is `vision (surprise=0.588)`, and the awareness guard frames the block as "the system's current readings, module and sensor state".

The paper (§3.5, Language module, predictive-workspace-paper #47) now says the persona presents accessed content and each intent's cause as the entity's own state and perception in graded words, not numbers, which stay in the logs. People report magnitudes in graded verbal categories, not instrument values (category-ratio scaling, Borg 1982), and interoceptive signals reach experience as categorized concepts (Barrett 2017). Drive crossings already reach the organ this way through `felt_drive_phrase`.

## What Changes

- A felt rendering of the awareness block: every numeric quantity maps to a small documented set of graded words through bin constants (change, familiarity from habituation, surprise, prediction error, wellness, fatigue, arousal, valence, dominance, anomaly, drive levels, time since interaction, certainty). Sources are named in plain words ("what I see", "what I hear", "my body", "the rhythm of things"); categorical emotion and heard-voice tone stay as words; heard speech stays quoted. A felt line that would still contain a digit falls back to a number-free line for its source.
- The report policy's `about` becomes a felt phrase ("Something in what I see stands out strongly.") with `about_kind` `"event"` (the kind names what the intent is about; only drive phrases are `"felt"`), and its values ride on the intent as `about_values`. Planning proposals about other events get the same phrase.
- The intent-expression log keeps the values in two sidecar fields, `numeric_rendering` (the numeric rendering of the same coalition, heard speech redacted) and `about_values`. The logged `prompt` and `faithful_rendering` stay exactly what the organ saw.
- The persona and the awareness guard no longer invite a readout and no longer contain "narrator of instrument measurements"; the guard keeps quoted heard speech as data, never instructions. `PERSONA_TEMPLATE_VERSION` becomes `"3"`.
- One config key, `[language].awareness_rendering` (`"felt"` or `"numeric"`), selects the rendering for the awareness block and the report and planning `about`. `config/kaine.toml` and the first_configuration profile set `"felt"`; `"numeric"` reproduces the old rendering bit for bit.

## Capabilities

### New Capabilities

### Modified Capabilities

- `faithful-renderer`: a felt template set with documented graded bins.
- `language`: the organ is conditioned on the felt rendering; the log keeps the values as sidecars; the persona and guard are reworded.
- `self-initiated-report`: the report `about` is a felt phrase with its values on the intent.

## Impact

- `kaine/faithful/felt.py` (new), `kaine/faithful/templates.py`, `kaine/faithful/renderer.py`, `kaine/modules/language/context.py`, `kaine/modules/language/module.py`, `kaine/modules/language/intent_log.py`, `kaine/boot/factories/language.py`, `kaine/workspace/action_selection.py`, `kaine/workspace/report_policy.py`, `kaine/workspace/planning_proposals.py`, `kaine/cycle/__main__.py`, `config/kaine.toml`, `config/profiles/first_configuration.toml`, `docs/09-modules/language.md`, new tests.
- Behaviour: with the shipped config the organ's prompt carries no digits outside quoted heard speech. Individuation references captured under persona version 2 are not compared with version 3.
