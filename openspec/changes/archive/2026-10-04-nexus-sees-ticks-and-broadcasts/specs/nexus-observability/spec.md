## ADDED Requirements

### Requirement: The diagnostics streams are streams that something writes
Every stream returned by `diagnostics_streams()` SHALL be one the system writes: `workspace.broadcast` or `module_stream(name)` for a canonical module name. It SHALL include `cycle.out`, so `cycle.tick`, `cycle.rates` and `cycle.time_scale` events reach Nexus. It SHALL NOT list an event type as if it were a stream.

#### Scenario: No phantom stream
- **WHEN** the diagnostics stream list is built
- **THEN** every entry is `workspace.broadcast` or the output stream of a canonical module, and `cycle.tick` is not in the list

#### Scenario: Ticks reach the feed
- **WHEN** the cycle publishes a `cycle.tick` event
- **THEN** the Nexus bridge relays it to diagnostics clients

### Requirement: Charts read the events that carry their data
The coherence chart SHALL plot `metadata.coherence` from `workspace.broadcast` events when it is a number. The salience chart SHALL plot only module events, not events from source `cycle` or `syneidesis`.

#### Scenario: Coherence from a broadcast
- **WHEN** a `workspace.broadcast` event carries `metadata.coherence = 0.42`
- **THEN** the coherence chart receives the sample 0.42

#### Scenario: Operational events stay off the salience chart
- **WHEN** a `cycle.tick` event with salience 0.05 arrives
- **THEN** the salience chart receives no sample from it

### Requirement: The bridge relays every event published after it starts
The Nexus bus bridge SHALL resolve each stream's starting cursor to that stream's last entry id at the time of its first successful read (`0-0` when the stream is empty) and SHALL relay, after the privacy filter, every decodable event published to its streams after that point. A failed resolution SHALL be retried on the next poll. A non-blocking read SHALL never be issued with the `$` cursor.

#### Scenario: Events after start reach a client
- **WHEN** the bridge has started and a module publishes an event to a diagnostics stream
- **THEN** a connected diagnostics client receives that event, filtered, within a poll interval

#### Scenario: History before start is not replayed
- **WHEN** a stream already holds entries when the bridge starts
- **THEN** those entries are not relayed, and the next new entry is

