## ADDED Requirements

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
