## ADDED Requirements

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
Every `publish` call SHALL trim the target stream to the configured
maximum length using Redis Streams' approximate trimming
(`XADD ... MAXLEN ~ N`). The default maximum SHALL be 100000 entries
per stream and SHALL be overridable in `config/kaine.toml` either
globally or per stream.

#### Scenario: Stream stays under configured cap
- **WHEN** 200000 events are published in succession to a stream with
  `maxlen = 100000`
- **THEN** the stream length reported by `XLEN` after the publishes is
  within 10% of 100000

### Requirement: Startup audit of Redis configuration
On first connection, the bus SHALL probe Redis for its bind address and
authentication state and SHALL refuse to proceed if it can confirm
external accessibility or absent authentication. When Redis denies the
audit query (a common hardening setting), the bus SHALL emit a warning
and continue.

#### Scenario: Unauthenticated Redis refuses to start the bus
- **WHEN** the configured Redis has no `requirepass` set
- **THEN** `get_bus()` raises `BusSecurityError`

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
