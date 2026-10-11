# event-bus Specification

## Purpose
The event-bus capability defines one canonical event schema and a module-stream layout for KAINE, together with an async Redis client, singleton accessor, stream retention via `MAXLEN`, startup configuration audit, and resilient roundtrip serialization.

## Requirements

### Requirement: Canonical event schema
The `kaine.bus` library SHALL define exactly one canonical event schema
that every module uses when publishing to or consuming from the event
bus. The schema SHALL contain the fields `source` (string), `type`
(string), `payload` (object), `salience` (float in the closed interval
0.0 to 1.0), `timestamp` (ISO-8601 UTC datetime), and `causal_parent`
(string or null). Events that fail validation SHALL be rejected at
publish time and SHALL NOT enter the bus.

#### Scenario: Valid event publishes successfully
- **WHEN** a caller invokes `bus.publish` with `source="soma"`,
  `type="wellness.update"`, `payload={"score": 0.82}`, `salience=0.3`,
  a current UTC timestamp, and `causal_parent=None`
- **THEN** the event is added to the `soma.out` stream and an entry id
  is returned

#### Scenario: Out-of-range salience rejected
- **WHEN** a caller invokes `bus.publish` with `salience=1.5`
- **THEN** the publish call raises `EventValidationError` before any
  Redis command is sent

#### Scenario: Missing required field rejected
- **WHEN** a caller invokes `bus.publish` omitting `source`
- **THEN** the publish call raises `EventValidationError` and the bus
  state is unchanged

### Requirement: Module output streams
Each module SHALL publish to a stream named `<module>.out` where
`<module>` is the module's registered name. The reserved stream
`workspace.broadcast` SHALL be owned exclusively by Syneidesis and
written to by no other module.

#### Scenario: Module name maps to stream
- **WHEN** the bus serves a `publish` call from a module registered as
  `chronos`
- **THEN** the event is appended to the Redis stream `chronos.out` and
  not to any other stream

#### Scenario: Non-Syneidesis write to workspace.broadcast rejected
- **WHEN** a module other than `syneidesis` calls `bus.publish_workspace`
- **THEN** the call raises `ReservedStreamError`

### Requirement: Async client and singleton accessor
The `kaine.bus` library SHALL expose an async client (`AsyncBus`) backed
by `redis.asyncio` and a module-level accessor `get_bus()` that returns
a process-wide singleton instance. All bus operations SHALL be coroutines.

#### Scenario: Singleton returns same instance
- **WHEN** `get_bus()` is called twice in the same process
- **THEN** both calls return the same client object identity

#### Scenario: Operations are awaitable
- **WHEN** caller invokes any of `publish`, `read`, `range`, `trim`,
  `subscribe_workspace`
- **THEN** the return value is a coroutine that completes against the
  configured Redis

### Requirement: Configuration and secrets loading
The bus SHALL load connection settings from `config/kaine.toml` and
secrets from `config/secrets.toml` (gitignored), with environment
variables `KAINE_REDIS_URL` and `KAINE_REDIS_PASSWORD` taking precedence
over file values. The bus SHALL refuse to start if no password is
available from any source.

#### Scenario: Env var overrides config file
- **WHEN** `config/secrets.toml` contains `redis_password = "fileval"`
  and the environment exports `KAINE_REDIS_PASSWORD=envval`
- **THEN** the bus connects with the password `envval`

#### Scenario: Missing password fails fast
- **WHEN** no password is present in env vars, `secrets.toml`, or
  `kaine.toml`
- **THEN** `get_bus()` raises `BusConfigError` on first call

### Requirement: Stream retention via MAXLEN
Every `publish` call SHALL trim the target stream to the configured maximum length using Redis Streams' approximate trimming (`XADD ... MAXLEN ~ N`). The default maximum SHALL be 100000 entries per stream and SHALL be overridable in `config/kaine.toml` either globally or per stream. The shipped configuration SHALL keep enough lookback on the high-rate streams that an observer or archive restart of several minutes loses no records: `topos.out` and `audition.out` SHALL be 12000 entries (about 20 minutes at 10 Hz; a `topos.out` entry is about 40 KB) and `workspace.broadcast` SHALL be 100000 entries. The memory these caps imply is checked before boot by the pre-boot bus budget row. The bus config loader SHALL merge an operator overlay TOML (`kaine.operator.toml`) into the base config so per-stream maxlen overrides are honored.

