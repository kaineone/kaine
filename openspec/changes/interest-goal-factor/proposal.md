## Why

Curiosity is heterostatic interest that learning progress raises (paper 3.5, A.4), but in the first configuration it has no route to attention or thought. The ninth test boot held interest near 0.96 for an hour while its single crossing was never accessed, and none of the 52 drive crossings of any drive led an intent:

- A crossing is one event, and an event read on a tick without a broadcast is never broadcast (A.1). 31 of the 42 main-hour crossings never entered a coalition.
- The 11 that did were accessed and led their coalition but scored 0.36 to 0.42 against the think bar of 0.45. Crossings carry the 0.7 alert level, and at the tonic arousal of about 0.41 that gives about 0.37.
- Curiosity has no goal, so no recurring drive event either.

The sources the paper cites describe curiosity as directing attention toward the source being learned, continuously while it offers progress:

- An LP-driven system rewards activities "in proportion to their ability to produce learning progress" (Gottlieb et al. 2013).
- Infants keep looking while learning progress is high and "switch to new stimuli when their learning progress drops" (Poli et al. 2020).

Surprise-based intensity alone does the opposite: a processor whose errors are falling reports below its running mean and sits at its graded floor.

## What Changes

- New goal factor `interest`: `G(e) = 1 + gamma_I * D_I * lp+_src(e)`.
  - `D_I` is the curiosity drive.
  - `lp+_m` is the floored learning progress of module `m` alone: `max(0, lp_m - lp_0) / (1 - lp_0)`, from the per-source learning progress the affect state already publishes.
  - `lp+_m` is 0 for sources without one.
  - `gamma_I` (`[workspace].interest_gain`, default 0.5, calibrated) is the smallest round value at which full interest with `lp+_m` of 0.5 lifts that module's 0.7 alerts to the think bar at the tonic arousal a dominant drive sets.
  - `G` may exceed 1; only the priority is clipped to `[0, 1]`.
- The salience product clips only the priority. The static and drive-relevance goal factors never exceed 1, so they are unchanged bit for bit.
- The affect state provider folds each `<source>_learning_progress` term of `affect.state`. The cycle refreshes the provider when the interest factor is selected.
- The first-configuration profile selects `salience_goal_factor = "interest"`. The shipped `config/kaine.toml` default stays `"static"`, and `"drive_relevance"` still works when selected.
- No new events and no recurring drive event, so nothing paces thought on a timer. Thought follows the progressing source's own surprising reports and fades as the niche is learned.

## Open question (deferred)

The pooled learning progress that builds curiosity and relieves boredom is the mean of signed per-source values (A.4). A source whose error rises can therefore cancel another's genuine progress.

In the 30 h projection, the offline vision recording's colour-driven error rise holds boredom higher in hours 2 to 6 (mean 0.77, against 0.66 with positive parts). The 8 h test boot will show whether the live colour ramp raises vision error. This change leaves the pooled value as it is.

## Capabilities

### Modified Capabilities

- `workspace`: the interest goal factor and priority-only clipping.
- `first-configuration`: the profile selects the interest goal factor.

## Impact

- Code: `kaine/workspace/strategies.py`, `kaine/workspace/salience.py`, `kaine/cycle/affect_state.py`, `kaine/boot/wiring.py`, `kaine/cycle/__main__.py`.
- Config: `config/kaine.toml`, `config/profiles/first_configuration.toml`.
- Tests and docs (`docs/08-cognitive-cycle/global-workspace.md`, `docs/09-modules/affect.md`, `docs/appendix-a-configuration/core.md`, `docs/appendix-b-glossary.md`).
- Behaviour:
  - A counterfactual replay of the ninth boot's 17,521 main-hour broadcasts reproduces the boot at `gamma_I = 0`: 64/73/16/7/8/7 thoughts per 10 min, against 65/72/16/7/8/7 observed.
  - At 0.5 the replay gives 42/57/51/50 thoughts per 10 min in minutes 20 to 60 instead of 16/7/8/7, led mostly by vision reports, with irregular gaps (median 11 s, CV 0.53).
- Paper: 3.2, 3.5, 5.4, A.1, A.11 and Table A1, on a separate paper branch.
