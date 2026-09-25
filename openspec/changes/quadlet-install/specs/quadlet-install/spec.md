## ADDED Requirements

### Requirement: Units are rendered for the checkout's location
The shipped quadlet units SHALL NOT contain a host path to the checkout; host-path mounts SHALL use the placeholder `@KAINE_ROOT@`. `scripts/install-quadlet.sh` SHALL render the units into the user's quadlet directory with the placeholder replaced by the checkout's absolute path, and SHALL refuse a path containing characters outside `A-Za-z0-9._/+-`.

#### Scenario: Checkout outside the home projects directory
- **WHEN** the script runs from a checkout at `/srv/kaine`
- **THEN** the installed cycle and Nexus units mount `/srv/kaine/config/...` and contain no placeholder

#### Scenario: Unsafe path refused
- **WHEN** the checkout path contains a space, `%`, `$`, `:` or a quote
- **THEN** the script exits non-zero naming the path and writes nothing

### Requirement: Installation refuses an incomplete checkout
The script SHALL refuse to install, writing nothing, when `config/kaine.operator.toml`, `config/secrets.toml` or `compose/.env` is missing, and SHALL name the step that creates each missing file.

#### Scenario: Bus credentials not bootstrapped
- **WHEN** `compose/.env` does not exist
- **THEN** the script exits non-zero, names `scripts/redis-bootstrap.sh`, and installs no unit

### Requirement: Installation never enables the entity
The script SHALL NOT install any unit whose file name contains `unattended`, and SHALL NOT enable, start or restart any unit.

#### Scenario: Unattended unit present in the checkout
- **WHEN** `quadlet/` contains an unattended cycle unit
- **THEN** it is not written to the destination

### Requirement: Units receive secrets from the bootstrap env file
Every unit that expands a `${...}` variable SHALL load `@KAINE_ROOT@/compose/.env` through `[Service] EnvironmentFile=`, so systemd has the values at every start, including after a reboot, and no secret is copied into the unit or any other file.

#### Scenario: Reboot
- **WHEN** the host reboots with linger enabled
- **THEN** Redis starts with the password from `compose/.env` without any shell `export`

### Requirement: The cycle unit receives the operator's presence claim
The cycle unit SHALL pass `KAINE_CYCLE_OPERATOR_PRESENT` from the service environment into the container, SHALL keep no `[Install]` section, and SHALL keep `Restart=no`.

#### Scenario: Documented supervised start
- **WHEN** the operator runs `systemctl --user set-environment KAINE_CYCLE_OPERATOR_PRESENT=1` and starts the cycle unit
- **THEN** the cycle receives the claim and boots

#### Scenario: No claim
- **WHEN** the cycle unit starts without the claim in its environment
- **THEN** the cycle refuses with exit code 2
