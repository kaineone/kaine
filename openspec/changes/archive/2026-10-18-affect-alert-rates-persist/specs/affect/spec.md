## ADDED Requirements

### Requirement: The running affect estimates survive a restore
`Affect.serialize()` SHALL store the perceptual alert rates under `alert_rates` (`fast` and `slow`, in alerts per entity second), the per-source learning-progress error means under `error_means` (for each source its fast and slow time-decayed sums and counts), the intent rate under `intent_rate`, the last wellness under `wellness` and whether an interaction has been seen under `interaction_seen`. `deserialize()` SHALL restore each value that is present, finite and in range, SHALL take the restore time as each restored source's latest report time, and SHALL keep the constructor default for a missing or invalid value. No timestamp SHALL be stored.

#### Scenario: The alert rates and error means round-trip
- **WHEN** a module has received perceptual reports and alerts, is serialized, and a new module deserializes the state
- **THEN** the new module's alert rates, error means, intent rate, wellness and interaction flag equal the first module's
- **AND** its learning progress and alert excess on the next update at the same entity time equal the first module's

#### Scenario: A restore does not relieve boredom
- **WHEN** a module has settled on a steady base rate of alerts with boredom above its threshold and an active boredom goal, is serialized and restored, and the same base-rate alerts continue
- **THEN** the alert excess stays at 0, boredom is not relieved by them, and the boredom goal is not abandoned

#### Scenario: Older state still restores
- **WHEN** the restored state has none of the new keys, or has non-numeric or negative values for them
- **THEN** `deserialize()` raises nothing, the other saved fields are restored, and the missing or invalid estimates keep their constructor defaults
