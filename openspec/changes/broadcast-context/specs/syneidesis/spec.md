## ADDED Requirements

### Requirement: Broadcasts carry the access threshold
Every broadcast SHALL record the access threshold in its metadata under `access_threshold`, so that a module can identify its accessed members: the coalition members whose score reaches the threshold. A broadcast is accessed when at least one member is.

#### Scenario: A rider below the threshold is not accessed
- **WHEN** a broadcast's coalition has members scoring 0.5 and 0.1 with an access threshold of 0.35
- **THEN** its metadata records the threshold 0.35, and only the member scoring 0.5 is accessed content

### Requirement: Processors hold the accessed broadcast as context
The context a processor holds SHALL be the featurization, weighted by intensity, of the accessed members of the latest accessed broadcast it has received, with the entity time elapsed since it received that broadcast. An inhibited broadcast SHALL leave the context unchanged, and before the first accessed broadcast there SHALL be no context.

#### Scenario: An inhibited broadcast does not replace the context
- **WHEN** a processor holds the context of an accessed broadcast and then receives an inhibited one
- **THEN** its context is unchanged apart from its age
