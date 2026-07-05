## ADDED Requirements

### Requirement: Backend is disclosed on every phantasia.* event

Every `phantasia.*` event payload SHALL include a `"backend"` field naming the
world-model backend that produced the signal (`"fake"` or `"dreamerv3"`).
This requirement applies to `phantasia.world_error`, `phantasia.scenario`, and
any future `phantasia.*` event types.

The `backend = "fake"` config option SHALL be documented as a non-learning EMA
stub (not a world model) in `config/kaine.toml` so operators understand what
the shipped default produces.

#### Scenario: world_error discloses backend
- **WHEN** Phantasia publishes `phantasia.world_error`
- **THEN** the payload includes `"backend"` matching the configured backend name

#### Scenario: scenario discloses backend
- **WHEN** Phantasia generates and publishes `phantasia.scenario`
- **THEN** the payload includes `"backend"` matching the configured backend name

#### Scenario: fake backend is documented as a non-learning stub
- **WHEN** `config/kaine.toml` is inspected
- **THEN** the `[phantasia]` section contains a comment distinguishing
  `backend = "fake"` (EMA stub, no learning) from `backend = "dreamerv3"`
  (real RSSM with trained latents)
