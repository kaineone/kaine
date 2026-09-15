## ADDED Requirements

### Requirement: Spot supervisor verified as a precondition of unattended boot

The Spot supervisor SHALL be a verified precondition of any unattended boot. Before the
entity is constructed, an unattended boot SHALL verify both that the Spot supervisor is
enabled in configuration AND that its freeze/recovery path is actually armed on this
install — liveness detection active and the freeze-on-failure, snapshot-before-restart
recovery path reachable — rather than merely declared enabled in configuration. If either
verification fails, the boot SHALL refuse before the entity is constructed, with an
operator-facing message that names the Spot supervisor and the specific condition that
failed. This precondition SHALL NOT apply to operator-supervised boots, in which the human
operator is the supervisor; operator-supervised boots SHALL proceed unchanged whether or
not Spot is enabled or armed.

#### Scenario: Spot disabled refuses unattended boot
- **WHEN** a boot is started in unattended mode and the Spot supervisor is disabled in configuration
- **THEN** the boot refuses before the entity is constructed, with an operator-facing message naming the Spot supervisor and its disabled state as the failed condition, and no entity is constructed or run

#### Scenario: Spot enabled but freeze path unarmed refuses unattended boot
- **WHEN** a boot is started in unattended mode, the Spot supervisor is enabled in configuration, but the armed-state verification determines that the freeze/recovery path is not actually armed (for example, liveness detection or the freeze-on-failure recovery path is not wired on this install)
- **THEN** the boot refuses before the entity is constructed, with an operator-facing message naming the Spot supervisor and the unarmed freeze/recovery path as the failed condition

#### Scenario: Spot armed allows unattended boot
- **WHEN** a boot is started in unattended mode, the Spot supervisor is enabled, and the freeze/recovery path is verified armed on this install
- **THEN** the Spot precondition passes and the boot proceeds to construct the entity and run unattended

#### Scenario: Operator-supervised boot unaffected
- **WHEN** a boot runs under operator supervision (the human operator is the supervisor) and the Spot supervisor is disabled or its freeze/recovery path is unarmed
- **THEN** the unattended Spot precondition is not applied, the boot is not refused on account of Spot, and existing operator-supervised boot behavior is unchanged