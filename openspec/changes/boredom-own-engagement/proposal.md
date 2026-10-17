## Why

Boredom relief came only from perceptual novelty, which the credit rule counts as response-independent (`own=False`). In the fourth test boot all 8 boredom goals that ended by a fall ended "abandoned, without_response" (drive_outcomes boredom own=0), so the coping score learned that boredom cannot be changed by the entity's own response, the structure of learned helplessness (Maier and Seligman 2016). The literature does not support that reading. Boredom is the failure to engage attention with internal or external information (Eastwood et al. 2012) or with valued activity (Westgate and Wilson 2018), it motivates the pursuit of new goals and experiences (Bench and Lench 2013, 2019), and situations that preclude effective engagement are boring because they deny control (Struk, Scholer and Danckert 2021). Re-engagement is the entity's own response to boredom. Self-generated thought as such does not count: thinking alone is unpleasant and less engaging than mundane activity (Wilson et al. 2014; Westgate, Wilson and Gilbert 2017), and noticing one's failure to engage is part of boredom itself (Eastwood et al. 2012). The paper (predictive-workspace-paper PR #47, sections 3.5 and A.4, Table A1) now defines the channel.

## What Changes

- Each intent other than rest on the action-selection stream whose `about_kind` is not `"felt"` relieves boredom by `D <- D * (1 - rho_eng)` with `own=True`, alongside the existing restlessness relief. Intents about a drive's felt state do not relieve boredom.
- A boredom crossing ended this way counts as the entity's own response: the boredom goal completes with reason `own_response`. Perceptual novelty keeps relieving boredom continuously with `own=False`.
- New `[affect] boredom_engagement_relief` (rho_eng, default 0.5, Table A1). 0.0 turns the channel off and reproduces the previous behaviour exactly.
- The sleep reset is unchanged.

## Capabilities

### Modified Capabilities

- `affect`: the entity's own engagement relieves boredom and is credited as its own response.

## Impact

- `kaine/modules/affect/drives.py`, `kaine/modules/affect/module.py`, `kaine/boot/factories/affect.py`, `config/kaine.toml`, `docs/09-modules/affect.md`, tests.
- Behaviour: boredom crossings that end after an engaging intent count as successes for coping and complete their goal; with `boredom_engagement_relief = 0.0` nothing changes.
