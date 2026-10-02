## ADDED Requirements

### Requirement: The merge form offers the world-model choice and shows refusal reasons
The dashboard's snapshot-merge form SHALL offer a labelled choice of which parent's Phantasia world model continues: none, A, or B. It SHALL send `world_model_from` as `"a"` or `"b"` when A or B is chosen and leave the field out otherwise. When the merge API answers with an error, the form SHALL show the status code and the server's `detail` text. The form SHALL NOT offer `allow_unmerged_adapters`.

#### Scenario: Choosing parent B's world model
- **WHEN** the operator enters two snapshot ids, chooses B under "world model from" and confirms the merge
- **THEN** the request body to `POST /diagnostics/merges` contains `"world_model_from": "b"`

#### Scenario: No choice leaves the field out
- **WHEN** the operator leaves "world model from" at none and confirms the merge
- **THEN** the request body contains no `world_model_from` key

#### Scenario: A refusal shows its reason
- **WHEN** the merge API answers `409` with detail "both parents carry a Phantasia world model; ..."
- **THEN** the form's status shows `409` and that detail text
