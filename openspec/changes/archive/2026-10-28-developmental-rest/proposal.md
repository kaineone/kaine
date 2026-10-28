## Why

In the tenth test boot the developmental stimulus was spent for hours at a time: no processor had learning progress and no alert came faster than the habituated rate, so boredom stood at or above its threshold between the entity's own intents and its goals stalled. Sleeps lasted 8 to 14 s, while boredom rebuilt to threshold in about 34 s, so sleep never relieved it. The paper (predictive-workspace-paper #48, section 3.5 and Table A1) now adds a developmental rest: in the developmental phase, sleep also begins when a boredom goal stalls with no learning progress or alert excess throughout the stall, and that rest lasts Delta_rest = 1,260 s, the mean length of a quiescent episode (state 1F) in mature fetuses (Pillai and James 1990). Other sleeps still end with their phases.

## What Changes

- The affect module records the last entity time at which `lp+` or the alert excess was above zero. When a boredom goal is abandoned as stalled and that time lies before the start of the stall (or never happened), and the development probe says the entity is developing, it publishes `affect.rest_request` on `affect.out` with `reason = "stimulus_spent"`, the drive and the stall length. The time since the last engagement persists in the affect snapshot as a duration. A snapshot without it counts as engaged at the restore.
- The sleep module starts a sleep with trigger `developmental_rest` on that event, under the same guards as the other event-driven triggers. That sleep runs its phases and then stays asleep until `[sleep].developmental_rest_s` (1,260 s, Table A1 Delta_rest) of entity time has passed since it began, then ends with the affective reset as every sleep does. A cancel or shutdown during the hold still runs the reset. Its `sleep.sleep.started` and `sleep.sleep.completed` events carry the trigger and its completed event the rest length.
- Every other sleep is unchanged, and after maturation (or with staging disabled, where the probe is absent) no rest request is published.

## Capabilities

### Modified Capabilities

- `affect`: a stalled boredom goal on a spent stimulus requests a developmental rest.
- `sleep`: a developmental rest lasts `developmental_rest_s`.

## Impact

- `kaine/modules/affect/module.py`, `kaine/modules/sleep/module.py`, `kaine/boot/factories/sleep.py`, `kaine/evaluation/observers/research_event_observer.py`, `config/kaine.toml`, `docs/09-modules/affect.md`, `docs/09-modules/sleep.md`, new tests.
- Behaviour: during development, a spent stimulus brings a 21-minute rest in place of hours above the boredom threshold. While the entity rests the cycle runs on, the perceptual feed pauses except the developmental stimulus, and forward-model adaptation is suspended, as in every sleep. The rest ends with the affective reset, which clears boredom.
