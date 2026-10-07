# local-service-clients Specification

## Purpose
This capability keeps every runtime client of KAINE's own local services from following proxy settings, so cognitive traffic never leaves the host; only setup-time downloads of public, hash-pinned artifacts may use a proxy.

## Requirements

### Requirement: Clients of KAINE's own services ignore proxy settings
Every runtime HTTP client in `kaine/` that talks to a KAINE service (the organ, speech-to-text, text-to-speech, the trainer, Nexus probes) SHALL ignore proxy environment variables. Only setup-time downloads of public weights and wheels MAY use a proxy, and they SHALL be named in an allowlist that a guard test enforces.

#### Scenario: A host has a proxy configured
- **WHEN** `HTTP_PROXY` or `ALL_PROXY` is set in the environment of a running cycle
- **THEN** the organ prompts, audio and speech still go directly to the local services, never to the proxy

#### Scenario: A new client is added without the setting
- **WHEN** a module adds an httpx client or request call without disabling environment trust
- **THEN** the guard test fails and names the file and line
