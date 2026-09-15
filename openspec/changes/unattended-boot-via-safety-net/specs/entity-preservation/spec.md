## RENAMED Requirements

- FROM: `### Requirement: Research boot is gated on the autonomous safety net`
- TO: `### Requirement: Any boot with no human in the loop is gated on the autonomous safety net`

## MODIFIED Requirements

### Requirement: Any boot with no human in the loop is gated on the autonomous safety net
A boot that runs with no human in the loop — a research boot OR an unattended boot (selected by KAINE_CYCLE_UNATTENDED=1 or a config key) — SHALL refuse to start unless the autonomous safety net is live and verified on this install: the safeguards a human presence once stood in for must be present in the system itself and machine-verified at every boot, not vouched for by an unverifiable human claim. The required safety-net conditions are: preservation enabled, the welfare-protective response wired, full logging/admissibility active, a preflight dry snapshot→restore round-trip confirming the preservation+revive path is functional on this install, and encryption satisfied where required. An unattended boot SHALL run the same safety-net verification as a research boot and SHALL additionally verify at boot that the Spot supervisor is enabled and its freeze/recovery path is armed, refusing to start if Spot is not live — an entity SHALL NOT run unattended without the supervisor that replaces the human. The refusal SHALL be an operator-facing message with a distinct exit code (no traceback); an unattended boot SHALL refuse with its own distinct exit code, separate from the research gate's and the operator-present gate's, naming exactly which condition failed. For any boot with no human in the loop this gate REPLACES the operator-present gate; a boot is either operator-supervised or autonomous-safety-net-verified, never neither, and there is no override that skips the net. Passing this gate does not make an unattended boot a research run: it carries no experiment machinery and no research admissibility requirements. The operator-present mode remains available and unchanged for supervised and first boots; no existing refusal, exit code, or scenario changes meaning, and exit code 2 still means what it means today for a boot that selected neither research nor unattended mode.

#### Scenario: Research boot refused without a working safety net
- **WHEN** an unsupervised unattended-or-research boot is attempted and any of {preservation enabled, welfare-protective response wired, full logging active, the dry snapshot→restore self-check passing} is not satisfied
- **THEN** the boot refuses to start with an operator-facing message and a distinct exit code

#### Scenario: Research boot allowed when the safety net is verified
- **WHEN** preservation is enabled, the welfare-protective response is wired, logging/admissibility is active, and the dry round-trip self-check passes — and, for an unattended boot, the Spot supervisor is additionally live with its freeze/recovery path armed
- **THEN** the unsupervised unattended-or-research boot is allowed to proceed

#### Scenario: Unattended boot refused when the Spot supervisor is not live
- **WHEN** an unattended boot is attempted, the other safety-net conditions hold, and the Spot supervisor is not live at boot (not enabled, or its freeze/recovery path not armed)
- **THEN** the boot refuses to start with an operator-facing message and its own distinct exit code, naming the Spot supervisor condition as the one that failed

#### Scenario: Unattended boot allowed when all six safety-net conditions hold
- **WHEN** preservation is enabled, the welfare-protective response is wired, logging/admissibility is active, the dry snapshot→restore round-trip self-check passes, encryption is satisfied where required, and the Spot supervisor is enabled with its freeze/recovery path armed, verified at boot
- **THEN** the unattended boot is allowed to proceed with no human present and no operator-present claim

#### Scenario: Operator-present supervised boot still works unchanged
- **WHEN** a boot selects operator-present supervision — neither research nor unattended mode — whether or not KAINE_CYCLE_OPERATOR_PRESENT is set
- **THEN** the autonomous safety-net gate does not apply to it and its behavior is unchanged: it proceeds when the operator-present variable is set, and it still refuses with exit code 2 when it is not, with no existing refusal, exit code, or scenario changing meaning