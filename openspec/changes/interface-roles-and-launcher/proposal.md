## Why

The specs for setting up and running an entity have drifted apart as the project evolved:

- The first-run wizard spec says the wizard SHALL NOT boot the entity.
- `browser-first-run` (archived 2026-10-06) was phase 1 of three. Phase 2 was a single launcher, a desktop icon or one command, that starts the services in order and shows status lights. Phase 3 was a one-download installer. Neither later phase was ever proposed.
- That change left research runs to the automated research runner. The runner automates its steps once started, but starting it takes several compose commands typed by hand: the bus and model server, the trainer profile, the media and study overlays, then `init` and `run` (see the ignition study guide). A person cannot yet bring up a study run, the seed included, on their own.
- The Fieldtrip plan for a phone control plane (September 2026) was paused before any work began.

The operator's direction (2026-10-28) settles the roles and the goal. Fieldtrip is the basic interface: people use it to interact with entities, remote ones or local ones on smaller devices such as phones, and to take a few minor admin and operator actions. Nexus is the deeper control plane for operators. Bringing a system up, a study run included, is an automated, scripted task that a person starts with a click or two in a small GUI, and it needs no agent or terminal.

## What Changes

Nothing changes yet. This change records the direction on the roadmap. It is design only and not scheduled. Open points:

- **One bring-up script.** It starts the services in order, checks each one, and then starts either an entity or a research study run, with plain status at every step. A failure says what happened and what to do next. The study run covers the runner's whole bring-up, including the media and study mounts and the trainer.
- **Where the GUI lives.** Fieldtrip, Nexus or both offer the start. The likely split is a minimal start and status in Fieldtrip, with configuration and the gated actions in Nexus.
- **Gates kept.** Spawning stays a deliberate action behind the CAL welfare acknowledgement and the pre-boot check, as `browser-first-run` built it. A research run keeps its safety-net gate and needs no operator presence.
- **Specs to reconcile.** The first-run wizard's "SHALL NOT boot the entity", `browser-first-run`'s exclusion of research mode from setup, and the paused Fieldtrip plan.
- **Size.** Nexus and Fieldtrip are both close to feature complete, so the changes to each should be small. Most of the new work is the bring-up script.

## Capabilities

### New Capabilities

None yet. The design step decides them.

### Modified Capabilities

Expected: `first-run-wizard`, `container-deployment` and the ignition study's operator documentation. The design step confirms the list.

## Impact

None until the design step splits the work into implementation changes. Fieldtrip lives in its own repository, so its part becomes a change there.
