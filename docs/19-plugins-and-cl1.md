# Plugins and CL1

This page explains how KAINE loads external plugins that swap model objects inside core modules, and how the optional CL1 substrate plugin runs some of those models on Cortical Labs' neuron culture or its simulator. Read it if you want to install, configure, write, or reason about a KAINE plugin.

## How plugins work

A KAINE plugin is an external Python package that replaces one of the model objects inside a core module while leaving the module's bus subscriptions, event shapes, and lifecycle wiring unchanged. The loader is in `kaine/plugins.py`; there is no `kaine/plugins/` package. Plugins are discovered through the `kaine.plugins` importlib metadata entry-point group, but they are loaded only when the operator explicitly names them in the run configuration.

## Enabling a plugin

The `[plugins]` section controls which installed plugins may run:

```toml
[plugins]
enabled = ["my_plugin"]

[plugins.my_plugin]
learning_rate = 0.01
```

A name in `enabled` is the plugin's entry-point name (`my_plugin` in the package layout below), not its distribution name. Only the plugin's own `[plugins.<name>]` table is passed to the plugin. An installed plugin that is not listed in `enabled` is never imported, so installing a package by itself does not change a boot.

## The plugin interface

The entry point resolves to a zero-argument callable that returns an object implementing this protocol:

```python
from typing import Any, Protocol

class KainePlugin(Protocol):
    def seams(self, config: dict) -> frozenset[str]: ...
    def injections(self, module: str, config: dict) -> dict[str, Any]: ...
    def make_oscillator(
        self, module: str, config: dict, defaults: dict
    ) -> Any | None: ...
```

`seams` declares the dotted seams the plugin will fill. `injections` returns constructor objects for a module's declared seams. `make_oscillator` is optional and supplies a replacement oscillator for modules whose `oscillator.<module>` seam was declared.

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
| `chronos.network` | The default [Chronos](09-modules/chronos.md) CfC network | An object with a `units` attribute (hidden width) and a `tick(feature_vec)` method that returns a hidden-state vector. Chronos sizes its forward-prediction head from `units`. |
| `soma.forward_model` | The default [Soma](09-modules/soma.md) forward model | `step(...)`, `prediction_error_to_salience(...)`, a `suspended` property, `adaptation_steps`, `state_dict()`, `load_state_dict(...)`. |
| `nous.engine` | The active-inference engine KAINE builds from `[nous].backend` (`"pymdp"` or `"numpy"`) in [Nous](09-modules/nous.md) | An object satisfying `kaine.modules.nous.engine.ActiveInferenceEngine` (Nous calls `step(...)` and reads `actions`). The `[nous]` complexity envelope is still validated. |
| `nous.engine_wrapper` | The built engine, indirectly: a wrapper around the active-inference engine KAINE built from `[nous].backend` | A callable `wrap(engine)` that receives the engine KAINE built and returns an `ActiveInferenceEngine`. Use it to add to the default engine without seeing its settings. The wrapper must forward every attribute it does not override to the inner engine: Nous probes optional methods with `getattr` (for example `seed_posterior` after a revive) and goes without them when they are missing. Nous calls `engine.step` via `asyncio.to_thread`, so a wrapper that touches shared state must serialise it. Cannot be combined with `nous.engine`. |
| `audition.acoustic_encoder` | The default [Audition](09-modules/audition.md) acoustic encoder | An object satisfying the `AcousticEncoder` protocol: `embedding_dim` (int), `model_id` (str), and `embed(audio_bytes, sample_rate)` returning a list of floats. Requires `general_audition = true` and `[audition].acoustic_encoder` to be unset or `"spectral"`. |
| `oscillator.<module>` | The default module oscillator | An oscillator object accepted by the module's `attach_oscillator` method. |

## When boot fails

If a plugin named in `enabled` is missing, exported by more than one installed distribution, fails to import, raises during `seams` or `injections`, declares an unknown seam, conflicts with another plugin over a seam, or returns an injection it did not declare, boot raises `PluginError` and stops. There is no silent fallback to the default model.

## Restart behavior

Spot restarts a failing module in one of two ways:

- **In place** (the default for Chronos and Soma): the same module object is shut down and re-initialized, so it keeps the injected object it was built with. The plugin is not asked again.
- **Rebuilt** (used by modules that hold external resources, such as Nous): the module is constructed afresh through the same path as at boot, so the plugin's `injections` is called again for that module and must return a working, fresh object.

