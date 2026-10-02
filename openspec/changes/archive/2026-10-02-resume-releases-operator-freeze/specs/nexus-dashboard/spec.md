## ADDED Requirements

### Requirement: Resume releases only the operator's own freeze
The Nexus resume control SHALL remove only freeze entries whose source is `operator`. When other holders remain, the cycle SHALL stay frozen and the response and the freeze panel SHALL name the remaining holders.

#### Scenario: Resume over a welfare pause
- **WHEN** the operator resumes while `operator` and `welfare` freezes are active
- **THEN** the `operator` entry is removed, the `welfare` entry stays, the cycle stays frozen, and Nexus shows that a welfare freeze is holding it

### Requirement: Protective freezes are lifted only by a named override
Nexus SHALL lift a `welfare`, `gestation` or `programme_end` freeze only through a separate override that names each holder it lifts and is confirmed by repeating those names. It SHALL refuse to override `spot` or `preserve` freezes, which release themselves, and any unknown source. Each override SHALL append a content-free record (time, sources lifted, holders remaining) to an audit log and SHALL be refused in read-only mode.

#### Scenario: A confirmed override lifts the named welfare freeze
- **WHEN** a welfare freeze is active and the operator overrides `welfare` with the confirmation `welfare`
- **THEN** the welfare entry is removed, one audit record is written, and the cycle resumes if no other holder remains

#### Scenario: An unconfirmed override is refused
- **WHEN** the operator overrides `welfare` with a confirmation that does not name it
- **THEN** the request is refused and the welfare freeze stays
