## ADDED Requirements

### Requirement: The cycle's log level comes from configuration
The cognitive cycle SHALL set its root log level from `[logging].level` after loading its configuration. Accepted values SHALL be `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`, case-insensitive; when the key is absent the level SHALL be `INFO`. Any other value SHALL make the cycle refuse to boot with "kaine.cycle: configuration error: <message>" and a non-zero exit, without a traceback.

#### Scenario: A configured level is applied
- **WHEN** `[logging].level = "debug"`
- **THEN** the cycle's root logger level is DEBUG

#### Scenario: An unknown level refuses boot
- **WHEN** `[logging].level = "LOUD"`
- **THEN** the cycle exits non-zero with a configuration error naming the key and the accepted values
