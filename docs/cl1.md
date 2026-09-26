# The CL1 substrate plugin

KAINE can run the forward models of some of its modules on Cortical Labs' CL1, a
system that grows cortical neurons on a 64-electrode array and lets software
stimulate them and record their spikes in a closed loop. The plugin that does
this lives in [`plugins/kaine-cl1`](../plugins/kaine-cl1/). It is optional, it is
not installed with KAINE, and it does nothing unless the operator installs it and
names it in the configuration.

## Why a biological substrate

KAINE's thesis is that a mind is the competition among specialised predictive
processors, each maintaining a forward model and publishing prediction errors.
Cortical Labs describes its cultures in the same free-energy terms: a network of
neurons in a closed stimulate-and-record loop that settles toward predictable
input. The plugin keeps a module's identity, bus subscriptions and published
events exactly as they are, and replaces only the object that realises its
forward model:

| Module | Seam | What runs on the substrate |
|---|---|---|
| Chronos | `chronos.network` | The recurrent network whose hidden state feeds Chronos' prediction head |
| Soma | `soma.forward_model` | The reservoir under Soma's interoceptive forward model; a small silicon readout still predicts the next metrics vector, so the prediction error keeps its usual units |
| Any module's oscillator | `oscillator.<module>` | The oscillatory-binding oscillator: each time the module publishes, its own small territory is stimulated in proportion to the event's salience, and the binding phase is read from that territory's firing, exactly as the silicon oscillator reads its simulated population |

Nous and several partial conversions are planned; their designs are
in [`plugins/kaine-cl1/openspec/`](../plugins/kaine-cl1/openspec/).

## What it needs

The plugin needs **Cortical Labs' `cl-sdk`**, which KAINE does not ship and does
not install. Install it yourself:

```bash
pip install cl-sdk
```

Before you do, note three things about it:

- **License.** `cl-sdk` is licensed CC BY-NC 4.0, for non-commercial use only.
  That license is Cortical Labs', not KAINE's, and it applies to your use of their
  package.
- **The simulator does not learn.** The simulator in `cl-sdk` is what the plugin
  runs on today. Cortical Labs describes its data as non-learning control data that
  does not respond to stimulation and must not be relied upon for experiments.
- **Real neurons are a paid service.** Running on living cultures needs a Cortical
  Cloud account or a CL1 device. The plugin does not support either yet (see
  below).

If the plugin is enabled and `cl-sdk` is not installed, KAINE refuses to boot and
prints these same points.

The plugin and `cl-sdk` both need Python 3.12 or later, so a KAINE install on
Python 3.11 cannot use it.

## Installing and enabling

From the repository root, in the same Python environment as KAINE:

```bash
pip install ./plugins/kaine-cl1
pip install cl-sdk
```

The setup wizard (`python -m kaine.setup`) offers this as an optional step,
off by default: answering yes records the configuration below for whichever of
Chronos and Soma you enabled and prints the two install commands; it never runs
them. To configure it by hand instead, add to your KAINE configuration:

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

To source the oscillatory-binding phase of some modules from the substrate as
well, list them; each gets its own territory, and KAINE's `[oscillator].enabled`
must be true (KAINE refuses oscillator seams otherwise):

```toml
[oscillator]
enabled = true

[plugins.cl1.oscillators]
modules = ["chronos", "soma"]
channels_per_module = 4
```

All territories together must fit in the 63 usable channels (64 electrodes, with
channel 0 reserved); the plugin refuses to load otherwise. Each publish of an
oscillated module costs one substrate tick.

With `cl1` absent from `[plugins].enabled`, or every module set to `"silicon"`,
KAINE runs exactly as it does without the plugin. The full set of keys is in
[`plugins/kaine-cl1/config/kaine_cl1.example.toml`](../plugins/kaine-cl1/config/kaine_cl1.example.toml).

## Simulator data sources

Because the `cl-sdk` simulator's own data ignores stimulation, the plugin makes
the data source an explicit choice with `data_source`:

| Value | What the substrate produces |
|---|---|
| `reference_culture` (default) | The plugin's own synthetic culture model: a seeded Poisson baseline plus evoked spikes that grow with stimulation strength. It exists so the converted modules can be exercised end to end, and it is a model, not biology. |
| `sdk` | `cl-sdk`'s own synthetic data, which does not respond to stimulation. Useful as a baseline control. |
| `replay` | A recording, given by `replay_path`. |

Every boot with a converted module logs a warning that the substrate is
simulated and names the data source, and the run manifest records which seams
the plugin filled. A simulated run is never evidence about living neurons.

## What it does not do yet

- **Cortical Cloud.** Cortical Cloud deploys your code to run on the CL1 itself,
  typically as a Jupyter notebook. Cortical Labs publishes no API for a program
  running elsewhere, such as KAINE on your machine, to drive a remote CL1, so
  there is nothing yet for the plugin to connect to or authenticate against.
  `target = "cloud"` is refused with that explanation. When a supported path
  exists, credentials will be kept out of the KAINE configuration file and out of
  logs.
- **Hardware.** `target = "hardware"` is refused. Running on living tissue is a
  deliberate step with its own welfare review, described in
  [`plugins/kaine-cl1/docs/biological-welfare.md`](../plugins/kaine-cl1/docs/biological-welfare.md).
- **Real time.** A substrate tick currently blocks the caller for one cognitive
  tick, so the plugin requires the simulator's accelerated time. A non-blocking
  substrate is planned.

## Testing

The plugin's tests live in `plugins/kaine-cl1/tests` and are not collected by
KAINE's own test run. With the plugin and `cl-sdk` installed:

```bash
cd plugins/kaine-cl1
pytest
```

Some tests boot stock KAINE through its plugin loader, and two also need torch
(to compare against the silicon models); those skip where torch is absent.
