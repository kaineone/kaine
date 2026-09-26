## ADDED Requirements

### Requirement: Preservation carries the embedding space and revive refuses to mix spaces
A preserved being's memory state SHALL include the embedding-space stamp of the vectors it holds. Revive and fork merge SHALL refuse a memory state whose embedding space differs from the running embedder's, rather than importing its vectors. A memory state without a stamp SHALL be treated as `sentence-transformers/all-MiniLM-L6-v2`.

#### Scenario: Revive onto a different embedder
- **WHEN** a being preserved with one embedding space is revived where the embedder has another
- **THEN** the revive is refused with an error naming both spaces and no memory is imported

#### Scenario: Revive of an older bundle
- **WHEN** a bundle from before stamping is revived with the MiniLM-L6-v2 embedder on either backend
- **THEN** its memories are imported unchanged
