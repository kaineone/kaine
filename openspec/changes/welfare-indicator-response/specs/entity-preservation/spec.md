## MODIFIED Requirements

### Requirement: Research boot is gated on the autonomous safety net
An unsupervised research boot SHALL refuse to start unless the autonomous safety
net is live and verified, because the research phase runs with no human in the
loop and the safeguards must be present in the system itself. The required conditions
are: preservation enabled, the welfare-protective response wired, the welfare
response to the A.4 indicators wired (`[preservation.welfare_response].enabled` and
`[preservation.welfare_response.indicators].enabled` true, the affect and sleep
modules enabled, and the action `pause` or `end`), full logging/admissibility
active, a preflight dry snapshot→restore round-trip confirming the
preservation+revive path is functional on this install, the configured encryption
contract satisfied where encryption is required, the individuation producer
enabled, and the module supervisor armed and self-tested (`[supervisor].enabled`
true, a restart ladder of at least one rung, writable escalation and incident-log
paths, and a passing supervisor self-test within `selftest_timeout_s`, evaluated by
the same function as unattended condition 6 before any entity module is
constructed). The refusal SHALL be an operator-facing message that names each
failed condition and its reason, with a distinct exit code (no traceback). For
research this gate REPLACES the operator-present gate; a run is either
operator-supervised or autonomous-safety-net-verified, never neither.

#### Scenario: Research boot refused without a working safety net
- **WHEN** an unsupervised research boot is attempted and any of {preservation enabled, welfare-protective response wired, indicator response wired, full logging active, the dry snapshot→restore self-check passing, encryption satisfied, individuation producer enabled, supervisor armed and self-tested} is not satisfied
- **THEN** the boot refuses to start with an operator-facing message and a distinct exit code

#### Scenario: Research boot allowed when the safety net is verified
- **WHEN** every condition holds, including a supervisor self-test that passes and a wired indicator response
- **THEN** the unsupervised research boot is allowed to proceed

#### Scenario: A research boot with the supervisor off
- **WHEN** a research boot finds `[supervisor].enabled = false`
- **THEN** the boot refuses with exit code 5 and the message names the supervisor condition with the reason "not enabled"

#### Scenario: A failing supervisor self-test
- **WHEN** the supervisor section is valid but its self-test does not complete within its bounded window
- **THEN** the boot refuses with exit code 5, the message gives the self-test's reason, and no entity module was constructed

#### Scenario: A research boot without the indicator response
- **WHEN** a research boot has the welfare response enabled but its indicators disabled, or the affect or sleep module disabled, or the action `notify`
- **THEN** the boot refuses with exit code 5 and the message names the indicator response and the part that failed

## ADDED Requirements

### Requirement: The research gate bounds the indicator settings
The indicator response SHALL count as wired only when its settings can act: `posterior_bar` below 1, `unavailable_escalate_s` at most the affect span `T_lp`, `rest_start_timeout_s` at most `unavailable_escalate_s`, and each `rest_complete_timeout_s` bound at most 21600 s. A setting outside these bounds SHALL refuse the research and unattended boot with a reason naming the setting.

#### Scenario: An unreachable bar
- **WHEN** a research boot sets `posterior_bar = 1.0`
- **THEN** the boot refuses with exit code 5 and the reason names `posterior_bar`

#### Scenario: A silence bound that never fires
- **WHEN** a research boot sets `unavailable_escalate_s = 1e9`
- **THEN** the boot refuses with exit code 5 and the reason names `unavailable_escalate_s` and the span
