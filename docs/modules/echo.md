# Echo

Minimal built-in test module — records every workspace snapshot it receives and
can publish a single `echo.ping` event on demand.

## Status

Permanent test infrastructure. Ships **permanently disabled**
(`[modules].echo = false`) in the default config. Must not be enabled in
production deployments.

---

## Responsibility

`EchoModule` is a ground-truth observer for the bus + cycle + Syneidesis path.
It receives every workspace broadcast (via `on_workspace`), appends the snapshot
to an in-memory list, and exposes a `publish_one()` helper that emits
`echo.ping`. Integration tests use it to verify that the global workspace is
broadcasting and that module registration is working.

---

## Inputs

| Source | Mechanism |
|---|---|
| `workspace.broadcast` | `on_workspace(snapshot)` — appends to `self.snapshots` |

## Outputs

| Stream | Event type | Condition |
|---|---|---|
| `echo.out` | `echo.ping` | Only when `publish_one()` is called explicitly |

---

## Configuration

| Key | Default | Description |
|---|---|---|
| `[modules].echo` | `false` | **Must remain false in all committed configs** |

The module accepts an optional `message_label` constructor argument (default
`"echo"`) used as the `label` field in `echo.ping` payloads.

---

## Key files

| File | Role |
|---|---|
| `kaine/modules/echo.py` | `EchoModule` class (single file) |

---

## Safety note

The guard test verifies that `[modules].echo = false` is set in the committed
`config/kaine.toml`. A CI failure here means a production config accidentally
enables test infrastructure.

---

## Spec & related

No dedicated OpenSpec change. Referenced implicitly by the cognitive-cycle and
bus integration test suites.
