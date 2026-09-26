# cl1-substrate Specification

## Purpose
The CL1 substrate the plugin drives: one owned session, a broker that leases disjoint channel territories and runs the closed loop, codecs, one substrate window per KAINE cycle tick on a background thread, and a real-hardware target reachable only through a welfare gate, with stimulation tied to the cycle so that a frozen cycle delivers none.

## Requirements

### Requirement: One owned substrate session

The overlay SHALL open and own exactly one `cl.Neurons` connection per process
via `cl.open()`, configured from `[substrate]`. Individual module backends SHALL
NOT open their own connection. The session SHALL target the simulator unless an
explicit `[substrate].target = "hardware"` opt-in is present, so that a run
reaches a real culture only by deliberate choice, never by accident.

#### Scenario: Simulator unless hardware is explicitly chosen

- **WHEN** the overlay boots with no `[substrate].target` set
- **THEN** it opens the connection against the simulator (`cl.is_simulator()` is
  `True`) and does not touch real hardware
- **AND** no module backend has opened its own `cl` connection

#### Scenario: Hardware requires a deliberate opt-in

- **WHEN** `[substrate].target = "hardware"` is set
- **THEN** the session may proceed against a real culture (subject to the
  biological-welfare review step)

#### Scenario: Deterministic simulator runs

- **WHEN** two runs use the same seed, replay path, and configuration
- **THEN** the spike stream delivered to modules is identical across the two runs

### Requirement: Disjoint channel territories

The broker SHALL lease each converted module a disjoint block of the 64
electrodes, fixed for the run and recorded in the run manifest. The sum of all
leased channels SHALL NOT exceed 64; an allocation that would exceed it SHALL
fail at boot, not at runtime.

#### Scenario: Isolation between modules

- **WHEN** two modules are leased disjoint territories
- **THEN** neither module observes stim delivered to, or spikes recorded on, the
  other's channels

#### Scenario: The 64-electrode ceiling is enforced

- **WHEN** module allocations sum to more than 64 channels
- **THEN** boot fails with an oversubscription error before any loop starts

### Requirement: A single shared closed loop

The broker SHALL run exactly one `neurons.loop(...)`. Each tick it SHALL deliver
every module's queued stimulation, read the resulting spikes, and return to each
module only the detection result on that module's territory.

#### Scenario: Fan-in and fan-out in one loop

- **WHEN** multiple modules queue stim in the same tick
- **THEN** all are delivered within that single loop tick
- **AND** each module receives back only its own territory's spikes and stims

### Requirement: Substrate cadence nests inside the cognitive cycle

The substrate `ticks_per_second` SHALL be an integer multiple of KAINE's
cognitive-cycle rate. The broker SHALL aggregate the substrate sub-ticks within
one cognitive tick into a single per-territory observation, and SHALL NOT block
the cognitive cycle's per-tick budget.

#### Scenario: Non-blocking cadence

- **WHEN** the substrate loop runs at 100 Hz and the cognitive cycle at ~3.3 Hz
- **THEN** each cognitive tick receives one aggregated observation per territory
- **AND** the cognitive tick budget is not exceeded waiting on the loop

### Requirement: Deterministic, safe, reversible codecs

Encoders SHALL clamp and validate every produced stimulation to the SDK limits
(±3 µA current, ≤3 nC per phase, ≤200 Hz burst, 20 µs duration granularity) at
construction, so an out-of-range input can never yield an invalid or unsafe
`StimDesign`. Decoders SHALL be pure functions of `(spikes, territory)`. A
surprise decoder SHALL return a value in [0, 1] that increases with response
disorder (criticality / Lempel-Ziv complexity) relative to a rolling baseline.

#### Scenario: Encoding stays within safety limits

- **WHEN** a module encodes any in-domain input value
- **THEN** the resulting stimulation satisfies all SDK current, charge,
  frequency, and duration limits

#### Scenario: Surprise tracks response disorder

- **WHEN** the culture's response to a stimulus is more disordered than the
  territory's recent baseline
- **THEN** the surprise decoder returns a higher value than for an ordered,
  predictable response

### Requirement: Conversions never modify pure KAINE

A module conversion SHALL be realised by injecting a CL1-backed forward model
through KAINE's existing client seam, leaving the module's `name`, bus
subscriptions, and published `<name>.out` event shapes unchanged. Where a module
lacks a suitable seam, the overlay SHALL contribute a vendor-neutral seam upstream
(silicon default unchanged) or subclass within this repo; never edit the pinned
KAINE dependency or the vendored simulator.

