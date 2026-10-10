# Echo

Echo is KAINE's built-in test module. It records every broadcast snapshot it receives and publishes a single `echo.ping` event on demand, so that tests can check the broadcast path and module registration. Echo is test infrastructure and plays no part in the architecture. This page is for contributors who write or debug cycle and bus tests, and for operators who want to know why the module ships disabled.

## What Echo does

`EchoModule` is a ground-truth observer for the path from the bus through the cycle to Syneidesis. It receives every [broadcast snapshot](../08-cognitive-cycle/global-workspace.md) through `on_workspace(snapshot)` and appends it to an in-memory list. Its `publish_one()` method publishes one `echo.ping` event when a test calls it, with a default intensity of 0.7. The end-to-end test `tests/test_phase_1_endtoend.py` and the cycle subsystem test `tests/systems/test_cycle_subsystem.py` use Echo to confirm that the workspace broadcasts and that [modules](./README.md) register. Echo has no OpenSpec change of its own.

## Inputs and outputs

| Source | Handler | Result |
|---|---|---|
| `workspace.broadcast` | `on_workspace(snapshot)` | Appends the snapshot to `self.snapshots` |

| Stream | Event | When published |
|---|---|---|
| `echo.out` | `echo.ping` | Only when `publish_one()` is called |

## Configuration

| Key | Type | Default | Meaning |
|---|---|---|---|
| `[modules].echo` | bool | `false` | Off in the shipped `config/kaine.toml` and in every shipped profile |

`EchoModule` also takes an optional `message_label` constructor argument. It defaults to `"echo"` and sets the `label` field of `echo.ping` payloads. `serialize()` records the label and the number of snapshots seen.

## Files

| File | Role |
|---|---|
| `kaine/modules/echo.py` | The `EchoModule` class |

## Configuration guard

`tests/test_setup_wizard.py` and `tests/test_ignition_study_overlay.py` assert that the configurations they build keep `[modules].echo = false`. A failure in either test means that a wizard-written configuration or a study overlay has turned on test infrastructure.
