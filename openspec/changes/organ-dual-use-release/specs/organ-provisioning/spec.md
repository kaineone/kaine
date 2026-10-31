## ADDED Requirements

### Requirement: A gated organ download fails honestly with guidance

When `hf download` of the organ fails because the repository is gated and access has not been granted, the organ download SHALL report `ok=False`, download nothing, record no revision, and print the repository's agreement page, the login step and the retry command. It SHALL NOT ask for, store, log or print a token.

#### Scenario: Agreement not yet accepted

- **WHEN** the operator consents to the organ download and the repository returns an access error
- **THEN** the step reports failure with the agreement and login guidance, and no organ file or revision state is written

### Requirement: A local organ file is accepted only with a matching digest

The wizard SHALL accept an operator-supplied local organ GGUF only when its SHA-256 equals `[language].model_sha256`. A mismatch SHALL be refused, naming both digests.

#### Scenario: Matching local file

- **WHEN** the operator points the wizard at a local GGUF whose SHA-256 equals `[language].model_sha256`
- **THEN** the wizard places it at the served organ path and records the digest as the organ's provenance

#### Scenario: Mismatched local file

- **WHEN** the local file's SHA-256 differs from `[language].model_sha256`
- **THEN** the wizard refuses, prints both digests, and leaves the served organ path unchanged