Oscillators are never re-created by a restart: a rebuilt module receives the oscillator its predecessor held (the same object, phase history intact), and every other module keeps its own. A plugin's `make_oscillator` is therefore called once per declared `oscillator.<module>` seam, at boot.

A plugin must accept repeated requests for the same module, and an injected object must tolerate being shut down and re-initialized in place.

## Oscillator seams

An `oscillator.<module>` seam replaces the default oscillator; it never enables the oscillator layer. If `[oscillator].enabled` is `false`, KAINE rejects any plugin that declares an `oscillator.*` seam at load time. When the layer is enabled, plugin oscillators are attached before the snnTorch check, so a plugin oscillator does not require snnTorch to be installed.

## Disabled modules

A plugin may declare a seam for a module that `[modules]` does not enable. The seam is accepted and recorded in the run manifest, but it is not filled because the module is not constructed.

## Observing the cycle

A plugin whose models depend on an external clock (for example a substrate that advances in windows) can follow the cognitive cycle by implementing an optional method:

```python
class MyPlugin:
    def on_cycle_tick(self, tick):
        ...
```

KAINE calls it once per cycle tick, after the tick's `cycle.tick` event is published, with a copy of that event's payload: `tick_index`, `wall_duration_ms`, `target_duration_ms`, `slip_ms`, `is_experiential`, `error`, `processing_rate_hz`, `experiential_rate_hz` (effective for that tick), `access_drive`, and `time_scale`. Ticks that do not run, such as while the entity is frozen, do not call it.

The hook is observation only. Changing the mapping it receives changes nothing in the cycle or the published event, and its return value is ignored.

It runs inside the tick on the cycle's event loop, so it must return quickly and hand any heavy work to a thread or task of its own. KAINE times every call and logs a WARNING naming the plugin, on the first slow call and every 100th after it, when a call takes longer than 10% of the tick's target period (10 ms at the default 10 Hz). An exception from the hook is logged with the same cadence and naming and never stops the cycle. When no loaded plugin implements the hook, the cycle makes no call at all, so deterministic runs are unchanged.

## State snapshots

Soma serializes its forward model through `state_dict()` and restores it with `load_state_dict(...)`, so an injected forward model must implement both. If restoring fails, Soma logs a warning and continues with the un-restored model, so a plugin model should restore what it can or keep a working state when it receives a snapshot taken with a different model.

A plugin model with a `reservoir_seed` attribute is a special case. If the snapshot carries `reservoir_seed`, Soma replaces the injected model with a fresh `SubstrateForwardModel` seeded from the snapshot instead of calling `load_state_dict(...)`. In that case, Chronos calls `load_state(...)` on the injected network and saves `reservoir_seed` when the network exposes one; otherwise Chronos serializes only its prediction head, so an injected network's state is normally the plugin's to keep.

## Run manifest records

Boot logs one WARNING line for each filled seam. The run manifest records, for each enabled plugin, its name, the distribution name and version from package metadata, its declared seams, and `observes_cycle` (whether it implements `on_cycle_tick`).

## Plugins in ablation runs

The workspace-mediation ablation runner constructs Chronos and Soma directly and does not load plugins.

## The CL1 substrate plugin

KAINE can run the forward models of some of its modules on Cortical Labs' CL1, a system that grows cortical neurons on a 64-electrode array and lets software stimulate them and record their spikes in a closed loop. The plugin lives in `plugins/kaine-cl1/`. It is optional, it is not installed with KAINE, and it does nothing unless the operator installs it and names it in the configuration.

### What the CL1 plugin replaces

The plugin keeps a module's identity, bus subscriptions and published events exactly as they are, and replaces only the object that realizes its forward model. Some partial conversion designs are in `plugins/kaine-cl1/openspec/`.

| Module | Seam | What runs on the substrate |
|---|---|---|
| [Chronos](09-modules/chronos.md) | `chronos.network` | The recurrent network whose hidden state feeds Chronos' prediction head. |
| [Soma](09-modules/soma.md) | `soma.forward_model` | The reservoir under Soma's interoceptive forward model; a small silicon readout still predicts the next metrics vector, so the prediction error keeps its usual units. |
| Any oscillated module | `oscillator.<module>` | The oscillatory-binding oscillator: each time the module publishes, its own small territory is stimulated in proportion to the event's salience, and the binding phase is read from that territory's firing. |
| [Nous](09-modules/nous.md) | `nous.engine_wrapper` | A policy proposal beside KAINE's own active-inference engine, which keeps its beliefs and expected free energy. |

### Requirements

