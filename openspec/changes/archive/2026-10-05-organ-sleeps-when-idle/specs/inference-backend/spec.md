## ADDED Requirements

### Requirement: The organ unloads when idle and reloads on demand
Every launch path of the organ server SHALL pass llama-server's `--sleep-idle-seconds`: the compose default command, the Quadlet unit and the native launcher. The value SHALL come from `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS` in compose and Quadlet, and from `[lingua].model_server_sleep_idle_seconds` for the native launcher. The default SHALL be 600. When no cycle or study has sent an inference request for that long, the organ SHALL unload its model, and the next inference request SHALL reload it without operator action.

#### Scenario: KAINE stops and the GPU is freed
- **WHEN** the last cycle or study stops and no inference request arrives for the configured seconds
- **THEN** the organ reports that it is asleep and holds no model in memory

#### Scenario: A new run wakes the organ
- **WHEN** a cycle sends an inference request to a sleeping organ
- **THEN** the organ reloads the model and answers the request

### Requirement: Health reports a sleeping organ as up and asleep
Nexus's organ health probe and the pre-boot `Chat LLM` row SHALL read the server's `/props` and report a sleeping organ as up and asleep, never as degraded or down. Health polling SHALL NOT wake a sleeping organ. The pre-boot `Organ content` row SHALL still send a real completion, so a boot proves the organ answers.

#### Scenario: Nexus while nothing runs
- **WHEN** the organ is asleep and Nexus polls its health
- **THEN** the organ shows as up and asleep, and it stays asleep
