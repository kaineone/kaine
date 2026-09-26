# KAINE module plugins

A KAINE plugin is an out-of-tree Python package that substitutes one of the
model objects inside a core module while leaving the module's bus
subscriptions, event shapes, and lifecycle wiring unchanged. Plugins are
discovered through the `kaine.plugins` importlib metadata entry-point group,
but they are loaded only when the operator explicitly names them in the
run configuration.

## Enabling plugins

The `[plugins]` section controls which installed plugins may run:

```toml
[plugins]
enabled = ["my_plugin"]

[plugins.my_plugin]
learning_rate = 0.01
```

A name in `enabled` is the plugin's entry-point name (`my_plugin` in the
package layout below), not its distribution name. Only the plugin's own
`[plugins.<name>]` table is passed to the plugin. An
installed plugin that is not listed in `enabled` is never imported, so
installing a package by itself does not change a boot.

## Plugin interface

The entry point resolves to a zero-argument callable that returns an object
implementing this protocol:

```python
from typing import Any, Protocol


class KainePlugin(Protocol):
    def seams(self, config: dict) -> frozenset[str]:
        ...

    def injections(self, module: str, config: dict) -> dict[str, Any]:
        ...

    def make_oscillator(
        self, module: str, config: dict, defaults: dict
    ) -> Any | None:
        ...
```

`seams` declares the dotted seams the plugin will fill. `injections` returns
constructor objects for a module's declared seams. `make_oscillator` is
optional and supplies a replacement oscillator for modules whose
`oscillator.<module>` seam was declared.

Minimal package layout:

```toml
[project]
name = "my-research-package"
version = "1.0.0"

[project.entry-points."kaine.plugins"]
my_plugin = "my_package.kaine_plugin:make_plugin"
```

```python
# my_package/kaine_plugin.py


class MyNetwork:
    units = 16

    def tick(self, feature_vec):
        ...


class MyPlugin:
    def seams(self, config):
        return frozenset({"chronos.network"})

    def injections(self, module, config):
        if module == "chronos":
            return {"network": MyNetwork()}
        return {}


def make_plugin():
    return MyPlugin()
```

## Seams

| Seam | Replaces | Interface expected by the module |
|---|---|---|
| `chronos.network` | The default CfC network | An object with a `units` attribute (hidden width) and a `tick(feature_vec)` method that returns a hidden-state vector. Chronos sizes its forward-prediction head from `units`. |
| `soma.forward_model` | The default forward model | `step(...)`, `prediction_error_to_salience(...)`, a `suspended` property, `adaptation_steps`, `state_dict()`, `load_state_dict(...)`. |
| `nous.engine` | The default `PymdpEngine` | An object satisfying `kaine.modules.nous.engine.ActiveInferenceEngine` (Nous calls `step(...)` and reads `actions`). The `[nous]` complexity envelope is still validated. |
| `nous.engine_wrapper` | Nothing: wraps the default `PymdpEngine` | A callable `wrap(engine)` that receives the engine KAINE built from `[nous]` and returns an `ActiveInferenceEngine`. Use it to add to the default engine without seeing its settings. The wrapper must forward every attribute it does not override to the inner engine: Nous probes optional methods with `getattr` (for example `seed_posterior` after a revive) and goes without them when they are missing. Cannot be combined with `nous.engine`. |
| `oscillator.<module>` | The default module oscillator | An oscillator object accepted by the module's `attach_oscillator` method. |

## Fail-closed behavior

If a plugin named in `enabled` is missing, exported by more than one
installed distribution, fails to import, raises during `seams` or
`injections`, declares an unknown seam, conflicts with another plugin over a
seam, or returns an injection it did not declare, boot raises `PluginError`
and stops. There is no silent fallback to the default model.

## Restarts

Spot restarts a failing module in one of two ways:

- **In place** (the default, used by Chronos and Soma): the same module object
  is shut down and re-initialized, so it keeps the injected object it was built
  with. The plugin is not asked again.
- **Rebuilt** (modules that hold external resources, such as Nous): the module
  is constructed afresh through the same path as at boot, so the plugin's
  `injections` is called again for that module and must return a working, fresh
  object.

Oscillators are never re-created by a restart: a rebuilt module receives the
oscillator its predecessor held (the same object, phase history intact), and
every other module keeps its own. A plugin's `make_oscillator` is therefore
called once per declared `oscillator.<module>` seam, at boot.

A plugin must therefore accept repeated requests for the same module, and an
injected object must tolerate being shut down and re-initialized in place.

## Disabled modules

A plugin may declare a seam for a module that `[modules]` does not enable. The
seam is accepted and recorded in the run manifest, but it is not filled because
the module is not constructed.

## Oscillator seam rule

An `oscillator.<module>` seam replaces the default oscillator; it never
enables the oscillator layer. If `[oscillator].enabled` is `false`, a plugin
declaring any `oscillator.*` seam is rejected at load time. When the layer
is enabled, plugin oscillators are attached before the snnTorch check, so a
plugin oscillator does not require snnTorch to be installed.

## Recording

Boot logs one WARNING line for each filled seam. The run manifest records,
for each enabled plugin, its name, the distribution name and version from
package metadata, its declared seams, and `observes_cycle` (whether it
implements `on_cycle_tick`).

## Observing the cycle

A plugin whose models depend on an external clock (for example a substrate that
advances in windows) can follow the cognitive cycle by implementing an optional
method:

```python
class MyPlugin:
    def on_cycle_tick(self, tick):
        ...
```

KAINE calls it once per cycle tick, after the tick's `cycle.tick` event is
published, with a copy of that event's payload: `tick_index`,
`wall_duration_ms`, `target_duration_ms`, `slip_ms`, `is_experiential`,
`error`, `processing_rate_hz`, `experiential_rate_hz` (effective for that tick)
and `access_drive`. Ticks that do not run, such as while the entity is frozen,
do not call it.

The hook is observation only. Changing the mapping it receives changes nothing
in the cycle or the published event, and its return value is ignored.

It runs inside the tick on the cycle's event loop, so it must return quickly and
hand any heavy work to a thread or task of its own. KAINE times every call and
logs a WARNING naming the plugin, on the first slow call and every 100th after
it, when a call takes longer than 10% of the tick's target period (10 ms at the
default 10 Hz). An exception from the hook is logged the same way and never
stops the cycle. When no loaded plugin implements the hook, the cycle makes no
call at all, so deterministic runs are unchanged.

## State snapshots

Soma serializes its forward model through `state_dict()` and restores it with
`load_state_dict(...)`, so an injected forward model must implement both. If
restoring fails, Soma logs a warning and continues with the un-restored model,
so a plugin model should restore what it can or keep a working state when it
receives a snapshot taken with a different model. Chronos does not serialize
its network (only its prediction head), so an injected network's state is the
plugin's to keep.

## Example

[`plugins/kaine-cl1`](../plugins/kaine-cl1/) is an optional substrate plugin in
this repository that fills `chronos.network` and `soma.forward_model`. See
[cl1.md](cl1.md).

## Non-goal

The workspace-mediation ablation runner constructs Chronos and Soma directly
and does not load plugins.
