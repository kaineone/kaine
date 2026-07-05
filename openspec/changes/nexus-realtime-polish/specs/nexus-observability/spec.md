## MODIFIED Requirements

### Requirement: The diagnostics surface streams over a single multiplexed connection

The Nexus console SHALL open at most one Server-Sent-Events connection to the
diagnostics stream, and client features SHALL receive events through a client-side
dispatcher rather than each opening its own `EventSource`. The server SHALL
privacy-filter and encode each bus event once per event, then fan the filtered event
to connected clients, rather than filtering once per client.

The UI SHALL pause its streams and pollers when the document is hidden, and SHALL
surface a visible connection status (live / reconnecting) so a dropped link does not
silently present stale values as current. Health polling SHALL NOT poll faster than
the health cache's time-to-live.

The render-layer privacy boundary (diagnostics templates render only metadata, never
cognitive content) SHALL remain unchanged.

#### Scenario: Console uses one stream

- **WHEN** the console page is open
- **THEN** exactly one diagnostics `EventSource` connection is established
- **AND** each bus event is privacy-filtered once before fan-out

#### Scenario: Hidden tab stops streaming

- **WHEN** the operator backgrounds the tab
- **THEN** the SSE and pollers pause until the tab is visible again

#### Scenario: Dropped connection is visible

- **WHEN** the stream disconnects
- **THEN** the UI shows a reconnecting state rather than continuing to display stale
  values as live

### Requirement: The status chip reflects real cycle state

The left-rail status chip SHALL reflect the real cognitive-cycle state, not a hardwired
awake/sleeping binary. It SHALL be a four-state chip — OFFLINE, FROZEN, SLEEPING,
AWAKE — computed live from the single diagnostics stream (the pushed cycle-status and
operator-freeze flag, plus Hypnos sleep/wake events), with priority
OFFLINE > FROZEN > SLEEPING > AWAKE. Its page-load default (before any live data
arrives) SHALL be OFFLINE, since with no live data the console cannot know a cycle is
running. The chip inputs SHALL be metadata-only (cycle running-state, freeze flag,
sleep/wake) and carry no cognitive content.

#### Scenario: No cycle running reads OFFLINE

- **WHEN** no cognitive cycle is running (including at page load, before live data)
- **THEN** the status chip reads OFFLINE (not AWAKE)

#### Scenario: Frozen cycle reads FROZEN

- **WHEN** the cycle is running but the experiential loop is frozen (operator freeze)
- **THEN** the status chip reads FROZEN

#### Scenario: Running cycle reflects sleep/wake

- **WHEN** the cycle is running, not frozen, and Hypnos is asleep
- **THEN** the status chip reads SLEEPING
- **AND WHEN** Hypnos wakes, the chip reads AWAKE
