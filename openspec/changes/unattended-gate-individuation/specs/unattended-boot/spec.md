## ADDED Requirements

### Requirement: Condition nine: individuation wired
An unattended boot SHALL require the research safety net's individuation check: `[individuation].enabled` is true, the `[individuation]` section is valid, and the `lingua` module is enabled. The predicate SHALL be the research net's own, so the entity's protection does not rest on the secondary divergence signals alone while nobody is present. The condition SHALL check that the individuation producer will run; it SHALL NOT require that the entity has individuated. Conditions 6–8 SHALL keep their numbers.

#### Scenario: Individuation disabled
- **WHEN** an unattended boot finds `[individuation].enabled = false`, an invalid `[individuation]` section, or the `lingua` module disabled
- **THEN** condition 9 fails naming those keys, the caretaker is not sent a start notice, and the boot refuses with exit code `6`

#### Scenario: Not yet individuated
- **WHEN** an unattended boot passes every condition and the entity has not individuated
- **THEN** the boot proceeds

## MODIFIED Requirements

### Requirement: Three supervision modes with distinct selectors and refusal codes
The cycle boot SHALL resolve supervision to exactly one of three modes — `operator-present`, `research`, or `unattended` — where `unattended` is selected by `KAINE_CYCLE_UNATTENDED=1` or by `[cycle].supervision_mode = "unattended"`, with the environment taking precedence over config. The modes SHALL keep distinct refusal exit codes (`2`, `5`, `6` respectively). If more than one mode selector is active, the boot SHALL refuse as a configuration error (exit `1`) before evaluating any gate.

#### Scenario: Unattended selected by environment
- **WHEN** a boot starts with `KAINE_CYCLE_UNATTENDED=1`
- **THEN** supervision resolves to `unattended` and admission requires the nine-condition unattended gate

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
An unattended boot SHALL evaluate every condition of the research safety net through the same evaluator the research gate uses, with identical predicates: preservation enabled, welfare response wired, logging active, a real preserve→revive round-trip passing on this install, and encryption satisfied where required (conditions 1–5), and the individuation producer wired (condition 9). A condition added to the research safety net SHALL become an unattended condition in the same change; the unattended gate SHALL NOT leave any research-net condition unmapped. An unattended boot SHALL NOT engage experiment machinery, admissibility requirements, or research-run bookkeeping.

#### Scenario: A research-net condition fails
- **WHEN** an unattended boot evaluates the shared net and any of its conditions fails
- **THEN** the boot refuses with exit code `6` and the refusal names the failed condition

#### Scenario: Unattended is not a research run
- **WHEN** an unattended boot passes all nine conditions with no experiment or admissibility configuration present
- **THEN** the boot proceeds as a plain autonomous cycle with no experiment record and no admissibility requirements applied

#### Scenario: Every research-net condition is mapped
- **WHEN** the research safety net's evaluator returns its checks
- **THEN** every check it returns maps to a numbered unattended condition, and a test fails if one does not

### Requirement: Condition seven — caretaker told
An unattended boot SHALL send a content-free start notice through every channel configured under `[caretaker]`, and condition 7 SHALL pass only if at least one channel accepts it. Condition 7 SHALL run after conditions 1–6, 8 and 9 have all passed. Supported channels SHALL be a desktop notification over the session D-Bus and an HTTP POST to an endpoint whose address is loopback, private (RFC 1918 or `fc00::/7`), or in `100.64.0.0/10`. Public addresses SHALL be refused both at config validation and at send time after DNS resolution.

#### Scenario: No channel configured
- **WHEN** an unattended boot has no `[caretaker]` channel configured
- **THEN** condition 7 fails with the reason "no channel configured" and the boot refuses with exit code `6`

#### Scenario: Every channel rejects the notice
- **WHEN** every configured channel fails to accept the start notice
- **THEN** condition 7 fails, the refusal names each channel and its error, and the boot refuses with exit code `6`

#### Scenario: One channel accepts
- **WHEN** at least one configured channel accepts the start notice and conditions 1–6, 8 and 9 have passed
- **THEN** condition 7 passes and the boot proceeds

#### Scenario: Public endpoint refused
- **WHEN** an HTTP channel's host resolves to a public address at send time
- **THEN** the notice is not sent to that address and the channel counts as not accepted

### Requirement: No override skips the unattended gate
No environment variable, config key, or flag SHALL let an unattended boot proceed when any of the nine conditions fails.

#### Scenario: Override attempt ignored
- **WHEN** an unattended boot fails a condition while any skip, force, or override switch is set
- **THEN** the boot still exits `6`

### Requirement: Existing modes unchanged
Operator-present mode SHALL remain available and unchanged: `KAINE_CYCLE_OPERATOR_PRESENT=1` admits the boot, and its absence refuses with exit code `2` when no other mode is selected. Research mode SHALL keep its safety net and exit code `5`. Neither mode SHALL gain any of conditions 6–8.

#### Scenario: Operator boot unchanged
- **WHEN** an operator-present boot runs with the flag set
- **THEN** it is admitted exactly as before this change, with no Supervisor selftest, caretaker notice, or input probe

#### Scenario: Research boot unchanged
- **WHEN** a research boot fails any of its conditions
- **THEN** it refuses with exit code `5` and the same message as before this change

### Requirement: Auto-start only through a separate opt-in unit
The shipped `quadlet/kaine-cycle.container` SHALL keep no `[Install]` section. A separate `quadlet/kaine-cycle-unattended.container` SHALL set `KAINE_CYCLE_UNATTENDED=1`, carry `[Install] WantedBy=default.target`, declare `Conflicts=kaine-cycle.service`, and keep `Restart=no`. Install scripts SHALL NOT copy or enable the unattended unit.

#### Scenario: Shipped unit never auto-starts
- **WHEN** the shipped cycle unit is parsed
- **THEN** it has no `[Install]` section and no unattended selector

#### Scenario: Power-loss reboot re-verifies
- **WHEN** an enabled unattended unit starts after a power loss
- **THEN** all nine conditions are evaluated again on this boot, and nothing is assumed from a previous boot

#### Scenario: Refused gate is not retried
- **WHEN** the unattended unit's boot exits `6`
- **THEN** systemd leaves the unit failed and does not restart it, and the entity stays down
