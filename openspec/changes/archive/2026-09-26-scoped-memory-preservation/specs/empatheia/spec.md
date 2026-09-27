## ADDED Requirements

### Requirement: Empatheia preserves its own agent profiles
Empatheia SHALL capture every agent profile it holds (in its store, not only those cached since boot) in preservation, and a revived Empatheia SHALL restore exactly those profiles into its own configured collection, re-embedding them with the running embedder. A failure to read the profiles SHALL fail the preservation.

#### Scenario: Profiles not touched since boot
- **WHEN** Empatheia is preserved holding profiles that were stored before this boot and not read since
- **THEN** those profiles are in the bundle and are restored on revive
