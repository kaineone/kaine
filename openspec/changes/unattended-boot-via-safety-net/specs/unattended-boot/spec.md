## ADDED Requirements

### Requirement: Three supervision modes with distinct selectors and refusal codes
The cycle boot SHALL resolve supervision to exactly one of three modes — `operator-present`, `research`, or `unattended` — where `unattended` is selected by `KAINE_CYCLE_UNATTENDED=1` or by the supervision-mode config key set to `unattended` with the environment taking precedence; the three modes SHALL keep distinct refusal exit codes (`2`, `5`, `6` respectively); and if more than one selector is active the boot SHALL refuse as a misconfiguration before any gate evaluation, using the generic configuration-error exit and not `2`, `5`, or `6`.

#### Scenario: Unattended selected by environment
- **WHEN** a boot starts with `KAINE_CYCLE_UNATTENDED=1`
- **THEN** supervision resolves to `unattended` and admission requires the six-condition unattended gate

#### Scenario: Default path unchanged
- **WHEN** a boot selects neither research nor unattended
- **THEN** operator-present semantics apply and a missing or invalid presence claim refuses with exit code `2`

#### Scenario: Conflicting selectors
- **WHEN** `KAINE_CYCLE_OPERATOR_PRESENT=1` and `KAINE_CYCLE_UNATTENDED=1` are both set
- **THEN** the boot refuses before evaluating any gate, with the generic configuration-error exit and not with `2`, `5`, or `6`

### Requirement: Unattended reuses the research safety net without research machinery
An unattended boot SHALL evaluate the same five safety-net conditions as research mode — preservation enabled, welfare response wired, logging active, dry preserve→revive self-check passed on this install, encryption satisfied — through the same evaluator as `research_gate.py` with identical predicates and no override that skips any condition; and an unattended boot SHALL NOT engage experiment machinery, admissibility requirements, or research-run bookkeeping.

#### Scenario: Five-condition failure refuses unattended
- **WHEN** an unattended boot evaluates the shared net and any of the five conditions fails
- **THEN** the boot refuses with exit code `6` and the refusal names the failed condition

#### Scenario: Unattended is not a research run
- **WHEN** an unattended boot passes all six conditions
- **THEN** the boot proceeds as a plain autonomous cycle with no experiment record and no admissibility requirements applied

### Requirement: Unattended gate adds condition six: Spot live and freeze armed
An unattended boot SHALL additionally require, verified at boot, that the Spot supervisor is enabled and live and that its freeze/recovery path is armed — freeze hook armed, restart ladder of at least one rung, escalation target configured, and incident log writable — and there SHALL be no override that skips this check; if Spot is not live or not armed, the unattended boot SHALL refuse.

#### Scenario: Spot unreachable
- **WHEN** the supervisor control plane does not answer the status handshake within the bounded startup grace
- **THEN** condition 6 fails and the boot refuses with exit code `6`, naming the Spot condition and the observed reason

#### Scenario: Spot live but not armed
- **WHEN** Spot answers the handshake but reports the freeze hook disarmed, an empty restart ladder, a missing escalation target, or an unwritable incident log
- **THEN** condition 6 fails and the boot refuses with exit code `6`

#### Scenario: Spot selftest fails
- **WHEN** Spot reports itself armed but its freeze/recovery selftest does not pass within the bounded window
- **THEN** condition 6 fails and the boot refuses with exit code `6`

### Requirement: Spot verification without starting the entity
The condition-6 check SHALL be performed entirely through the supervisor control plane — a status handshake plus Spot's selftest against Spot's own internal probe — before any entity runtime is constructed; the check SHALL NOT start the entity, import or instantiate entity modules, read or write entity state, or issue a freeze against any live supervised target.

#### Scenario: Cold gate
- **WHEN** the unattended gate performs the Spot check
- **THEN** no entity process is started and no entity state is read or written

