# CL1 / cl-sdk API notes (research)

Notes from studying the vendored simulator snapshot
(`vendor/cl-sdk/`, upstream `Cortical-Labs/cl-sdk@a9a2f9c`). These are the
primitives every conversion is built on. Authoritative source:
[docs.corticallabs.com](https://docs.corticallabs.com) and the vendored source.

## The device model

A CL1 system presents **one culture of living cortical neurons on a
64-channel multi-electrode array (MEA)**. Every channel can both **stimulate**
(inject current) and **record** (read extracellular voltage). The free `cl-sdk`
package is a faithful **simulator** of this device: `cl.is_simulator()` returns
`True`, and spikes are either replayed from a recording or generated from a
seeded Poisson process. The simulator is where we build and validate now,
since real CL1 hardware is not available to this project yet; the same API
will drive real cultures once running on real tissue becomes a deliberate,
reviewed step (see `biological-welfare.md`).

Key constants (simulator):
- **64 channels** (`ChannelSet._CHANNELS_TOTAL`).
- **Frame time 20 µs** → 50 kHz sampling (`_FRAME_TIME_US = 20`).
- Stim current limit **±3.0 µA**; pulse width a multiple of **20 µs**; per-phase
  charge ≤ **3.0 nC**. Burst frequency ≤ **200 Hz**.

## Writing: stimulation

```python
import cl
from cl import ChannelSet, StimDesign, BurstDesign

with cl.open() as neurons:
    # biphasic pulse: 160 µs @ -1.0 µA, then 160 µs @ +1.0 µA, on channels 8 & 9
    neurons.stim(ChannelSet(8, 9), StimDesign(160, -1.0, 160, 1.0))
```

- `StimDesign(dur_us, cur_uA, ...)`: mono / bi / triphasic (2, 4, or 6 args);
  consecutive phases must alternate polarity.
- `BurstDesign(count, hz)`: a train of stims (≤ 200 Hz). This is the natural
  primitive for **rate coding** a scalar into stimulation.
- `ChannelSet` supports set algebra (`| & ^ ~`), convenient for allocating and
  masking channel territories.
- `neurons.create_stim_plan()` / `StimPlan`: compose multi-channel patterns.
- `neurons.interrupt(...)`, `interrupt_then_stim(...)`, `sync(...)`: closed-loop
  control primitives.

## Reading: spikes, frames, the loop

```python
for tick in neurons.loop(ticks_per_second=100, stop_after_ticks=1000):
    for spike in tick.analysis.spikes:   # Spike: timestamp, channel, samples[75]
        ...
    for stim in tick.analysis.stims:     # Stims delivered this tick
        ...
```

- `neurons.loop(ticks_per_second=...)` is the closed-loop driver. Each
  `LoopTick` carries `.analysis` (a `DetectionResult` with `.spikes` / `.stims`)
  and `.frames`. **This is where a converted module reads the culture's response
  to its stimulation in the same tick.**
- `neurons.read(n)`: raw µV frames; `Spike.samples` is a 75-sample window
  (25 pre, 50 post) around each detected spike.
- `neurons.record(...)` / `Recording` / `DataStream`: persistence and streaming.

## The analysis suite → our decoders

`cl.analysis` ships exactly the metrics a predictive-processing decoder needs to
turn a spike response into a **prediction-error / surprise** scalar:

| Metric | Module use in KAINE terms |
|---|---|
| firing stats (rates) | population activity → scalar magnitude |
| **criticality** | order/disorder of the response → **free-energy / surprise** proxy |
| **Lempel-Ziv complexity** | response unpredictability → prediction error |
| information entropy | response uncertainty → precision weighting |
| functional connectivity | relational / associative signal (Empatheia, Mnemos-assoc) |
| bursts | discrete "event" detection (onset salience) |
| spike-triggered histogram | stimulus→response tuning (codec calibration) |
| discrete cosine transform | oscillatory/phase content (Oscillator layer) |

The criticality/LZ/entropy trio is the crux of the whole idea: KAINE weights bus
events by **precision-weighted prediction error**, and Cortical Labs' DishBrain
paradigm already frames the culture's dynamics in **free-energy** terms. The
decoder reads *how surprised the tissue was* and publishes that as the module's
salience.

## Simulator knobs we rely on (`.env`)

- `CL_SDK_ACCELERATED_TIME=1`: decouple from wall-clock for fast offline
  evaluation (incompatible with the visualisation WebSocket; hardware-invalid).
- `CL_SDK_REPLAY_PATH`: replay a recording instead of synthetic Poisson data.
- `CL_SDK_RANDOM_SEED`, `CL_SDK_SAMPLE_MEAN`, `CL_SDK_SPIKE_PERCENTILE`:
  deterministic synthetic-data controls (reproducible runs).
- Custom `SimulatorDataSource` / `LiveSimulatorDataSource`: feed our own
  stimulus-conditioned data source, and receive committed stims via
  `on_stim(stim)`. This is how a closed-loop *learning* experiment is wired in
  the sim: our data source can make the synthetic response depend on the stim
  history, approximating plasticity.

## Consequences for the architecture

1. **One array, many modules.** 64 channels is the hard ceiling. Converted
   modules must share via disjoint channel territories → the **substrate broker**
   (new component; see the foundation change).
2. **Real-time cadence.** The loop runs in real time (unless accelerated in the
   sim). KAINE cycles ~3.3 Hz; the substrate loop runs faster (~100 Hz) and the
   broker aggregates sub-ticks into one cognitive-tick observation.
3. **Lossy, low-dimensional interface.** 64 electrodes cannot carry a video
   latent or an LLM's hidden state. This is *why* only low-dimensional,
   dynamics-heavy modules convert well: it is a property of the medium, not a
   temporary limitation. See `conversion-matrix.md`.
