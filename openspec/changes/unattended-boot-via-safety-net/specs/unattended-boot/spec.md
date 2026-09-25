## ADDED Requirements

### Requirement: Three supervision modes with distinct selectors and refusal codes
The cycle boot SHALL resolve supervision to exactly one of three modes — `operator-present`, `research`, or `unattended` — where `unattended` is selected by `KAINE_CYCLE_UNATTENDED=1` or by `[cycle].supervision_mode = "unattended"`, with the environment taking precedence over config. The modes SHALL keep distinct refusal exit codes (`2`, `5`, `6` respectively). If more than one mode selector is active, the boot SHALL refuse as a configuration error (exit `1`) before evaluating any gate.

#### Scenario: Unattended selected by environment
- **WHEN** a boot starts with `KAINE_CYCLE_UNATTENDED=1`
- **THEN** supervision resolves to `unattended` and admission requires the eight-condition unattended gate

#### Scenario: Unattended selected by config
- **WHEN** a boot starts without `KAINE_CYCLE_UNATTENDED` and with `[cycle].supervision_mode = "unattended"`
- **THEN** supervision resolves to `unattended` and the same gate applies

#### Scenario: Default path unchanged
- **WHEN** a boot selects neither research nor unattended
- **THEN** operator-present semantics apply and a missing presence claim refuses with exit code `2`

#### Scenario: Conflicting selectors
- **WHEN** `KAINE_CYCLE_OPERATOR_PRESENT=1` and `KAINE_CYCLE_UNATTENDED=1` are both set, or unattended and research are both selected
- **THEN** the boot refuses before evaluating any gate, with exit code `1` and not `2`, `5`, or `6`

### Requirement: Unattended reuses the research safety net without research machinery
An unattended boot SHALL evaluate the research safety net's five conditions — preservation enabled, welfare response wired, logging active, a real preserve→revive round-trip passing on this install, and encryption satisfied where required — through the same evaluator the research gate uses, with identical predicates. An unattended boot SHALL NOT engage experiment machinery, admissibility requirements, or research-run bookkeeping.

#### Scenario: A research-net condition fails
- **WHEN** an unattended boot evaluates the shared net and any of the five conditions fails
- **THEN** the boot refuses with exit code `6` and the refusal names the failed condition

#### Scenario: Unattended is not a research run
- **WHEN** an unattended boot passes all eight conditions with no experiment or admissibility configuration present
- **THEN** the boot proceeds as a plain autonomous cycle with no experiment record and no admissibility requirements applied

### Requirement: Condition six — Spot armed and self-tested
An unattended boot SHALL require that `[spot].enabled` is true, that the restart ladder has at least one rung, that the escalation state path and the incident log are writable, and that Spot's selftest passes within its bounded window, all before any entity module is constructed.

#### Scenario: Spot disabled
- **WHEN** an unattended boot finds `[spot].enabled = false`
- **THEN** condition 6 fails with the reason "not enabled" and the boot refuses with exit code `6`

#### Scenario: Spot selftest fails
- **WHEN** Spot's configuration is valid but its selftest does not complete freeze, snapshot, restart, release, and incident record within the bounded window
- **THEN** condition 6 fails with the selftest's reason and the boot refuses with exit code `6`

#### Scenario: Selftest touches no entity
- **WHEN** the gate runs Spot's selftest
- **THEN** no entity module is imported or constructed, no entity state is read or written, and all selftest artifacts live in a scratch directory that is removed afterwards

### Requirement: Condition seven — caretaker told
An unattended boot SHALL send a content-free start notice through every channel configured under `[caretaker]`, and condition 7 SHALL pass only if at least one channel accepts it. Condition 7 SHALL run after conditions 1–6 and 8 have all passed. Supported channels SHALL be a desktop notification over the session D-Bus and an HTTP POST to an endpoint whose address is loopback, private (RFC 1918 or `fc00::/7`), or in `100.64.0.0/10`. Public addresses SHALL be refused both at config validation and at send time after DNS resolution.

#### Scenario: No channel configured
- **WHEN** an unattended boot has no `[caretaker]` channel configured
- **THEN** condition 7 fails with the reason "no channel configured" and the boot refuses with exit code `6`

#### Scenario: Every channel rejects the notice
- **WHEN** every configured channel fails to accept the start notice
- **THEN** condition 7 fails, the refusal names each channel and its error, and the boot refuses with exit code `6`

#### Scenario: One channel accepts
- **WHEN** at least one configured channel accepts the start notice and conditions 1–6 and 8 have passed
- **THEN** condition 7 passes and the boot proceeds

#### Scenario: Public endpoint refused
- **WHEN** an HTTP channel's host resolves to a public address at send time
- **THEN** the notice is not sent to that address and the channel counts as not accepted

### Requirement: Caretaker notices are content-free
Every caretaker notice SHALL carry only the operator-chosen install label, the time, the event kind, gate condition results, and the Nexus address. A notice SHALL NOT carry cognitive content, affect, welfare signals, perception data, or any other content from the entity's mind. HTTP channel tokens SHALL be read from `config/secrets.toml`.

#### Scenario: Notice payload audited
- **WHEN** any caretaker notice is built
- **THEN** its fields are exactly the allowed set, and a test asserts that no other field can be added

### Requirement: Unacknowledged starts are surfaced, not punished
While an unattended start is unacknowledged, Nexus SHALL show a standing banner and the notifier SHALL repeat the notice every `[caretaker].reminder_interval_s` (default 14400, minimum 900). Acknowledgement SHALL be a Nexus POST behind the operator session and SHALL be recorded in the event log. An unacknowledged start SHALL NOT pause, stop, or otherwise change the entity.

