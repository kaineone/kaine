## ADDED Requirements

### Requirement: The bus and memory store run without containers
The Redis and Qdrant bootstraps SHALL offer a native path that needs no container runtime and no root: a user-level server per service, bound to loopback on the KAINE ports, authenticated with the same generated secret the container path uses, persisting under the entity's state directory, and supervised by `systemd --user` when available or as a supervised background process otherwise. A downloaded server binary SHALL be pinned by version and sha256 and refused on mismatch. Without an explicit choice, the bootstraps SHALL use containers when a container runtime is present and the native path otherwise.

#### Scenario: A host without Docker
- **WHEN** the Redis bootstrap runs on a host with no container runtime
- **THEN** a user-level redis-server starts on 127.0.0.1:6479 with the generated password, and the bus answers PONG

#### Scenario: A tampered download
- **WHEN** the Qdrant binary's sha256 does not match the pinned value
- **THEN** the bootstrap stops without starting it
