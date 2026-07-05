## ADDED Requirements

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
