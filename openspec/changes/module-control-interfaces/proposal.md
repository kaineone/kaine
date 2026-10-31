## Why

The paper now says: "Modules exchange events through typed bus streams. A few control couplings are direct calls, among them the affective reset at the end of sleep, boot-time wiring of drive tables and phase probes, and the arousal read that sizes the apertures and sets the scorer's gains" (§3.1), and "each event's envelope ... is validated at publish time, and its payload is free-form" (§3.4). Both sentences are true. Neither is backed by an interface definition a reader or a module author can check: "a few" is not a list, nothing stops a new direct call from appearing, and a module rebuilt on another theory has to discover by reading boot code which Python methods it must also provide.

The audit found these couplings (B1; triage M02, W6), all confirmed against the code:

- The sleep module is built holding the affect, episodic memory and world model objects (`kaine/boot/registry.py:351-363`) and calls `affect.affective_reset()` as its last phase (`kaine/modules/sleep/phases.py:406-418`), while the interoception module's fatigue reset already goes through `sleep.sleep.completed`.
- Boot calls setters on module objects: `affect.set_drive_relevance`, `set_development_probe` on affect, interoception and sleep, `sleep.set_paused_source` (`kaine/boot/wiring.py:408-450`), `language.set_lora_resolver` (`wiring.py:375`), `engine.set_whitelist_commands` (`wiring.py:395`), the shared speaking gate on vocal and audition (`wiring.py:470-487`), and `language.set_expects_self_model` with an `add_situation_fact` callback (`kaine/cycle/__main__.py:280-283`).
- Per-tick reads go through in-process getters: the workspace's state modulator reads `affect_provider.dimensional_state` (`wiring.py:145-149`), vision and audition read arousal through `set_arousal_provider` (`cycle/__main__.py:371-395`), and a sidecar reads `affect.serialize()` (`cycle/__main__.py:346`).

On payloads (B7): `Event.payload` is `dict[str, Any]` (`kaine/bus/schema.py:24`), `publish` adds no per-type check (`kaine/bus/client.py:301-309`), and the workspace broadcast is written by `publish_workspace` as a raw snapshot with source and timestamp only (`client.py:311-327`). The producer/consumer contract drift this permits has already cost data once (`fix-research-event-contracts`, archived 2026-09-09).

## What Changes

1. An interface specification, `module-control-interfaces`: every direct coupling between a module and anything outside it, by name, kind (boot configuration, per-tick read, command, time-critical gate), owner and reason. A test pins the inventory, so a new direct call fails CI until it is declared.
2. Typed protocols for each declared coupling, so a replacement module knows exactly which methods to provide.
3. The affective reset moves to the bus, because it is one module acting on another's state and the streams already carry the sleep module's other end-of-sleep signal: it becomes a command event with an acknowledgement. The arousal reads (the scorer's gain and the vision and audition apertures) stay direct, declared as per-tick neuromodulatory reads behind one read-only protocol, because `affect.state` is published at most once a second (`publish_interval_s = 1.0`, `config/kaine.toml:767`) and routing a 100 ms gain through it would add up to a second of lag. The speaking gate stays direct, declared as time-critical with its cited reason.
4. Payload contracts: each producer declares the payload schema of each event type it publishes, consumers declare the fields they read, and a test checks both against each other. Publish-time enforcement is available as an opt-in debug mode and is not the default, so the paper's "free-form" stays accurate.

## Capabilities

### New Capabilities

- `module-control-interfaces`: the declared inventory of direct couplings, their protocols, and the rule that undeclared couplings fail CI.

### Modified Capabilities

- `event-bus`: payload contracts per event type, checked in tests, with an opt-in publish-time check.
- `sleep`: the affective reset requested by a command event.
- `affect`: the affective reset performed on that command, with an acknowledgement.

## Impact

- Phase 1 (inventory, protocols, pin test, docs) changes no runtime behaviour.
- Phase 2 (the affective reset as a command) changes how the last sleep phase reaches the affect module and when it completes, so it is a change to the entity's experience and waits for the study.
- Phase 3 (payload contracts) adds tests and an opt-in check; default runtime behaviour is unchanged.
- Code: `kaine/boot/wiring.py`, `kaine/boot/registry.py`, `kaine/cycle/__main__.py`, `kaine/modules/sleep/`, `kaine/modules/affect/`, `kaine/modules/vision/`, `kaine/modules/audition/`, `kaine/workspace/` (state modulator), `kaine/bus/` (contracts), a new `kaine/boot/couplings.py` (the declared inventory).
- Docs: `docs/08-cognitive-cycle/` (an interfaces page), `docs/09-modules/affect.md`, `sleep.md`.
