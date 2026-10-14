## Why

Two wiring faults found in the documentation sweep.

- The affect module caches each agent's familiarity from `social_cognition.agent_model` under
  the payload's `agent_id`, but looks it up by the perceived speaker's
  `source_label` (the audio channel). The social cognition module's agent ids are the speaker
  label for operator channels and `media:<channel>` otherwise, so the lookup
  never matches and the emotional-coupling weight is always `coupling_base`.
- The utterance-outcome observer reads `[language].outcome_reply_window_s`, but
  the language module factory's key check does not accept it, so setting it stops boot.

## What Changes

- `social_cognition.agent_model` carries the `source_label` of the audio event that
  updated the model, and the affect module caches the familiarity under that label as
  well as under `agent_id`, so its lookup by `source_label` finds it.
- The language module factory accepts `outcome_reply_window_s` and leaves it to the
  observer that reads it.

## Capabilities

### Modified Capabilities

- `affect`: familiarity reaches the coupling weight.
- `language`: the reply-window key is accepted.

## Impact

- `kaine/modules/social_cognition/module.py`, `kaine/modules/affect/module.py`,
  `kaine/boot/factories/language.py`, tests. Both modules involved in the first
  fix are held in the base-thesis profile.