#### Scenario: Event shapes are preserved

- **WHEN** a module runs with its `cl1` backend selected
- **THEN** its published `<name>.out` events have the same schema as under the
  silicon backend

#### Scenario: The overlay is inert when unused

- **WHEN** no module selects the `cl1` backend
- **THEN** the system behaves identically to pure KAINE

### Requirement: The substrate advances once per cycle tick
When KAINE calls the plugin's `on_cycle_tick`, the broker SHALL close exactly one substrate window per call, whatever the number of consumers, and each territory's spikes in that window SHALL become its latest observation.

#### Scenario: Several consumers in one cycle
- **WHEN** three consumers each step once between two `on_cycle_tick` calls
- **THEN** exactly one window was run for that cycle and each consumer read its own territory's latest completed window

### Requirement: Stimulation lands in the next window
In beat mode a consumer's step SHALL queue its stimulation for the next window and SHALL NOT run a window itself; the stimulation SHALL be delivered at the start of the window that begins after the next `on_cycle_tick`.

#### Scenario: One-cycle response latency
- **WHEN** a consumer queues strong stimulation, `on_cycle_tick` runs, and the consumer reads its latest observation after the following `on_cycle_tick`
- **THEN** that observation contains the evoked response

### Requirement: Real time never blocks the cycle
On a real-time substrate, `on_cycle_tick` SHALL only mark the window boundary and swap observations; the substrate loop SHALL run on a background thread, and consumers SHALL never wait for a window.

#### Scenario: Slow substrate
- **WHEN** the background loop is running in real time
- **THEN** `on_cycle_tick` and every consumer step return without waiting for a substrate window to complete

### Requirement: Standalone use keeps per-step windows
Until the first `on_cycle_tick`, consumers SHALL run their own windows as before; the first beat SHALL switch the broker to beat mode for the rest of the process and SHALL log that switch.

#### Scenario: Used outside KAINE
- **WHEN** consumers step and `on_cycle_tick` is never called
- **THEN** each step runs its own window and reads its own stimulus response

### Requirement: Hardware is reachable only through an explicit welfare gate
The plugin SHALL accept `target = "hardware"` only when `[plugins.cl1.hardware].welfare_acknowledgement` equals the required statement exactly, `ethics_reference` is a non-empty string, `accelerated_time` is false and no `data_source` is set. Otherwise it SHALL refuse to load with a message naming each unmet condition.

#### Scenario: Missing acknowledgement
- **WHEN** `target = "hardware"` and the `hardware` table is absent
- **THEN** the plugin refuses to load and the message names `welfare_acknowledgement` and `ethics_reference`

#### Scenario: Accelerated time on hardware
- **WHEN** the gate's statements are present but `accelerated_time = true`
- **THEN** the plugin refuses to load and the message names `accelerated_time`

#### Scenario: Complete gate
- **WHEN** the statement matches, `ethics_reference` is set, `accelerated_time = false` and no `data_source` is set
- **THEN** the plugin declares its seams and logs at WARNING that a living culture is in the loop, naming the ethics reference

### Requirement: The session confirms a real device
With `target = "hardware"`, opening the substrate session SHALL refuse when `cl.is_simulator()` is true.

#### Scenario: Hardware target on the simulator
- **WHEN** `target = "hardware"` and the installed SDK is the simulator
- **THEN** opening the session raises an error saying no real device is present

### Requirement: Stimulation does not outlive a freeze
When a beat arrives more than two processing periods after the previous beat, the broker SHALL discard stimulation queued before it, rather than deliver it, and SHALL log that it did. In real-time mode the spikes held for an open window SHALL be capped to the most recent window-length of activity.

#### Scenario: Freeze and resume
- **WHEN** a consumer queues stimulation, no beat arrives for ten processing periods, and then a beat arrives
- **THEN** that stimulation is not delivered and the discard is logged

### Requirement: A lagging real-time substrate is visible
In real-time mode, a beat that arrives before the previous window boundary was consumed SHALL be counted and logged at WARNING on the first occurrence and every 100th.

#### Scenario: Beats faster than the loop consumes them
- **WHEN** two beats arrive before the loop consumes the first boundary
- **THEN** the overrun count increases and a WARNING is logged
