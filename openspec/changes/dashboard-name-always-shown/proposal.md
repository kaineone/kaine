## Why

The eleventh test boot named its entity "Kaine Whipple", but no operator could see the name. The first configuration sets `conversation_enabled = false`, so the console that shows the name (#581) is not served and "/" redirects to diagnostics. At first boot the dashboard also starts before the cycle mints the identity and reads the name only at startup, so with the self-model module off it would show "KAINE" until the dashboard restarts.

## What Changes

- The entity's name appears in the header shared by every dashboard page, the diagnostics and health boards included, whatever `conversation_enabled` says. The name is identity data the operator already holds, and is not cognitive content.
- The dashboard re-reads the name from the self-model document and `state/identity/entity.json` when either file changes, checked at a short interval, so a name minted after the dashboard started appears without a restart.
- When no name exists yet, the header shows the existing placeholder.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: the entity name is always shown and kept current.

## Impact

- `kaine/dashboard/` (header template, name reader, refresh), docs, tests.
- Behaviour: none for the entity.
