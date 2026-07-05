## MODIFIED Requirements

### Requirement: A real weight merge is the default when possible

The lineage merge path SHALL use the real TIES/DARE adapter merger by default when
the PEFT extra is present, performing an actual weight merge of the two parents'
trained adapters. The no-op `FakeAdapterMerger` SHALL be used only as an explicit
development or no-extra fallback. When the extra is absent and both parents carry
trained adapters, the system SHALL continue to fail loud (raise rather than silently
union), and the error message SHALL name the extra required to enable a real merge.

#### Scenario: Real merge runs when the extra is present

- **WHEN** two parents with trained adapters are merged and the PEFT extra is installed
- **THEN** a real TIES/DARE weight merge is performed, not a path-list union

#### Scenario: Fail loud when a real merge is impossible

- **WHEN** two parents with trained adapters are merged and the PEFT extra is absent
- **THEN** the merge raises rather than silently unioning
- **AND** the error names the extra to install
