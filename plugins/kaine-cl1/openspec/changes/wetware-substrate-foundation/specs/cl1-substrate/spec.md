## ADDED Requirements

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
(silicon default unchanged) or subclass within this repo — never edit the pinned
KAINE dependency or the vendored simulator.

#### Scenario: Event shapes are preserved

- **WHEN** a module runs with its `cl1` backend selected
- **THEN** its published `<name>.out` events have the same schema as under the
  silicon backend

#### Scenario: The overlay is inert when unused

- **WHEN** no module selects the `cl1` backend
- **THEN** the system behaves identically to pure KAINE
