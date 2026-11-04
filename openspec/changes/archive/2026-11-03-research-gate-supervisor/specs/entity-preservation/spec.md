## MODIFIED Requirements

### Requirement: Research boot is gated on the autonomous safety net
An unsupervised research boot SHALL refuse to start unless the autonomous safety
net is live and verified, because the research phase runs with no human in the
loop and the safeguards must be present in the system itself. The required conditions
are: preservation enabled, the welfare-protective response wired, full
logging/admissibility active, a preflight dry snapshot→restore round-trip
confirming the preservation+revive path is functional on this install, the
configured encryption contract satisfied where encryption is required, the
individuation producer enabled, and the module supervisor armed and self-tested
(`[supervisor].enabled` true, a restart ladder of at least one rung, writable
escalation and incident-log paths, and a passing supervisor self-test within
`selftest_timeout_s`, evaluated by the same function as unattended condition 6
before any entity module is constructed). The refusal SHALL be an operator-facing
message that names each failed condition and its reason, with a distinct exit code
(no traceback). For research this gate REPLACES the operator-present gate; a run is
either operator-supervised or autonomous-safety-net-verified, never neither.

#### Scenario: Research boot refused without a working safety net
- **WHEN** an unsupervised research boot is attempted and any of {preservation enabled, welfare-protective response wired, full logging active, the dry snapshot→restore self-check passing, encryption satisfied, individuation producer enabled, supervisor armed and self-tested} is not satisfied
- **THEN** the boot refuses to start with an operator-facing message and a distinct exit code

#### Scenario: Research boot allowed when the safety net is verified
- **WHEN** every condition holds, including a supervisor self-test that passes
- **THEN** the unsupervised research boot is allowed to proceed

#### Scenario: A research boot with the supervisor off
- **WHEN** a research boot finds `[supervisor].enabled = false`
- **THEN** the boot refuses with exit code 5 and the message names the supervisor condition with the reason "not enabled"

#### Scenario: A failing supervisor self-test
- **WHEN** the supervisor section is valid but its self-test does not complete within its bounded window
- **THEN** the boot refuses with exit code 5, the message gives the self-test's reason, and no entity module was constructed
