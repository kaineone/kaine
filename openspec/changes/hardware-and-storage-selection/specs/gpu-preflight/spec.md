## ADDED Requirements

### Requirement: The gate names shared services and never asks to close them
When a process holding memory on a device the cycle needs belongs to a service marked `[services.<name>].shared = true`, the gate SHALL name that service as shared with the operator's other applications. It SHALL suggest a placement that avoids the device (another allowed device, a lighter backend rung, or CPU) instead of asking the operator to close it. The gate SHALL still never terminate any process.

#### Scenario: A shared server fills the vision device
- **WHEN** a shared text-to-speech server leaves the vision device below the free-memory minimum
- **THEN** the block message names the shared service
- **AND** it suggests an alternative placement
- **AND** it does not ask the operator to close the service

### Requirement: The consumer list says when it cannot see the host
When the gate runs where host processes are not visible, such as inside a container's process namespace, it SHALL say that its consumer list is limited to the container. It SHALL report the device's used memory. It SHALL NOT attribute memory held outside the container to a process inside it.

#### Scenario: Gate inside a container
- **WHEN** a host process holds most of a device and the gate runs in a container
- **THEN** the message states that host processes are not visible from the container
- **AND** it reports the device's used and free memory
