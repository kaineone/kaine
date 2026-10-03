# Nexus receives cycle ticks and workspace broadcasts, and charts them correctly

## Why
An audit of the diagnostics streams on 2026-10-03, done for `workspace-graph-only-recording`, found that two of the streams Nexus subscribes to deliver nothing, and that one chart reads the wrong events:

- **`cycle.tick` is not a stream.**
  - `diagnostics_streams()` (`kaine/evaluation/stream_registry.py`) lists a stream named `cycle.tick` and excludes `cycle.out` "in favor of the `cycle.tick` event type".
  - The engine publishes `cycle.tick` (and `cycle.rates`, `cycle.time_scale`) as events with source `cycle`, and `publish` routes them by source to `cycle.out`. No `cycle.tick` stream ever exists.
  - So Nexus never sees ticks. The rate chart never shows the effective conscious-access rate that the adaptive-access-rate change specified.
- **Workspace broadcasts never reach Nexus.**
  - `publish_workspace` writes entries with `snapshot`, `timestamp` and `source` fields and no `type`.
  - The Nexus bridge and the Nexus record read through `bus.read`, whose decoder requires a non-empty `type`. Every broadcast is therefore skipped as undecodable.
  - The `nexus-observability` spec already requires the bridge to relay `workspace.broadcast`; the code does not meet it.
- **The coherence chart reads the wrong events.** It reads `metadata.coherence` from events with source `cycle` and expects a dict. Coherence is a float on `workspace.broadcast` (`syneidesis.py`). The spec's coherence chart requirement is unmet.

Research impact: **instrument (diagnostics display) only.**
- Nothing the entity perceives or does changes. The broadcast published on the bus is unchanged.
- Studies keep the Nexus record off (`workspace-graph-only-recording`), so study data is unchanged.

## What changes
- **Diagnostics streams name real streams.**
  - `diagnostics_streams()` lists `cycle.out` in place of the phantom `cycle.tick`.
  - A guard test requires every listed stream to be a stream something writes: a `module_stream()` of a canonical module, or `workspace.broadcast`.
- **The bus decodes workspace entries.** On the read path, an entry with a `snapshot` field and no `type` decodes as an event with:
  - source `syneidesis`;
  - type `workspace.broadcast`;
  - the snapshot as its payload;
  - the entry's timestamp;
  - salience equal to the highest selected member's salience, clamped to [0, 1], or 0.0 with no members.

  Publishing is unchanged, and `subscribe_workspace` keeps returning snapshot dicts. The privacy filter, which removes content and vectors at every depth, applies to broadcasts like any other diagnostics event.
- **The charts read the right events.**
  - Coherence comes from `workspace.broadcast` events whose `metadata.coherence` is a number.
  - The salience chart plots module events only, skipping `cycle` and `syneidesis` events, which carry operational or aggregate saliences.
  - The routing is a small pure function exposed to the page, so a real-browser test can check it.

## Capabilities
### Modified Capabilities
- `nexus-observability`: the diagnostics streams are real streams, ticks reach Nexus, and the coherence chart reads broadcasts.
- `event-bus`: workspace entries decode as `workspace.broadcast` events on the read path.

## Impact
- **Code:**
  - `kaine/evaluation/stream_registry.py`
  - `kaine/bus/client.py` (read-path decode)
  - `kaine/nexus/static/nexus.js` (chart routing)
- **Tests:**
  - stream registry guard
  - bus decode of a real `publish_workspace` entry
  - bridge relays a broadcast
  - chart routing in a real browser
- **Docs:** the Nexus chapter's chart descriptions, if they name the sources.
