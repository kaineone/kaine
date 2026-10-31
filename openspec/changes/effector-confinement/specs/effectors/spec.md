## ADDED Requirements

### Requirement: Every effector declares a confinement profile

Every effector, built-in or registered, SHALL carry a `ConfinementProfile` naming its readable paths, at most one writable directory (the effectors sandbox), its network access (`none` or `session_bus_notifications`), its device nodes, its environment allowlist, and its CPU-time, address-space, process-count and wall-time limits. No built-in profile SHALL name the state tree, the data root, the trainer jobs directory, a bus socket or a file holding a secret.

#### Scenario: Built-in profiles exclude the state tree

- **WHEN** the built-in profiles for `file_write`, `shell` and `notify` are inspected
- **THEN** none lists the state tree, the data root or the trainer jobs directory among its readable or writable paths, and only `file_write` and `shell` have a writable directory, the sandbox

### Requirement: An effector without a profile cannot be registered

`register_effector` SHALL refuse an effector that carries no confinement profile and SHALL name the effector in the error.

#### Scenario: A plugin effector without a profile is refused

- **WHEN** a plugin registers an effector that has no `confinement_profile`
- **THEN** registration raises at boot naming the effector, and the effector is not added to the effector table

### Requirement: Effector side effects run in a confined child process

The effectors module SHALL perform every effector's side effect in a child process started under that effector's profile by the confined executor, and SHALL NOT perform any effector's side effect in the cycle process. The cycle process SHALL keep the provenance check, the whitelist checks and the audit write. The executor SHALL pass the request to the child on standard input and SHALL accept a bounded result on standard output; output beyond the bound SHALL make the act fail.

#### Scenario: A file write happens in the child

- **WHEN** an enabled `file_write` act runs
- **THEN** the file is created by the executor's child process, and the cycle process opens no file under the sandbox for the act

#### Scenario: Oversized child output fails the act

- **WHEN** a whitelisted shell command writes more than the result bound to standard output
- **THEN** the act's result has `success=False` with an error naming the bound, and the audit log records the attempt

### Requirement: Effector children receive no secrets and work inside the sandbox

The child's environment SHALL contain only the variables in its profile's allowlist, and SHALL NOT contain any variable whose name starts with `KAINE_` or ends with `_KEY`, `_TOKEN` or `_PASSWORD`. The child's working directory SHALL be the sandbox. A shell whitelist entry whose `cwd` does not resolve inside the sandbox SHALL be rejected when the configuration loads, with an error naming the entry; an entry without `cwd` SHALL run in the sandbox.

#### Scenario: The state key does not reach a shell command

- **WHEN** the cycle runs with `KAINE_STATE_KEY` set and a whitelisted `env` command runs as an act
- **THEN** the command's output contains no `KAINE_STATE_KEY` entry

#### Scenario: A whitelist entry outside the sandbox is a configuration error

- **WHEN** `[effectors.shell_whitelist.<name>].cwd` names a directory outside the sandbox
- **THEN** configuration loading fails with an error naming that entry and the cycle does not start

### Requirement: Confinement blocks the filesystem and network outside the profile

Under every supported backend, a child SHALL be unable to read a file outside its profile's read paths and write directory, unable to write outside its write directory, unable to follow a symlink from inside the write directory to a target outside it for a write, and, for a profile with network `none`, unable to create an `AF_INET`, `AF_INET6`, `AF_PACKET` or `AF_NETLINK` socket. A child SHALL run with `no_new_privs` set and with the profile's resource limits applied.

#### Scenario: A shell command cannot read the entity's state

- **WHEN** a whitelisted `cat` act asks for a file under the state tree
- **THEN** the act fails with a permission or not-found error and the file's content appears nowhere in the result or the audit record

#### Scenario: A planted symlink is not followed

- **WHEN** a symlink inside the sandbox points to a file outside it and a `file_write` act targets the symlink's name
- **THEN** the act fails and the target outside the sandbox is unchanged

#### Scenario: No network for the built-in shell profile

- **WHEN** a whitelisted command run as an act tries to open a TCP connection to the bus address
- **THEN** socket creation fails inside the child and no connection is made

### Requirement: Boot chooses the strongest backend that satisfies the profiles

When `[effectors].enabled_effectors` is not empty, boot SHALL choose the first backend, in the order `bwrap`, `landlock-seccomp`, `systemd-run`, that satisfies every enabled effector's profile on this host. If none does, boot SHALL refuse with the confinement refusal code and name the missing kernel or runtime features.

#### Scenario: No backend available

- **WHEN** `enabled_effectors` is not empty and the host supports none of the three backends
- **THEN** the boot refuses with the confinement refusal code and names the missing features

### Requirement: Enabling an effector requires a passing confinement self-test

Before the effectors module starts, boot SHALL run the confinement self-test for each enabled effector under the chosen backend: secret absence, state-tree read denial, write confinement, symlink refusal, network denial, process and CPU limits, and for `notify` the session-bus filter. A failed probe SHALL refuse the boot with the confinement refusal code naming the effector, backend and probe. A pass SHALL be recorded in the research event log with the backend and the profile digest.

#### Scenario: A failed probe stops the boot

- **WHEN** `enabled_effectors = ["shell"]` and the chosen backend lets the self-test child read a file under the state tree
- **THEN** the boot refuses with the confinement refusal code naming `shell`, the backend and the state-read probe

#### Scenario: A pass is recorded

- **WHEN** every probe passes for every enabled effector
- **THEN** the research event log holds one record naming the backend and the profile digest, and the effectors module starts

### Requirement: The gates require verified confinement when effectors are on

The research gate and the unattended gate SHALL hold the condition `effector_confinement_verified`. It SHALL be satisfied when the effectors module is off, and otherwise only when this boot's confinement self-test passed for every enabled effector.

#### Scenario: The research gate requires the self-test when effectors are on

- **WHEN** a research run's module set includes the effectors module and this boot's self-test has not passed
- **THEN** the research gate does not open and names `effector_confinement_verified`

#### Scenario: The module off needs no self-test

- **WHEN** `[modules].effectors = false`
- **THEN** no self-test runs and `effector_confinement_verified` is satisfied

### Requirement: Audit records name the confinement that ran the act

Each effectors audit record for an act that reached an effector SHALL include `confinement_backend` and `profile_digest`. The child SHALL have no write access to the audit log.

#### Scenario: Audit record carries the backend

- **WHEN** an act runs under the `landlock-seccomp` backend
- **THEN** its audit record has `confinement_backend = "landlock-seccomp"` and a non-empty `profile_digest`, and the hash chain still verifies
