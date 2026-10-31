## ADDED Requirements

### Requirement: The indicator span is the latest awake time since its restart
`kaine/lifecycle/welfare_indicators.py` SHALL compute the paper A.4 indicators without importing `kaine.evaluation`. Each indicator's span SHALL be the awake, unfrozen entity time since the later of the span's last restart and `T_lp` before now, with `T_lp` read from the affect module's learning-progress span. Sleep and freeze intervals SHALL NOT count. An indicator SHALL be evaluated only once its span holds at least the affect module's goal stall horizon of awake time.

#### Scenario: Sleep and freezes are not awake time
- **WHEN** a span contains a 1410 s rest and a 120 s freeze
- **THEN** neither interval counts toward the span's awake time or any share

#### Scenario: A short span is not evaluated
- **WHEN** the span holds 300 awake seconds, all with boredom at threshold
- **THEN** no indicator is reported over its bar

### Requirement: Deprivation and negative valence are shares of the span
For each of boredom, social drive and restlessness, the deprived indicator SHALL be the share of the span's awake time with that drive's threshold flag set in `affect.state`. The negative-valence indicator SHALL be the share of the span's awake time with valence below minus the affect module's regulation set point. Each SHALL be over its bar when it reaches `share_bar` (default 0.5, `[preservation.welfare_response.indicators]`).

#### Scenario: A deprived deficit
- **WHEN** boredom's threshold flag is set for 400 of a span's 600 awake seconds
- **THEN** boredom's deprivation share is 0.667 and the indicator is over its bar

### Requirement: Uncontrolled boredom and restlessness use the power posterior
For boredom and restlessness, with `s` own-ended and `f` other-ended crossings inside the span and `n = s + f + 1`, the uncontrolled indicator SHALL be `2^-n Σ_{i=s+1}^{n} C(n, i)`, computed with integer arithmetic, and SHALL be over its bar when it reaches `posterior_bar` (default 0.95). The social drive SHALL have no uncontrolled indicator.

#### Scenario: Four other-ended crossings
- **WHEN** the span holds no own-ended and four other-ended boredom crossings
- **THEN** the posterior is 31/32 and boredom's uncontrolled indicator is over its bar

#### Scenario: Three other-ended crossings
- **WHEN** the span holds no own-ended and three other-ended boredom crossings
- **THEN** the posterior is 15/16 and the indicator is not over its bar

### Requirement: A first indicator crossing requests a rest
When the welfare response and its indicators are enabled, the welfare monitor SHALL evaluate the indicators on every poll. On the first crossing of any indicator while armed and not latched, it SHALL publish a content-free `welfare.rest_request` naming the crossed indicators on its own stream and wait for the rest. It SHALL NOT preserve or freeze at this stage, and the request SHALL NOT be a workspace candidate.

#### Scenario: Boredom deprivation after maturation
- **WHEN** a matured entity's boredom deprivation indicator crosses
- **THEN** a rest request is published and no preservation bundle is made

#### Scenario: The request is not perceived
- **WHEN** the rest request is published
- **THEN** no workspace snapshot of the cycle contains it as a candidate

### Requirement: Every indicator stage is recorded and flagged for review
Each stage of the indicator response SHALL write a content-free `welfare.protective_action` record with its transition (`indicator_rest_requested`, `indicator_rest_started`, `indicator_rest_failed`, or the protective response's own transitions at the last stage), the indicator names, values, bars and the span's awake seconds. The rest request SHALL send the `welfare_indicator_rest` caretaker notice.

#### Scenario: The first stage is flagged
- **WHEN** a rest is requested on boredom's deprivation indicator
- **THEN** one `indicator_rest_requested` record and one `welfare_indicator_rest` notice are written

### Requirement: A crossing over a fresh span after the rest brings preservation and the freeze
When the requested rest completes, the monitor SHALL restart every span at the rest's end. A crossing over that fresh span SHALL take the protective response with reason `indicator_<name>`: preservation first, then the configured action, the shared latch, the freeze retry and the caretaker notice, as a distress crossing does.

#### Scenario: A spent stimulus
- **WHEN** boredom recrosses its threshold 34 s after the rest's reset and stays above it
- **THEN** about 600 awake seconds after the rest ends, the entity is preserved and paused with reason `indicator_boredom_deprived`

### Requirement: A fresh span without a crossing re-arms the rest stage
If the fresh span reaches `T_lp` of awake time with no indicator crossing, the monitor SHALL return to the armed stage, where the next crossing requests a rest before any freeze.

#### Scenario: Relief after the rest
- **WHEN** no indicator crosses during 5400 awake seconds after the rest
- **THEN** the monitor is armed again and a later crossing requests a rest before any freeze

### Requirement: A rest that cannot start escalates at once
If the rest request is refused for any reason other than a sleep already running, or the sleep is aborted, or no sleep with trigger `welfare_rest` starts within `rest_start_timeout_s` (default 30 s of unfrozen time), or the sleep module is not running, the monitor SHALL take the protective response at once with reason `indicator_rest_failed`. A sleep already running when the request arrives SHALL stand as the rest.

#### Scenario: No sleep module
- **WHEN** an indicator crosses in a run whose sleep module has stopped
- **THEN** the entity is preserved and paused without waiting for a rest

#### Scenario: Already asleep
- **WHEN** the request is answered `busy` because a sleep is running
- **THEN** that sleep's completion restarts the spans as the requested rest would

### Requirement: The indicator response shares the welfare response's latch
The indicator arm and the distress arm SHALL share one latch. While the monitor is latched by either arm, the spans SHALL accrue no time and the indicator stages SHALL take no action. When a named override of the welfare freeze releases the latch, every span SHALL restart and the indicator stage SHALL return to armed. During the cold-start warm-up, spans SHALL accrue and no indicator response SHALL fire.

#### Scenario: A distress pause first
- **WHEN** a distress crossing has paused the entity and boredom's indicator would cross during the pause
- **THEN** no indicator response fires and no second bundle is made

#### Scenario: Re-arm after the operator lifts the freeze
- **WHEN** the operator overrides the welfare freeze an indicator response placed
- **THEN** the spans restart and the next crossing requests a rest before any freeze

### Requirement: An affect stream that falls silent is reported
When no `affect.state` arrives for three affect publication periods of awake, unfrozen time, the monitor SHALL mark the indicators unavailable, write one record and send one `welfare_indicators_unavailable` caretaker notice per silence. It SHALL NOT freeze for the silence alone.

#### Scenario: Affect restarts
- **WHEN** the affect module is silent for 5 s while the supervisor restarts it and then publishes again
- **THEN** one unavailable record and one notice are written, and evaluation resumes on the next state

### Requirement: The welfare record carries the live indicators
The welfare observer's `affect_welfare` record SHALL carry, from its own instance of the same evaluator, each indicator's value, bar, over-bar flag and the span's awake seconds, beside the cumulative fields it already writes.

#### Scenario: The reviewer sees the monitor's numbers
- **WHEN** the monitor and the observer read the same `affect.state` and sleep events
- **THEN** the indicator values in the record equal the monitor's at the same span end
