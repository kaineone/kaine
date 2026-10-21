## ADDED Requirements

### Requirement: The console shows the entity's name
The dashboard SHALL show the entity's name in the console's page title and left rail. At start it SHALL read the name from the self-model file at `[self_model].persistence_path` through the self-model document loader, and when that file holds no name, from an optional `name` field of the identity file. While running it SHALL take the name from the `name` field of each `self_model.document` event on `self_model.out`, read by a bridge observer whether or not a browser is connected, and when the app starts it SHALL read the newest such event already on the stream. When no source gives a non-empty name the console SHALL show "KAINE". A missing, unreadable or undecryptable file and a bus error SHALL leave the name as it was and SHALL NOT stop the dashboard. The observer SHALL read no other field of the event.

#### Scenario: The persisted launch name is shown
- **WHEN** the self-model file holds the name "Kaine Voxel" and the dashboard starts
- **THEN** the console's title and left rail show "Kaine Voxel"

#### Scenario: A rename arrives on the bus
- **WHEN** a `self_model.document` event with the name "Lyra" is read from `self_model.out` and no browser is connected
- **THEN** the next console page shows "Lyra"

#### Scenario: No name anywhere
- **WHEN** the self-model file and the identity file are absent and the bus holds no `self_model.document` event
- **THEN** the console shows "KAINE"

### Requirement: The status chip starts from the server's sleep state
The dashboard SHALL follow `sleep.sleep.started` and `sleep.sleep.completed` on `sleep.out` through a bridge observer and, when the app starts, SHALL read the newest of the two among the stream's last 500 entries. The console SHALL render that state on the status chip as a `data-sleeping` attribute, and the chip script SHALL start from it, so a page opened during a sleep shows "sleeping" once the cycle reports running.

#### Scenario: A page opened during a sleep
- **WHEN** the newest sleep lifecycle event is `sleep.sleep.started` and the console is loaded
- **THEN** the chip carries `data-sleeping="true"` and reads "sleeping" after the first metrics snapshot reports the cycle running

#### Scenario: An observer error does not stop the bridge
- **WHEN** an observer raises on an event
- **THEN** the error is logged and the bridge still delivers that event and later ones
