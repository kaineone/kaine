## ADDED Requirements

### Requirement: Boot fails closed when voice-alignment is enabled, operator-approved, and training extras are missing

`_resolve_trainer` SHALL raise `VoiceAlignmentConfigError` when all three
conditions hold simultaneously: `voice_alignment.enabled=True`, the
`KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED` environment variable is set, and the
`[training]` extras (`unsloth`, `trl`, `peft`, `datasets`) are not importable.
Silently returning `None` (and thus installing `FakeTrainer`) in this
configuration would let training cycles appear to succeed while writing no real
adapter — a pretend process.

The error message SHALL name the missing extras and provide the install command
(`.venv/bin/pip install 'kaine[training]'`) and the alternative (disable
`voice_alignment` in config).

The following paths remain unchanged:

- `voice_alignment.enabled=False` → `_resolve_trainer` returns `None` (honest: training not in play)
- `voice_alignment.enabled=True` AND operator approval NOT set → returns `None` (honest: awaiting approval)
- `voice_alignment=None` → returns `None` (not configured)

#### Scenario: Boot raises when enabled + approved + extras missing

- **WHEN** `voice_alignment.enabled=True`
- **AND** `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`
- **AND** the `[training]` extras are not installed
- **THEN** `_resolve_trainer` raises `VoiceAlignmentConfigError` with a message
  naming the missing extras and the install command
- **AND** `Hypnos` is not constructed with a `FakeTrainer`

#### Scenario: Disabled path returns None honestly

- **WHEN** `voice_alignment.enabled=False`
- **THEN** `_resolve_trainer` returns `None` regardless of operator approval or extras

#### Scenario: Unapproved path returns None honestly

- **WHEN** `voice_alignment.enabled=True` AND `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED`
  is not set
- **THEN** `_resolve_trainer` returns `None`
