## ADDED Requirements

### Requirement: Topos habituation and encoder revision follow configuration
The composition root SHALL build Topos's habituator with `[topos].habituation_window` when it is set; the window SHALL be an integer of at least 2. `[topos].encoder_revision`, when set, SHALL equal the InternVideo-Next loader's pinned revision; any other value SHALL refuse boot with a configuration error naming the configured and pinned revisions, because the pin decides which vendored code and weights load.

#### Scenario: The habituation window is applied
- **WHEN** `[topos].habituation_window = 8`
- **THEN** Topos's habituator keeps a rolling window of 8 embeddings

#### Scenario: An unpinned revision is refused
- **WHEN** `[topos].encoder_revision` names a revision other than the pinned one
- **THEN** boot refuses with a configuration error naming both revisions, and no encoder is loaded