The plugin needs **Cortical Labs' `cl-sdk`**, which KAINE does not ship and does not install:

```bash
pip install cl-sdk
```

Before you do, note three things:

- **License.** `cl-sdk` is licensed CC BY-NC 4.0, for non-commercial use only. That license is Cortical Labs', not KAINE's, and it applies to your use of their package.
- **The simulator does not learn.** The simulator in `cl-sdk` is what the plugin runs on. Cortical Labs describes its data as non-learning control data that does not respond to stimulation and must not be relied upon for experiments.
- **Real neurons are a paid service.** Running on living cultures needs a Cortical Cloud account or a CL1 device. The plugin supports a CL1 device only through a welfare gate (see [Running on a CL1](#running-on-a-cl1)) and does not support Cortical Cloud yet.

If the plugin is enabled and `cl-sdk` is not installed, KAINE refuses to boot and prints these same points.

The plugin and `cl-sdk` both need Python 3.12 or later, so a KAINE install on Python 3.11 cannot use it.

### Installation and enabling

From the repository root, in the same Python environment as KAINE:

```bash
pip install ./plugins/kaine-cl1
pip install cl-sdk
```

The setup wizard (`python -m kaine.setup`) offers this as an optional step, off by default, but skips it when you choose a defaults run: answering yes records the configuration below for whichever of Chronos and Soma you enabled and prints the two install commands; it never runs them. To configure it by hand instead, add to your KAINE configuration:

```toml
[plugins]
enabled = ["cl1"]

[plugins.cl1.substrate]
target = "simulator"
accelerated_time = true
data_source = "reference_culture"

[plugins.cl1.backends]
chronos = "cl1"
soma = "cl1"

[plugins.cl1.substrate.territories]
chronos = 12
soma = 12
```

To source the oscillatory-binding phase of some modules from the substrate as well, list them; each gets its own territory, and KAINE's `[oscillator].enabled` must be true:

```toml
[oscillator]
enabled = true

[plugins.cl1.oscillators]
modules = ["chronos", "soma"]
channels_per_module = 4
```

All territories together must fit in the 63 usable channels (64 electrodes, with channel 0 reserved); the plugin refuses to load otherwise. Each publish of an oscillated module costs one substrate tick.

With `cl1` absent from `[plugins].enabled`, KAINE runs exactly as it does without the plugin. With `cl1` enabled, the plugin still validates and needs `cl-sdk` installed, and `[plugins.cl1.oscillators].modules` must also be empty, before the run is equivalent to silicon-only; otherwise boot fails or the substrate is used. If you want no substrate effect, leave `cl1` out of `enabled`. The full set of keys is in `plugins/kaine-cl1/config/kaine_cl1.example.toml`.

### Simulator data sources

Because the `cl-sdk` simulator's own data ignores stimulation, the plugin makes the data source an explicit choice with `data_source`:

| Value | What the substrate produces |
|---|---|
| `reference_culture` (default) | The plugin's own synthetic culture model: a seeded Poisson baseline plus evoked spikes that grow with stimulation strength. It exists so the converted modules can be exercised end to end, and it is a model, not biology. |
| `sdk` | `cl-sdk`'s own synthetic data, which does not respond to stimulation. Useful as a baseline control. |
| `replay` | A recording, given by `replay_path`. |

Every boot with a converted module logs a warning that the substrate is simulated and names the data source, and the run manifest records which seams the plugin filled. A simulated run is never evidence about living neurons.

### Nous on the substrate

Nous is off the substrate unless you set `nous = "cl1"`. When it is on, KAINE builds its usual active-inference engine and the plugin wraps it. Each step runs the silicon engine first, then stimulates one group of electrodes per action, harder for actions with lower expected free energy, and reads the tissue's proposed action from whichever group fires most in the window that answers its stimulation. When no group fires, or the top groups tie, the proposal is the silicon engine's choice and the answer counts as a disagreement. Once the substrate follows KAINE's cycle, that answer arrives one Nous step later, so it is scored against the silicon choice it was stimulated with, not the current one. The last two electrodes of the territory carry feedback in the manner of Cortical Labs' DishBrain experiment: a fixed pulse after a proposal that agreed with the silicon engine, and a random amplitude after one that did not.

```toml
[plugins.cl1.backends]
nous = "cl1"

[plugins.cl1.substrate.territories]
nous = 10        # two electrodes per action plus two feedback electrodes

[plugins.cl1.nous]
mode = "shadow"  # or "drive"
```

The territory needs two electrodes for each of Nous' actions plus the two feedback electrodes, so 10 for the default four actions; a smaller one fails the boot with a message naming the plugin.

- **`shadow`** (the default) changes nothing about what Nous does. The tissue's proposal is computed and the agreement rate with the silicon engine is logged every 100 proposals.
- **`drive`** makes Nous act on the tissue's proposal. Beliefs and expected free energy still come from the silicon engine. Every boot in drive mode logs a warning.

A step whose silicon inference timed out or failed is passed through untouched, with no stimulation. On the simulator this proves the wiring only: the reference culture responds to stimulation but does not learn, so its proposals follow the encoded preference and nothing more. On a CL1, the feedback pattern is stimulation like any other and belongs in your welfare review.

### What the CL1 plugin does not do yet

Cortical Cloud deploys your code to run on the CL1 itself, typically as a Jupyter notebook. Cortical Labs publishes no API for a program running elsewhere, such as KAINE on your machine, to drive a remote CL1, so there is nothing yet for the plugin to connect to or authenticate against. `target = "cloud"` is refused with that explanation. When a supported path exists, credentials will be kept out of the KAINE configuration file and out of logs.

### Timing

KAINE calls the plugin once per processing tick. Each call closes one substrate window, one processing period long, however many converted modules and oscillators share the substrate. A background thread runs the substrate, so the cognitive cycle never waits for it:

- **Accelerated simulator** (`accelerated_time = true`): the thread runs one window per tick.
- **Real time** (`accelerated_time = false`, the simulator's real-time mode, and the mode real tissue would need): the thread runs the substrate loop continuously and each tick marks a window boundary.

A module's step queues its stimulation for the next window and reads its territory's latest completed window, so the response to a stimulus arrives one tick later. If two steps of the same module queue stimulation before a window starts, the later one wins. An oscillator records the window that answers its own stimulation, which is the response to its module's previous publish, so a module that publishes less often than the cycle ticks still records its own response rather than background firing. Outside KAINE, or before the first tick, each step runs its own window instead, one at a time (Nous steps from a worker thread, the other modules from the event loop). If such a window is still running at the first tick, the switch to one window per tick finishes in the background, so the cycle never waits for it.

### Running on a CL1

Real CL1 hardware is not available to this project, so this path has been tested only against a fake device in the tests. It exists so that anyone with a CL1 can try KAINE's forward models on a living culture without rebuilding the plumbing.

**Where it runs.** The plugin drives the device through Cortical Labs' own SDK, in the same process. KAINE and the plugin therefore run on the machine that has the device SDK installed; with the simulator SDK the plugin refuses the hardware target.

**Configuration.** Set the target and answer the welfare gate:

```toml
[plugins.cl1.substrate]
target = "hardware"
accelerated_time = false        # accelerated time is simulator-only
# no data_source on hardware: the culture is the data

[plugins.cl1.hardware]
welfare_acknowledgement = "I have read plugins/kaine-cl1/docs/biological-welfare.md and hold institutional approval for work with this culture"
ethics_reference = "your approval or protocol reference"
```

**What the gate checks.** The plugin refuses the hardware target, listing every unmet condition, unless the acknowledgement matches exactly, the ethics reference is filled in, accelerated time is off and no simulated data source is set. Opening the session also refuses if the SDK reports the simulator. Every boot with a hardware target logs a warning that a living culture is in the loop, naming the ethics reference.

**What it does while running.** On hardware the substrate follows KAINE's cycle from the moment it opens: stimulation is delivered only on cycle ticks, never on a module's own step. So a frozen cycle, including a welfare freeze, delivers no stimulation, and stimulation queued before a freeze is discarded rather than delivered when the cycle resumes. Stimulation stays inside the SDK's current and charge ceilings and inside each module's own electrodes, and a lagging substrate or a crashed substrate loop is logged.

**What remains yours.** The plugin records your acknowledgement and reference; it cannot verify them. Institutional approval, the culture's care, and characterising every stimulation pattern in the simulator before it reaches tissue are the operator's responsibility, as `plugins/kaine-cl1/docs/biological-welfare.md` sets out.

### Testing the CL1 plugin

The plugin's tests live in `plugins/kaine-cl1/tests` and are not collected by KAINE's own test run. With the plugin and `cl-sdk` installed:

```bash
cd plugins/kaine-cl1
pytest
```

Some tests boot stock KAINE through its plugin loader. Two also need torch (to compare against the silicon models) and the Nous boot tests need KAINE's `reasoning` extra (`pymdp`); those skip where their dependency is absent.
