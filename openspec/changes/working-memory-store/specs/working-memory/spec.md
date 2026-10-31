## ADDED Requirements

### Requirement: Working memory ships off and is bit for bit absent when off
`[working_memory].arm` SHALL be one of `off`, `notes`, `context` or `both`, and the shipped configuration SHALL set `off`. With `off`, no store SHALL be built, every snapshot SHALL carry an empty `held` field, and every context, null context and organ prompt SHALL equal those of the build before this change. Any other value or an unknown key SHALL be a configuration error.

#### Scenario: Off equals the current build
- **WHEN** the same candidates and broadcast ticks drive the workspace, a processor and the language module once on the build before this change and once with `arm = "off"`
- **THEN** the snapshots apart from the empty `held` field, the contexts, the null contexts and the prompts are identical

#### Scenario: An unknown arm is refused
- **WHEN** `[working_memory].arm = "all"`
- **THEN** loading the configuration raises a configuration error

### Requirement: The store is filled only from accessed members
With any arm other than `off`, the workspace SHALL add each accessed member of a broadcast to the store after the access decision and before composing the snapshot. Coalition members that were not accessed and members of inhibited broadcasts SHALL NOT enter the store. In the matched arm the matched draw's accessed members, and in the pooled arm every member, SHALL enter it.

#### Scenario: An inhibited broadcast adds nothing
- **WHEN** the store holds two entries and an inhibited broadcast arrives
- **THEN** the store still holds the same two entries

#### Scenario: The accessed member of this tick is held
- **WHEN** a broadcast accesses a vision report
- **THEN** that broadcast's `held` field lists the vision report first

### Requirement: Same-kind replacement and capacity displacement
The store SHALL hold at most `capacity` entries, default 4, allowed 1 to 8. A new entry whose source and event type match an entry SHALL replace it and move to the front. Otherwise the new entry SHALL enter at the front, and when the store is full the entry accessed longest ago SHALL be displaced.

#### Scenario: A newer report of the same kind replaces the older one
- **WHEN** the store holds a vision report and an audition report and a new vision report is accessed
- **THEN** the store holds the new vision report first and the audition report second, and the old vision report is gone

#### Scenario: A fifth kind displaces the oldest
- **WHEN** the store holds four entries of different kinds and a member of a fifth kind is accessed
- **THEN** the entry accessed longest ago is displaced and the new one is first

### Requirement: Entries are dropped by age and cleared at sleep and boot
An entry whose access lies more than `max_age_s` entity seconds in the past, default 30, SHALL be dropped. The store SHALL be empty at boot and SHALL be cleared at sleep onset. It SHALL NOT be written to `serialize()`, a checkpoint, a preservation bundle or any log payload.

#### Scenario: A stale entry is dropped
- **WHEN** an entry was accessed 31 entity seconds ago and nothing has displaced it
- **THEN** the next broadcast's `held` field omits it

#### Scenario: Sleep clears the store
- **WHEN** the sleep module publishes the start of a sleep
- **THEN** the store is empty and the next broadcast carries an empty `held` field

#### Scenario: Preservation carries no store
- **WHEN** a preservation bundle is captured while the store holds entries
- **THEN** the bundle holds no store entries

### Requirement: The broadcast carries the store and the log records it without payloads
Every snapshot SHALL carry `held`, the store's entries newest first, each with its stream-qualified id, event, access tick and access time. The research log SHALL record each held entry's id, source, event type and age and SHALL NOT record its payload.

#### Scenario: The log holds no held payload
- **WHEN** a broadcast holds an entry whose payload carries a heard-text field
- **THEN** the research log's record of that broadcast lists the entry's id, source, type and age and no payload field

### Requirement: The context arm builds the context from the store
With `context` or `both`, each processor's context SHALL be built from the held entries of the latest broadcast it received, each weighted by its intensity, with the intensity-weighted mean of the entries' ages as the context age. The null context SHALL be built by the A.8 substitution rule over the same entries.

#### Scenario: Capacity one equals the current context
- **WHEN** one access per broadcast is in force, `capacity = 1` and `arm = "context"`, and the same broadcasts drive a processor as with `arm = "off"`
- **THEN** the context vectors and null contexts are identical

#### Scenario: Two held kinds both enter the context
- **WHEN** the store holds a vision report and an interoception report and the latest broadcast accessed only the vision report
- **THEN** the processor's context carries the source mass of both
