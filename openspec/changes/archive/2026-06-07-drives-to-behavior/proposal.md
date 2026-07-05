## Why

Thymos computes four drives (curiosity, boredom, social_drive, restlessness)
and publishes `thymos.drive` threshold-crossing events — but **no module
consumes them** (audit finding #3). The entity has motivations that cannot move
it. Now that the executive action layer exists (`executive-action-intent`), a
drive crossing is exactly an *impulse*: the paper frames executive inhibition as
what "prevents the system from acting on every impulse" (§37). So a drive
crossing that reaches the non-inhibited conscious coalition should be able to
move the entity to act — to deliberate, or to reach out — via the same
inhibition-gated intent path.

## What Changes

- A `DriveBiasedActionSelectionPolicy` (injected into Volition in place of the
  default) that, on a **non-inhibited** snapshot, in addition to responding to
  user communication, forms intents from `thymos.drive` crossing events present
  in the conscious coalition:
  - `social_drive` crossing → a `speak` intent (the entity is moved to reach
    out / engage) — subject to the one-speak-in-flight guard.
  - `curiosity` / `boredom` / `restlessness` crossing → a `think` intent
    (internal deliberation / self-stimulation) — internal speech that never
    reaches TTS or external interfaces, subject to a one-think-in-flight guard.
- **Priority:** responding to a present user utterance takes precedence over a
  drive-initiated `speak` (one `speak` intent per tick).
- Still fully gated by Syneidesis inhibition (Volition checks `inhibited` first)
  and the no-self-response guard — drives bias *what* the entity is disposed to
  do, they do not bypass the executive gate.
- An optional `[volition].drive_initiative` knob (default on) to disable
  drive-initiated intents; reported for the operator to add to config.

## Capabilities

### Modified Capabilities

- `action-selection`: the action-selection policy additionally turns drive
  threshold-crossings in the non-inhibited coalition into intents (social → speak
  initiative; curiosity/boredom/restlessness → internal deliberation), closing
  the drive→behavior loop.

## Impact

- **Code**: new `DriveBiasedActionSelectionPolicy` (in `kaine/workspace/`),
  injected via `kaine/boot.py`. No change to Thymos (it already emits the
  crossings) or to the inhibition gate.
- **Tests**: unit tests (fakes) for drive→intent mapping, inhibition still
  gating, user-response priority, and in-flight guards.
- **Config**: optional `[volition].drive_initiative` (default on) — reported,
  not auto-added.