#### Scenario: Stream stays under configured cap
- **WHEN** 200000 events are published in succession to a stream with `maxlen = 100000`
- **THEN** the stream length reported by `XLEN` after the publishes is within 10% of 100000

#### Scenario: Latent-vector streams are capped lower by default
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[bus.per_stream_maxlen]` contains `"topos.out" = 12000`, `"audition.out" = 12000` and `"workspace.broadcast" = 100000`
- **AND** `[bus].default_maxlen` is 100000

#### Scenario: Operator overlay overrides per-stream maxlen
- **WHEN** `kaine.operator.toml` sets `"topos.out" = 500` and `load_bus_config()` is called
- **THEN** the resulting `BusConfig.per_stream_maxlen["topos.out"]` is 500

#### Scenario: Operator overlay does not affect unrelated keys
- **WHEN** `kaine.operator.toml` only changes per-stream maxlen
- **THEN** `BusConfig.default_maxlen` and other settings remain at their base-config values

### Requirement: Startup audit of Redis configuration
The bus SHALL refuse to proceed if it can confirm the Redis instance
lacks authentication, and SHALL emit a warning (without failing) for
checks it cannot verify. The `requirepass` check applies to **all
hosts**, loopback or not — KAINE's threat model includes future
deployment of the same code onto network-attached hosts where the
port mapping no longer enforces isolation.

The `bind` portion of the audit SHALL be skipped when the configured
`host` is a loopback name (`127.0.0.1`, `::1`, `localhost`), because
Docker port mapping (or equivalent transport-level loopback
restriction) enforces network isolation regardless of what Redis
binds inside the container. The `requirepass` check SHALL NOT be
skipped under any circumstance.

The `BusConfig` loader SHALL likewise refuse to load when no password
is available from any source, on any host.

#### Scenario: Unauthenticated Redis refuses to start the bus
- **WHEN** the configured Redis has no `requirepass` set
- **THEN** `get_bus()` raises `BusSecurityError`

#### Scenario: Loopback host without password fails the config load
- **WHEN** `BusConfig` is loaded with host `127.0.0.1` and no password
  in env / secrets / kaine.toml
- **THEN** `load_bus_config` raises `BusConfigError`

#### Scenario: Non-loopback host without password fails the config load
- **WHEN** `BusConfig` is loaded with host `10.0.0.5` and no password
  in env / secrets / kaine.toml
- **THEN** `load_bus_config` raises `BusConfigError`

#### Scenario: Containerized Redis bound 0.0.0.0 inside container accepted
- **WHEN** the configured host is `127.0.0.1` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus does not raise `BusSecurityError` for the bind value
  and continues to the (mandatory) `requirepass` check

#### Scenario: Non-loopback host with externally-bound Redis still refused
- **WHEN** the configured host is `10.0.0.5` and Redis reports
  `bind 0.0.0.0`
- **THEN** the bus raises `BusSecurityError`

#### Scenario: CONFIG-disabled Redis emits warning
- **WHEN** Redis returns an error to `CONFIG GET requirepass`
- **THEN** the bus logs a warning naming the unverified setting and
  continues operating

### Requirement: Roundtrip serialization integrity
Events SHALL roundtrip through the bus without lossy conversion of any
field. Floats SHALL retain full IEEE-754 double precision, payloads
SHALL preserve nested dict and list structures, and timestamps SHALL
deserialize to the original `datetime` object including timezone.

#### Scenario: Float salience roundtrips exactly
- **WHEN** an event with `salience=0.30000000000000004` is published
  and then read back
- **THEN** the deserialized salience compares equal to the original

#### Scenario: Nested payload roundtrips intact
- **WHEN** an event with a payload containing nested dicts and lists is
  published and read back
- **THEN** the deserialized payload equals the original by deep
  equality

### Requirement: Resilient decode of stored entries on read

Reading stored entries SHALL be resilient to malformed or legacy entries. When
decoding an entry read from a stream, an empty or unparseable `salience` value
SHALL be treated as `0.0` (the floor of the valid range) rather than raising.
The `read` and `range` operations SHALL guard decoding per entry: if an entry
cannot be decoded at all, it SHALL be skipped (logged at debug level, since a
large legacy backlog would otherwise flood the log on every read), and the scan
SHALL continue. A single malformed stored entry SHALL NOT cause `read` or
`range` to raise.

A cursor-advancing consumer SHALL be able to advance past an entire batch of
undecodable entries. The bus SHALL expose a way to read a batch that reports the
id of the last entry *scanned* (decodable or not), so that when a whole batch
decodes to nothing the consumer still advances its cursor past it rather than
re-reading the same poison batch indefinitely.

This tolerance applies only to the read path. Publish-time validation is
unchanged: publishing an event with a missing or out-of-range salience SHALL
still be rejected.

#### Scenario: Empty salience on a stored entry decodes to the floor

- **WHEN** a stream contains an entry whose `salience` field is an empty string
- **AND** that entry is read via `read` or `range`
- **THEN** the entry decodes to an event with `salience == 0.0`
- **AND** no exception is raised

#### Scenario: A poison entry mid-stream does not wedge the reader

- **WHEN** a stream contains a malformed legacy entry followed by well-formed
  entries
- **AND** a consumer reads the stream from before the malformed entry
- **THEN** `read` returns without raising
- **AND** the consumer's cursor advances past the malformed entry on the next
  read rather than re-reading it indefinitely

#### Scenario: An undecodable entry is skipped, not fatal

- **WHEN** a stream contains an entry that cannot be decoded into an event
- **AND** that stream is read via `read` or `range`
- **THEN** the undecodable entry is omitted from the returned results
- **AND** the remaining well-formed entries in the batch are still returned

#### Scenario: A fully undecodable batch still advances the cursor

- **WHEN** an entire batch read from a stream consists of undecodable entries
- **THEN** the batch read reports no decoded events
- **AND** it reports the id of the last entry scanned, non-null
- **AND** a cursor-advancing consumer advances past the whole batch on the next
  read rather than re-reading the same undecodable entries indefinitely

#### Scenario: Publish still rejects malformed salience

- **WHEN** an event with a missing or out-of-range salience is published
- **THEN** the publish is rejected, unchanged by this resilience requirement

### Requirement: Typical event sizes for bus budgeting
`kaine/bus/config.py` SHALL provide a table of typical serialized event sizes per stream, used only to estimate bus memory before boot. The table SHALL hold the measured values `topos.out` 40 KB, `workspace.broadcast` 6.6 KB, `chronos.out` 1.3 KB, `soma.out` 0.55 KB, `cycle.out` 0.25 KB and `audition.out` 0.4 KB, and every other stream SHALL use a 2 KB default. The table SHALL be documented as estimates, not limits.

#### Scenario: A measured stream uses its measured size
- **WHEN** the typical size of `topos.out` is looked up
- **THEN** it is 40 KB

#### Scenario: An unmeasured stream uses the default
- **WHEN** the typical size of `mnemos.out` is looked up
- **THEN** it is 2 KB

### Requirement: Workspace entries decode as broadcast events on read
On the read path (`read`, `range` and the cursor-advancing batch read), an entry with a `snapshot` field and no `type` field SHALL decode as an event with source `syneidesis`, type `workspace.broadcast`, the decoded snapshot as payload, the entry's timestamp, and salience equal to the highest selected member's salience clamped to [0, 1] (0.0 when there are no members). Publishing and `subscribe_workspace` SHALL be unchanged. An entry whose snapshot cannot be decoded SHALL still be skipped.

#### Scenario: A published broadcast is readable
- **WHEN** `publish_workspace` writes a snapshot and a consumer reads `workspace.broadcast` with `read`
- **THEN** it receives one event of type `workspace.broadcast` whose payload equals the snapshot

#### Scenario: A corrupt snapshot is skipped
- **WHEN** a workspace entry's `snapshot` is not valid JSON
- **THEN** the read skips it without raising

### Requirement: Every cursor-advancing consumer reads with the last scanned id
Every consumer that keeps a cursor on a bus stream SHALL read with `read_entries` and SHALL advance its cursor to the returned last-scanned id whenever one is returned, whether or not any entry in the batch decoded. A consumer that stops partway through a batch SHALL advance only to the last entry it handled, so the entries after it are read on the next poll. It SHALL handle the decoded entries exactly as it would without undecodable ones. A batch that advanced the cursor without decoding any entry SHALL count as progress for the consumer's poll pacing, and SHALL NOT be treated as an event of any kind. Only one-shot readers that keep no cursor MAY use `read`.

#### Scenario: A module input survives a long undecodable run
- **WHEN** more undecodable entries than one read returns are written to a stream a consumer follows, followed by a decodable event
- **THEN** the consumer handles the decodable event

#### Scenario: A skipped entry is not an interaction
- **WHEN** Chronos reads a batch of user-input entries none of which decode
- **THEN** its cursor advances past them
- **AND** its time since the last interaction is not reset

#### Scenario: New code cannot reintroduce the stall
- **WHEN** code under `kaine/` outside the bus and the listed one-shot readers calls `bus.read(`
- **THEN** a test fails naming the file and line

#### Scenario: A consumer that stops early resumes where it stopped
- **WHEN** a consumer stops handling a batch partway through
- **THEN** its cursor stays at the last entry it handled
- **AND** the remaining entries of that batch are read on its next poll

### Requirement: Bus calls do not lose a cancellation
Every `AsyncBus` operation, and every call made through `AsyncBus.client`, SHALL
raise `asyncio.CancelledError` when the calling task was cancelled during the
call and the Redis client caught that cancellation and returned normally. The
bus SHALL detect this by the task's cancellation count rising during the call.
It SHALL NOT raise when the count was already non-zero before the call and did
not rise, so cleanup that runs after a task caught its own cancellation can
still use the bus. Results and behaviour SHALL be unchanged when cancellation is
delivered normally.

#### Scenario: A swallowed cancellation ends a workspace subscription
- **WHEN** a task iterating `subscribe_workspace_block` is cancelled and the
  Redis client swallows the `CancelledError`, returning an empty reply
- **THEN** the subscription raises `CancelledError`, and the task finishes as
  cancelled

#### Scenario: Module shutdown is bounded despite a swallowed cancellation
- **WHEN** a module's workspace loop is subscribed and the bus client swallows
  the cancellation that `shutdown()` sends
- **THEN** `shutdown()` still returns promptly

#### Scenario: Cleanup after a caught cancellation still uses the bus
- **WHEN** a task catches its own `CancelledError` and then publishes to the bus
  before re-raising
- **THEN** the publish completes and returns its entry id

### Requirement: A non-blocking read never starts from "$"
The bus SHALL refuse a non-blocking stream read whose cursor is `"$"`, raising an error that names the stream, because such a read can never return an entry. A consumer that follows a stream from "now" SHALL resolve its starting cursor once with `last_entry_id` before its first read. A blocking read from `"$"` SHALL remain allowed.

#### Scenario: The silent stall becomes an error
- **WHEN** `read_entries`, `read` or `read_entries_block` is called with the cursor `"$"` and no block time
- **THEN** it raises an error naming the stream

#### Scenario: Sleep reaches a module that follows hypnos.out
- **WHEN** Chronos, Topos or Audition has initialized and Hypnos then publishes `hypnos.sleep.started`
- **THEN** that module suspends its forward-model adaptation
- **AND** it resumes after `hypnos.sleep.completed`
