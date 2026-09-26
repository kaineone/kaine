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
| Nous | `nous.engine_wrapper` | A policy proposal beside KAINE's own active-inference engine, which keeps its beliefs and expected free energy (see "Nous: the tissue as a policy proposer") |

Several partial conversions are planned; their designs are
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
  Cloud account or a CL1 device. The plugin supports a CL1 device only through a
  welfare gate (see "Running on a CL1") and does not support Cortical Cloud yet (see
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

## Nous: the tissue as a policy proposer

Nous is off the substrate unless you set `nous = "cl1"`. When it is on, KAINE
builds its usual active-inference engine and the plugin wraps it. Each step runs
the silicon engine first, then stimulates one group of electrodes per action,
harder for actions with lower expected free energy, and reads the tissue's
proposed action from whichever group fires most in the window that answers its
stimulation. When no group fires, or the top groups tie, the proposal is the
silicon engine's choice and the answer counts as a disagreement. Once the
substrate follows KAINE's cycle, that answer arrives one Nous step later, so it is
scored against the silicon choice it was stimulated with, not the current one.
The last two electrodes of the territory carry feedback in the manner of Cortical
Labs' DishBrain experiment: a fixed pulse after a proposal that agreed with the
silicon engine, and a random amplitude after one that did not.

```toml
[plugins.cl1.backends]
nous = "cl1"

[plugins.cl1.substrate.territories]
nous = 10        # two electrodes per action plus two feedback electrodes

[plugins.cl1.nous]
mode = "shadow"  # or "drive"
```

The territory needs two electrodes for each of Nous' actions plus the two
feedback electrodes, so 10 for the default four actions; a smaller one fails the
boot with a message naming the plugin.

- **`shadow`** (the default) changes nothing about what Nous does. The tissue's
  proposal is computed and the agreement rate with the silicon engine is logged
  every 100 proposals.
- **`drive`** makes Nous act on the tissue's proposal. Beliefs and expected free
  energy still come from the silicon engine. Every boot in drive mode logs a
  warning.

A step whose silicon inference timed out or failed is passed through untouched,
with no stimulation. On the simulator this proves the wiring only: the reference
culture responds to stimulation but does not learn, so its proposals follow the
encoded preference and nothing more. On a CL1, the feedback pattern is
stimulation like any other and belongs in your welfare review.

## What it does not do yet

- **Cortical Cloud.** Cortical Cloud deploys your code to run on the CL1 itself,
  typically as a Jupyter notebook. Cortical Labs publishes no API for a program
  running elsewhere, such as KAINE on your machine, to drive a remote CL1, so
  there is nothing yet for the plugin to connect to or authenticate against.
  `target = "cloud"` is refused with that explanation. When a supported path
  exists, credentials will be kept out of the KAINE configuration file and out of
  logs.

## Timing: one substrate window per cycle tick

KAINE calls the plugin once per processing tick (10 Hz by default). Each call
closes one substrate window, one processing period long, however many converted
modules and oscillators share the substrate. A background thread runs the
substrate, so the cognitive cycle never waits for it:

- **Accelerated simulator** (`accelerated_time = true`): the thread runs one
  window per tick.
- **Real time** (`accelerated_time = false`, the simulator's real-time mode, and
  the mode real tissue would need): the thread runs the substrate loop
  continuously and each tick marks a window boundary.

A module's step queues its stimulation for the next window and reads its
territory's latest completed window, so the response to a stimulus arrives one
tick later (about 100 ms). If two steps of the same module queue stimulation
before a window starts, the later one wins. Outside KAINE, or before the first
tick, each step runs its own window instead, one at a time (Nous steps from a
worker thread, the other modules from the event loop).

## Running on a CL1

Real CL1 hardware is not available to this project, so this path has been
exercised only against a fake device in the tests. It exists so that anyone with
a CL1 can try KAINE's forward models on a living culture without rebuilding the
plumbing.

**Where it runs.** The plugin drives the device through Cortical Labs' own SDK,
in the same process. KAINE and the plugin therefore run on the machine that has
the device SDK installed; with the simulator SDK the plugin refuses the hardware
target.

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

**What the gate checks.** The plugin refuses the hardware target, listing every
unmet condition, unless the acknowledgement matches exactly, the ethics
reference is filled in, accelerated time is off and no simulated data source is
set. Opening the session also refuses if the SDK reports the simulator. Every
boot with a hardware target logs a warning that a living culture is in the loop,
naming the ethics reference.

**What it does while running.** On hardware the substrate follows KAINE's cycle
from the moment it opens: stimulation is delivered only on cycle ticks, never on
a module's own step. So a frozen cycle, including a welfare freeze, delivers no
stimulation, and stimulation queued before a freeze is discarded rather than
delivered when the cycle resumes. Stimulation stays inside the SDK's current and
charge ceilings and inside each module's own electrodes, and a lagging substrate
or a crashed substrate loop is logged.

**What remains yours.** The plugin records your acknowledgement and reference; it
cannot verify them. Institutional approval, the culture's care, and
characterising every stimulation pattern in the simulator before it reaches
tissue are the operator's responsibility, as
[`plugins/kaine-cl1/docs/biological-welfare.md`](../plugins/kaine-cl1/docs/biological-welfare.md)
sets out.

## Testing

The plugin's tests live in `plugins/kaine-cl1/tests` and are not collected by
KAINE's own test run. With the plugin and `cl-sdk` installed:

```bash
cd plugins/kaine-cl1
pytest
```

Some tests boot stock KAINE through its plugin loader. Two also need torch (to
compare against the silicon models) and the Nous boot tests need KAINE's
`reasoning` extra (pymdp); those skip where their dependency is absent.
