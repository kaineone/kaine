## Why

Two wiring faults found in the documentation sweep.

- Thymos caches each agent's familiarity from `empatheia.agent_model` under
  the payload's `agent_id`, but looks it up by the perceived speaker's
  `source_label` (the audio channel). Empatheia's agent ids are the speaker
  label for operator channels and `media:<channel>` otherwise, so the lookup
  never matches and the emotional-coupling weight is always `coupling_base`.
- The utterance-outcome observer reads `[lingua].outcome_reply_window_s`, but
  the Lingua factory's key check does not accept it, so setting it stops boot.

## What Changes

- `empatheia.agent_model` carries the `source_label` of the audio event that
  updated the model, and Thymos caches the familiarity under that label as
  well as under `agent_id`, so its lookup by `source_label` finds it.
- The Lingua factory accepts `outcome_reply_window_s` and leaves it to the
  observer that reads it.

## Capabilities

### Modified Capabilities

- `thymos`: familiarity reaches the coupling weight.
- `lingua`: the reply-window key is accepted.

## Impact

- `kaine/modules/empatheia/module.py`, `kaine/modules/thymos/module.py`,
  `kaine/boot/factories/lingua.py`, tests. Both modules involved in the first
  fix are held in the base-thesis profile.