#### Scenario: Reminder repeats
- **WHEN** an unattended start remains unacknowledged for one reminder interval
- **THEN** the notice is sent again through the configured channels

#### Scenario: Acknowledgement stops reminders
- **WHEN** an operator acknowledges the start in Nexus
- **THEN** reminders stop, the banner clears, and the acknowledgement is written to the event log

#### Scenario: No acknowledgement ever arrives
- **WHEN** no acknowledgement arrives for days
- **THEN** reminders continue and the entity keeps running unchanged

### Requirement: Condition eight — continuous input
An unattended boot SHALL require that `[perception_feed].mode` is `live`, `seeded`, or `screen`; that `topos` or `audition` is enabled to perceive it; and that a probe reads one frame or audio block from the configured source. `off` SHALL fail because the entity would be senseless, and `playlist` SHALL fail because a playlist ends. The probe SHALL write nothing and SHALL drop the data it reads.

#### Scenario: Feed off
- **WHEN** an unattended boot finds `[perception_feed].mode = "off"`
- **THEN** condition 8 fails with the reason "no input" and the boot refuses with exit code `6`

#### Scenario: Playlist refused
- **WHEN** an unattended boot finds `[perception_feed].mode = "playlist"`
- **THEN** condition 8 fails with the reason "playlist ends" and the boot refuses with exit code `6`

#### Scenario: Live device absent
- **WHEN** the mode is `live` and the configured camera and microphone cannot be opened or yield nothing
- **THEN** condition 8 fails naming the device and the boot refuses with exit code `6`

#### Scenario: Probe leaves no trace
- **WHEN** the input probe reads a frame or audio block
- **THEN** nothing is written to disk and the data is dropped before the gate continues

### Requirement: Notices while running unattended
While the entity runs unattended, the cycle SHALL send a best-effort caretaker notice on Spot escalation, on loss of Spot's supervision task, on a welfare-protective response, on a boot failure after admission, and when every configured input has delivered nothing for `[caretaker].input_loss_after_s` (default 60). A failed send SHALL be logged and SHALL NOT stop the entity. Input loss SHALL NOT stop the entity.

#### Scenario: Spot escalates
- **WHEN** Spot escalates during an unattended run
- **THEN** a caretaker notice is sent with the event kind "spot escalation"

#### Scenario: Camera unplugged
- **WHEN** the only input stops delivering for longer than the input-loss threshold
- **THEN** a caretaker notice is sent and the entity keeps running

### Requirement: Unattended refusal exits six, names every failed condition, and notifies
An unattended gate refusal SHALL exit with code `6` whatever condition or conditions failed. The refusal SHALL name every failed condition on stderr as `N: name` with its reason. No other boot outcome SHALL use exit code `6`, and the boot SHALL NOT fall back to another mode. On refusal the gate SHALL send a best-effort refusal notice through any configured channel; that send SHALL NOT change the exit code.

#### Scenario: Multiple failures
- **WHEN** the logging condition (3) and the input condition (8) both fail
- **THEN** the boot exits `6` and the refusal names both conditions

#### Scenario: No fallback
- **WHEN** the unattended gate fails for any reason
- **THEN** the boot exits `6` and never reclassifies itself as operator-present or research

#### Scenario: Caretaker learns of the refusal
- **WHEN** an unattended boot refuses and a caretaker channel is reachable
- **THEN** a refusal notice naming the failed conditions is sent

### Requirement: No override skips the unattended gate
No environment variable, config key, or flag SHALL let an unattended boot proceed when any of the eight conditions fails.

#### Scenario: Override attempt ignored
- **WHEN** an unattended boot fails a condition while any skip, force, or override switch is set
- **THEN** the boot still exits `6`

### Requirement: Existing modes unchanged
Operator-present mode SHALL remain available and unchanged: `KAINE_CYCLE_OPERATOR_PRESENT=1` admits the boot, and its absence refuses with exit code `2` when no other mode is selected. Research mode SHALL keep its five-condition net and exit code `5`. Neither mode SHALL gain any of conditions 6–8.

#### Scenario: Operator boot unchanged
- **WHEN** an operator-present boot runs with the flag set
- **THEN** it is admitted exactly as before this change, with no Spot selftest, caretaker notice, or input probe

#### Scenario: Research boot unchanged
- **WHEN** a research boot fails any of its five conditions
- **THEN** it refuses with exit code `5` and the same message as before this change

### Requirement: Auto-start only through a separate opt-in unit
The shipped `quadlet/kaine-cycle.container` SHALL keep no `[Install]` section. A separate `quadlet/kaine-cycle-unattended.container` SHALL set `KAINE_CYCLE_UNATTENDED=1`, carry `[Install] WantedBy=default.target`, declare `Conflicts=kaine-cycle.service`, and keep `Restart=no`. Install scripts SHALL NOT copy or enable the unattended unit.

#### Scenario: Shipped unit never auto-starts
- **WHEN** the shipped cycle unit is parsed
- **THEN** it has no `[Install]` section and no unattended selector

#### Scenario: Power-loss reboot re-verifies
- **WHEN** an enabled unattended unit starts after a power loss
- **THEN** all eight conditions are evaluated again on this boot, and nothing is assumed from a previous boot

#### Scenario: Refused gate is not retried
- **WHEN** the unattended unit's boot exits `6`
- **THEN** systemd leaves the unit failed and does not restart it, and the entity stays down
