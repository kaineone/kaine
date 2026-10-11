## ADDED Requirements

### Requirement: Recent points rank a non-finite timestamp as zero
`MemoryStorage.recent_points()` SHALL rank a point whose payload timestamp is
missing, unparseable, NaN or infinite as if its timestamp were 0.0, on the
in-memory, sqlite-vec and Qdrant backends alike.

#### Scenario: Non-finite timestamps rank as the oldest
- **WHEN** a collection holds points with finite positive timestamps and
  points with NaN, positive infinite and negative infinite timestamps
- **THEN** `recent_points()` returns the finite points first, newest first,
  on every backend