#### Scenario: Replacement boot with a live supervised entity
- **WHEN** the gate runs while Spot is already supervising a live entity
- **THEN** the selftest still exercises only Spot's internal probe and the live entity is never frozen or restarted by the gate

### Requirement: Unattended refusal exits six and names every failed condition
An unattended gate refusal SHALL exit with code `6`, distinct from `2` (operator-present claim) and `5` (research net), regardless of which condition or conditions failed; the refusal output SHALL name every failed condition by number and name; no other boot outcome SHALL use exit code `6`; and the boot SHALL NOT fall back to another supervision mode after an unattended gate failure.

#### Scenario: Single failure
- **WHEN** only the dry self-check (condition 4) fails
- **THEN** the boot exits `6` and the refusal names condition 4

#### Scenario: Multiple failures
- **WHEN** the logging condition (3) and the Spot condition (6) both fail
- **THEN** the boot exits `6` and the refusal names both conditions

#### Scenario: No fallback
- **WHEN** the unattended gate fails for any reason
- **THEN** the boot refuses with `6` and never re-classifies itself as operator-present or research

### Requirement: Operator-present mode remains unchanged
Operator-present supervision SHALL remain available and behaviorally unchanged: selection via `KAINE_CYCLE_OPERATOR_PRESENT=1`, refusal with exit code `2` when the claim is absent or invalid, and no new verification requirements introduced by this change.

#### Scenario: Claim gate unchanged
- **WHEN** a boot that selected neither research nor unattended runs without a valid `KAINE_CYCLE_OPERATOR_PRESENT=1` claim
- **THEN** it refuses with exit code `2` exactly as it does today

#### Scenario: No new burden on operator boots
- **WHEN** an operator-present boot runs with the claim set
- **THEN** it is admitted exactly as today, with no Spot check or safety-net verification added

### Requirement: Quadlet auto-start only for unattended
`kaine-cycle.container` SHALL include an `[Install]` section only when its environment selects unattended mode, and SHALL NOT include `[Install]` while it selects operator-present or research; an unattended deployment intended to survive power loss SHALL include `[Install]` so systemd starts the unit at boot.

#### Scenario: Unattended container file
- **WHEN** `kaine-cycle.container` sets `KAINE_CYCLE_UNATTENDED=1`
- **THEN** it carries an `[Install]` section so a power-loss reboot starts the unit and re-runs the gate

#### Scenario: Operator-present container file
- **WHEN** `kaine-cycle.container` relies on `KAINE_CYCLE_OPERATOR_PRESENT=1`
- **THEN** it has no `[Install]` section and is started by a human

### Requirement: Power-loss reboot re-verifies the net
On a boot-time start after power loss, an unattended boot SHALL run the full six-condition verification again on this install; the entity SHALL NOT run on the assumption that the net was live at any previous boot; and the unit SHALL NOT automatically restart after a gate refusal.

#### Scenario: Net not live at reboot
- **WHEN** power is restored, systemd starts the unattended unit, and the Spot control plane does not become reachable within the bounded grace
- **THEN** the boot refuses with exit code `6`, the unit is left failed, and the entity remains down

#### Scenario: Net live at reboot
- **WHEN** power is restored, the unattended unit starts, and all six conditions pass
- **THEN** the entity boots unattended with no human present and no operator-present claim

### Requirement: Unattended unit ordering with bounded handshake grace
The unattended quadlet SHALL order the cycle unit after the Spot supervisor unit, and the gate's Spot handshake SHALL use a bounded, configurable startup grace after which an unreachable supervisor fails condition 6.

#### Scenario: Supervisor still starting
- **WHEN** systemd starts the spot unit and the cycle unit together and Spot answers within the grace
- **THEN** the handshake succeeds once Spot responds and the gate continues

#### Scenario: Grace expires
- **WHEN** Spot does not answer within the configured grace
- **THEN** the gate stops waiting, fails condition 6, and the boot refuses with exit code `6`