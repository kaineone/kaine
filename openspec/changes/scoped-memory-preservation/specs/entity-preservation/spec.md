## ADDED Requirements

### Requirement: A preservation bundle holds only the preserved being's memories
Preservation SHALL capture only the preserved being's own memory collections (its collection prefix and memory kinds, and its own Empatheia collection), whatever else the memory server holds. Revive SHALL restore each preserved memory kind into the reviving being's own collections, replacing their contents with exactly the preserved points, and SHALL never write into a collection that is not the reviving being's own.

#### Scenario: Two beings on one memory server
- **WHEN** a being with collection prefix `a_` is preserved while a being with prefix `b_` has memories on the same server
- **THEN** the bundle contains no `b_` collection

#### Scenario: Reviving under another prefix
- **WHEN** a bundle preserved under prefix `a_` is revived by a being whose prefix is `c_`
- **THEN** the memories are restored into the `c_` collections, the `a_` and `b_` collections are unchanged, and any points already in the `c_` collections are replaced

#### Scenario: An older bundle that swept other collections
- **WHEN** a bundle containing another being's collections is revived
- **THEN** only the bundle's own memory kinds are restored, and the other collections are skipped and named in the log
