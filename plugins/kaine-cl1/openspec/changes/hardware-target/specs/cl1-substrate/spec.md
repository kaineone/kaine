## ADDED Requirements

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
