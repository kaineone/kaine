# distributed-deployment Specification

## Purpose
TBD - created by archiving change distributed-substrate. Update Purpose after archive.

## Requirements

### Requirement: The live cognitive loop and stateful stores never run on untrusted compute

The system SHALL NOT distribute the live cognitive cycle, the modules in its
per-tick feedback path, or the stateful stores (Mnemos memory, the Eidolon
self-model, and the Redis workspace state) onto untrusted nodes (volunteer /
BOINC-style / public-swarm compute). This boundary holds even when such
distribution is technically requested.

Rationale recorded with the requirement: (a) the per-cycle latency budget cannot
absorb WAN round-trips or node intermittency; (b) shared mutable state across
intermittent partitioned nodes forces a CAP sacrifice that corrupts continuity
(the named identity-drift failure mode) or stalls the mind; (c) the load-bearing
zero-raw-persistence privacy invariant forbids raw sensory data leaving the host,
so perception modules cannot be offloaded even in principle.

#### Scenario: Offloading a live module onto an untrusted node is refused

- **WHEN** a configuration would place a per-tick module or a stateful store on
  an untrusted/volunteer node
- **THEN** the system treats this as disallowed and does not enable it
- **AND** the boundary and its rationale are documented in the deployment topology
  docs

### Requirement: Modules may be split across trusted hosts over an authenticated bus

The system SHALL support running disjoint subsets of modules in separate
processes across trusted hosts that share one authenticated Redis Streams bus.
A non-loopback bus SHALL require authentication and SHALL NOT be reachable while
bound to a wildcard address, as already enforced by the bus audit. Inter-module
coordination across hosts SHALL go through the bus or an explicitly-typed
contract, not in-process Python object references.

#### Scenario: A LAN bus split requires authentication

- **WHEN** the bus host is non-loopback
- **THEN** the bus audit requires `requirepass` and refuses a wildcard-bound,
  unauthenticated Redis

#### Scenario: The language organ runs on a separate trusted host

- **WHEN** Lingua runs in a process on a different trusted host from the
  coordinator
- **THEN** it obtains the Eidolon self-model via a bus-mediated snapshot rather
  than an in-process reference
- **AND** it emits the same speech and evaluation events as in the single-host
  deployment

### Requirement: Sanctioned decentralization is federation and encrypted backup, not sharding

The sanctioned decentralization paths SHALL be (a) federation of whole, trusted
peer instances exchanging high-level state, and (b) encrypted quorum-backup of
serialized state for resilience (secret-shared backup, never computation on
untrusted nodes). Sharding a single mind across untrusted nodes SHALL remain
disallowed per the boundary requirement above.

#### Scenario: Quorum-backup is backup, not remote computation

- **WHEN** state is distributed for resilience via encrypted quorum-backup
- **THEN** the distributed shares are used only to reconstruct state on a trusted
  host
- **AND** no live computation is performed on the untrusted holders of the shares

### Requirement: Quadlet cycle and Nexus units can reach the Redis bus
`quadlet/kaine-cycle.container` and `quadlet/kaine-nexus.container` SHALL set `Environment=KAINE_REDIS_URL=redis://:${KAINE_REDIS_PASSWORD}@kaine-redis:6379/0` so the in-container processes connect to the Redis service by container name, matching `compose/kaine.yml`.

#### Scenario: Cycle container has Redis URL
- **WHEN** `quadlet/kaine-cycle.container` is inspected
- **THEN** it contains `KAINE_REDIS_URL` pointing to `kaine-redis:6379/0`

#### Scenario: Nexus container has Redis URL
- **WHEN** `quadlet/kaine-nexus.container` is inspected
- **THEN** it contains `KAINE_REDIS_URL` pointing to `kaine-redis:6379/0`

### Requirement: Quadlet Qdrant healthcheck uses only tools in the image
`quadlet/kaine-qdrant.container` SHALL use a `bash /dev/tcp/127.0.0.1/6333` readiness probe, because the `qdrant:v1.18.0` image ships neither `curl` nor `wget`.

#### Scenario: Qdrant healthcheck does not invoke curl
- **WHEN** `quadlet/kaine-qdrant.container` is inspected
- **THEN** `HealthCmd` does not contain `curl` or `wget`

#### Scenario: Qdrant healthcheck succeeds in the minimal image
- **WHEN** the Qdrant container starts from the Quadlet unit
- **THEN** the healthcheck exits 0 and the container is marked healthy

### Requirement: Redis memory cap is consistent across deployment files
The Redis `--maxmemory` value SHALL be identical in `compose/kaine.yml`, `compose/redis.yml`, and `quadlet/kaine-redis.container`.

#### Scenario: Compose and Quadlet Redis caps match
- **WHEN** the three deployment files are compared
- **THEN** they all specify the same `--maxmemory` value
