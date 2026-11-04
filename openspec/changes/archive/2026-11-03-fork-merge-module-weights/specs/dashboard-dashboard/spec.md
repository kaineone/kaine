## ADDED Requirements

### Requirement: The merge form offers the choice of module weights
The dashboard's snapshot-merge form SHALL offer a labelled choice of which parent's module weights continue: none, A, or B. It SHALL send `module_weights_from` as `"a"` or `"b"` when A or B is chosen and leave the field out otherwise. When the merge API refuses for a missing choice, the form SHALL show the status code and the server's `detail`, which names the modules.

#### Scenario: Choosing parent B
- **WHEN** the operator chooses B for module weights and submits the merge form
- **THEN** the request body to `POST /diagnostics/merges` contains `"module_weights_from": "b"`

#### Scenario: A refusal names the modules
- **WHEN** the merge API refuses because vision's weights differ and no choice was sent
- **THEN** the form shows the status code and a detail naming vision
