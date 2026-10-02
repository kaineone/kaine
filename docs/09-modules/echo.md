# Echo

Echo is KAINE's built-in test module. It records workspace snapshots and emits a single `echo.ping` event on demand so tests can verify the broadcast path and module registration. The page covers Echo's inputs, outputs, configuration, and safety gate. It is for contributors writing or debugging cycle and bus tests, and for operators reviewing why the module ships disabled.

## What Echo does

`EchoModule` is a ground-truth observer for the bus, cycle, and Syneidesis path. It receives every [global workspace](../08-cognitive-cycle/global-workspace.md) broadcast through `on_workspace(snapshot)` and appends each snapshot to an in-memory list. It also exposes `publish_one()`, which emits one `echo.ping` event when called. Integration tests use Echo to confirm that the workspace broadcasts and that [modules](./README.md) register correctly. Echo has no dedicated OpenSpec change; the [cognitive cycle](../08-cognitive-cycle/README.md) and bus test suites reference it implicitly.

## Inputs and outputs

| Source | Handler | Result |
|---|---|---|
| `workspace.broadcast` | `on_workspace(snapshot)` | Appends the snapshot to `self.snapshots` |

| Stream | Event | When emitted |
|---|---|---|
| `echo.out` | `echo.ping` | Only when `publish_one()` is called |

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `[modules].echo` | `false` | Off by default in shipped `config/kaine.toml` |

`EchoModule` also accepts an optional `message_label` constructor argument. The default is `"echo"`, and it sets the `label` field in `echo.ping` payloads.

## Files

| File | Role |
|---|---|
| `kaine/modules/echo.py` | The `EchoModule` class |

## Safety gate

`tests/test_setup_wizard.py` and `tests/test_ignition_study_overlay.py` assert that their effective configurations keep `[modules].echo = false`. A CI failure here means a production-facing configuration or study overlay has accidentally enabled test infrastructure.
