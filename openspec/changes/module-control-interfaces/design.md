# Design: module control interfaces

## Context

KAINE's modules publish typed events to streams and read each other's streams; the workspace reads candidates and publishes the broadcast. Beside that, boot and the cycle wire a set of direct Python calls between module objects. Some are configuration handed over once at boot. Some are per-tick reads. One is a command from one module to another. One is a gate shared between two modules for corollary discharge. The revised paper names three of them and says "among them" (§3.1). The specification layer has no list at all: `openspec/specs/module-pattern` defines the lifecycle and serialization contract, `architecture-boundaries` defines import layering, `event-bus` defines the envelope, and none of them says which method calls a module must accept to work in the cycle.

Prior work this builds on: `stream-wiring-quality` (canonical stream names and the stream-registry drift test, merged as #394), `fix-research-event-contracts` (archived 2026-09-09; consumer allowlists adapted to real producer payloads, three stream lists diffed against one registry), `edge-import-contracts` and `import-boundary-enforcement` (import layering). None of them covered direct calls or payload schemas. The May 2026 architecture audit left a "canonical registry" follow-up open; payload contracts are that follow-up.

## The inventory (origin/main cb41895b)

| Coupling | Kind | Site | Disposition |
| --- | --- | --- | --- |
| sleep → `affect.affective_reset()` | command | `kaine/boot/registry.py:351-363`, `kaine/modules/sleep/phases.py:406-418` | moves to a command event (D3) |
| sleep → episodic memory object (consolidation phases) | command | `registry.py:351-363`, `kaine/modules/sleep/module.py:95-130` | declared; follow-up (D6) |
| sleep → world model object (scenario window open and close) | command | same | declared; follow-up (D6) |
| sleep → `sequence_resetters` | command | `sleep/module.py:97`, `175` | declared; follow-up (D6) |
| `affect.set_drive_relevance` | boot configuration | `kaine/boot/wiring.py:408` | declared protocol |
| `set_development_probe` on affect, interoception, sleep | boot configuration (a callable read later) | `wiring.py:433-446` | declared protocol |
| `sleep.set_paused_source` | boot configuration (a callable read later) | `wiring.py:450` | declared protocol |
| `language.set_lora_resolver` | boot configuration | `wiring.py:375` | declared protocol |
| `engine.set_whitelist_commands` | boot configuration | `wiring.py:395` | declared protocol |
| `language.set_expects_self_model`, `add_situation_fact` callback | boot configuration | `kaine/cycle/__main__.py:280-283` | declared protocol |
| vocal and audition `set_speaking_gate` (shared `SpeakingGate`) | time-critical gate | `wiring.py:470-487` | stays direct, declared (D4) |
| workspace state modulator reads `affect_provider.dimensional_state` | per-tick read | `wiring.py:145-149` | stays direct behind `ArousalSource` (D2) |
| vision and audition `set_arousal_provider` | per-tick read | `cycle/__main__.py:371-395` | stays direct behind `ArousalSource` (D2) |
| sidecar reads `affect.serialize()` and other modules' `serialize()` | observation read | `cycle/__main__.py:346`, `410` | declared; read-only (D5) |
| cycle `set_sleep_source` reads the sleep module's state | per-tick read | `cycle/__main__.py:2450` | declared protocol |
| gate runner setters (sensory schedule, pause sources, clock, maturation hook) | boot configuration | `cycle/__main__.py:2165`, `2864-2899` | declared protocol |

The implementation task re-derives this table from the code (task 1.1) rather than trusting it; the pin test then holds whatever the code has.

## Decisions

### D1. The inventory is data, and a test holds the code to it

`kaine/boot/couplings.py` holds one record per coupling: name, kind, caller, callee module, method, protocol, reason. `tests/test_control_coupling_inventory.py` walks the AST of `kaine/boot/` and `kaine/cycle/` for calls to methods on objects obtained from the module registry (`registry.get(...)`, factory results) and fails on any call not in the inventory, and on any inventory entry the code no longer makes. The docs page is generated from the same records, so the paper's "among them" can point to one complete list.

Alternatives considered: a hand-written docs page only (rejected: it drifts, which is how "only through append-only streams" survived); forbidding every direct call (rejected: D2 and D4 give reasons some should stay).

### D2. Arousal reads stay direct, behind one read-only protocol

The audit proposed reading arousal for scoring from the latest `affect.state` event. That event is published at most once per second (`publish_interval_s = 1.0`, `config/kaine.toml:767`; `kaine/modules/affect/module.py:1314`), while the state modulator and the apertures read the live value every 100 ms tick. Routing them through the event would add up to a second of lag to a gain the paper models on the phasic locus coeruleus response (§3.4, Nieuwenhuis, Aston-Jones and Cohen 2005), whose timescale is a few hundred milliseconds. Publishing `affect.state` every tick instead would multiply that stream's traffic by ten for one scalar.

So the three arousal reads stay direct, and become one declared protocol, `ArousalSource.arousal() -> float`, which the affect module implements and which carries no other state. The workspace, vision and audition receive an `ArousalSource`, never the affect module object, so a replacement affect module provides one method rather than `dimensional_state()` and its return type. The interface spec says why the read is direct.

Alternative considered: a dedicated `affect.arousal` stream at tick rate. Kept as the route if a future module needs arousal across a process boundary (for example a module moved out of process by `module-residency-and-speech-tiers`); not needed in-process.

### D3. The affective reset becomes a command with an acknowledgement

The sleep module publishes `sleep.affective_reset.requested` (payload: the sleep index and a request id) as phase 5. The affect module consumes it, performs exactly the reset its spec defines, and publishes `affect.affective_reset.done` with the request id and success. The sleep module's phase 5 waits for the acknowledgement up to a configured timeout and records phase success from it. A timeout records `success = False` for the phase with reason `no_ack`, exactly as a raised reset is recorded today, and the sleep still ends.

The interoception module's fatigue reset already follows `sleep.sleep.completed` (`phases.py:412-416`), so the bus route has precedent. The sleep spec requires that "a cancelled sleep still ends with the affective reset"; the command path keeps that by publishing the request in the same `finally` path that calls the method today.

Alternative considered: affect resets itself on `sleep.sleep.completed`. Rejected because the sleep spec orders the affective reset as the last *phase*, before completion, and the completion event's `phases` payload reports its result; resetting after completion would change that order and the record.

### D4. The speaking gate stays direct

The shared `SpeakingGate` lets audition suppress the entity's own voice while vocal is speaking. That is corollary discharge, which the paper already cites for the speech guard (Crapse and Sommer 2008), and it must act within the same audio window, which a bus round trip cannot guarantee. It stays a direct shared object, declared as `time_critical` in the inventory with that reason.

### D5. Observation reads of `serialize()` are declared read-only

The sidecar and the resume checkpoint read modules' `serialize()`; that is the persistence contract of `module-pattern` and is already specified there. The inventory records them as observation reads and the protocol states they must not change module state.

### D6. Sleep's other commands are declared now and moved later

Sleep drives episodic memory's consolidation phases, the world model's scenario window and the sequence resetters through object references. These are module-to-module commands like the affective reset. They are declared in phase 1 and moved to command events in a follow-up change, after `world-model-content-prediction` and the memory workstream settle what those modules expose, so the interfaces are not redesigned twice.

### D7. Payload contracts are checked in tests; publish-time checking is opt-in

Each producing module declares, per event type, a payload model (a pydantic model or a JSON schema) in a contracts module next to the producer. Each consumer declares the fields it reads per event type. `tests/test_payload_contracts.py` checks that every consumer field exists in its producer's model with a compatible type, and the producers' own tests validate the payloads they emit against their models. `[bus].validate_payloads = "off" | "warn" | "enforce"` adds a publish-time check; the default is `off`.

Why not enforce at publish by default: a rejected `affect.state` or `interoception.report` at runtime would silently remove a signal the welfare net and the entity's regulation read, which is worse for the entity than a malformed field the consumer already tolerates. The drift class this guards against is a build-time defect, and tests catch it before it ships. The revised paper's "its payload is free-form" stays accurate; if the paper later wants "validated", `enforce` exists, with its runtime cost measured first (task 3.4).

The workspace broadcast keeps its own record type (`publish_workspace`), and the interface spec documents it as a separate type with source and timestamp and no intensity or causal parent, so no text implies it is an `Event`.

## Risks

- The AST pin test misses dynamic calls (`getattr(obj, "set_" + name)`). The existing code already uses `getattr(affect, "set_development_probe", None)`; the test resolves string-literal `getattr` calls and treats any non-literal one under `kaine/boot` or `kaine/cycle` as a failure that must be declared.
- The command path for the reset can deadlock if the affect module is frozen or restarting. The timeout bounds it; the supervisor's restart path re-subscribes the affect consumer; a test covers a reset requested while affect is restarting.
- Contract models drift from producers: each producer's tests validate its own emitted payloads, so the model is checked where the payload is built.

## Migration and ordering

- Phase 1 (tasks 1.x): inventory, protocols, pin test, docs. No runtime behaviour changes; the `ArousalSource` refactor passes the same value at the same time. Can merge before the study's launch image is built, or any time after; it does not touch a running study.
- Phase 2 (tasks 2.x): the affective reset as a command. Changes the last sleep phase's mechanism and timing. After the module-addition study.
- Phase 3 (tasks 3.x): payload contracts in tests (any time, test-only) and the opt-in publish check (after the study, since the image changes).
- Follow-up (separate change): sleep's other commands (D6).

## Welfare and admissibility notes

Phase 1 is behaviour-neutral, and the pin test proves it: the `ArousalSource` returns the same float on the same tick. Phase 2 touches the affective reset, which clears the entity's drives, goals and affect at the end of every sleep and is the welfare net's means of relief (paper §6.5), so it is welfare-high-risk. Checks before merge: a test that the reset still runs on a cancelled sleep; a test that a timeout leaves the phase recorded as failed rather than silently succeeded; an offline replay comparing the post-sleep affect state from the method path and the command path on recorded sleeps, which must match; Claude's independent second review. No study run sees a mix of the two paths.

## Implementation estimate (LLM-agent terms)

Size M overall. Phase 1: one pull request of about 400 to 700 lines (inventory, protocols, AST test, generated docs page), 3 to 5 worker calls, one Claude review; about a day. Phase 2: one pull request of about 200 to 400 lines with tests, 2 to 3 worker calls, Claude review plus second review (welfare); half a day plus the offline replay. Phase 3: one or two pull requests, the contract models for about 40 event types being the bulk, 6 to 10 worker calls; one to two days. No entity boots, no GPU.
