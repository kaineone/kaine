# paracosm-connector tasks

Implementation tasks for the Kosmos module on the KAINE side. Paracosm-side
asks are tracked in `paracosm-counterpart-asks.md` and should be opened as
issues against `kaineone/Paracosm`.

This change is design-only until a branch picks it up; tasks below are the
shape of the work, not yet in progress.

## 1. Module skeleton

- [ ] 1.1 `kaine/modules/kosmos/__init__.py` — `KosmosModule`, `KosmosConfig` exports
- [ ] 1.2 `kaine/modules/kosmos/module.py` — `KosmosModule(BaseModule)` skeleton matching the §6.2 sketch
- [ ] 1.3 `kaine/modules/kosmos/config.py` — `KosmosConfig` dataclass with every key from §8
- [ ] 1.4 Two-layer gate: `OPERATOR_APPROVED_ENV = "KAINE_KOSMOS_OPERATOR_APPROVED"` + `operator_approved()` helper, matching `kaine/modules/hypnos/voice_alignment.py` shape
- [ ] 1.5 Wire into `kaine/boot.py` with all the new config keys
- [ ] 1.6 Add `kosmos = false` to `config/kaine.toml` `[modules]` table (shipped off)
- [ ] 1.7 Add the full `[kosmos]` table to `config/kaine.toml` with shipped-off defaults

## 2. Bridge TCP client

- [ ] 2.1 `kaine/modules/kosmos/bridge.py` — `BridgeClient` with `asyncio.open_connection`
- [ ] 2.2 Length-prefixed MessagePack reader (`read_exactly(4) → u32 BE → read_exactly(length) → msgpack.unpackb`)
- [ ] 2.3 Reconnect loop honoring `reconnect_backoff_s` schedule, never raises
- [ ] 2.4 `connect_timeout_s` enforcement
- [ ] 2.5 `max_frame_bytes` guard (matches Paracosm's 8 MiB cap)
- [ ] 2.6 Graceful close on shutdown

## 3. Frame decoder

- [ ] 3.1 `_handle_frame` dispatcher on `frame["kind"]`
- [ ] 3.2 `_on_proprio` — publish `kosmos.proprio`, salience rules from §7.1
- [ ] 3.3 `_on_temporal` — publish `kosmos.temporal`, salience rules
- [ ] 3.4 `_on_intero` — publish `kosmos.intero.bridge`
- [ ] 3.5 `_on_visual` — drop stub frames by default per `consume_stub_visual`; redact bytes (zero-persistence)
- [ ] 3.6 `_on_audio` — drop by default (wind synth ≠ STT input); redact bytes
- [ ] 3.7 `_on_event` (future feed) — publish `kosmos.event`; synthesize `audio.in.transcription` for Speech-from-agent
- [ ] 3.8 `_on_entity` (future feed) — publish `kosmos.entity`
- [ ] 3.9 `_on_shutdown` — drive the §6.3 mortality flow
- [ ] 3.10 Unknown kind → debug-log and continue (forward-compatible)

## 4. Intent consumer & action sender

- [ ] 4.1 `_consume_intents` task — `volition.out` reader with `block_ms=100`
- [ ] 4.2 Effector allow-list per `expose_*` config flags
- [ ] 4.3 `_intent_to_frame(family, payload)` translator (one branch per intent type)
- [ ] 4.4 `_write_frame` — length-prefixed MessagePack send
- [ ] 4.5 `kosmos.action.sent` + `kosmos.action.result` audit events
- [ ] 4.6 Action audit log to `state/kosmos/audit.jsonl` (no payload bytes for any data field; only summaries)

## 5. Volition extension

- [ ] 5.1 `kaine/workspace/volition.py` — add `AVATAR_*` constants + `INTENT_TYPES` entries per §7.2
- [ ] 5.2 Confirm executive inhibition gates the new intents (no code change expected; verify via test)
- [ ] 5.3 Confirm Lingua + Praxis ignore `intent.avatar.*` (prefix mismatch; verify via test)

## 6. Eidolon body extension

- [ ] 6.1 `kaine/modules/eidolon/document.py` — `ParacosmBody` dataclass + optional `paracosm_body` field
- [ ] 6.2 `kaine/modules/eidolon/module.py` — subscribe to `kosmos.proprio`, update body field
- [ ] 6.3 Persist `paracosm_body` in `state/eidolon/self_model.json` (summary scalars only — no raw sense data)
- [ ] 6.4 Emit `eidolon.body.dying` when `dying=true` is first seen, salience 0.9

## 7. Thymos appraisal extension

- [ ] 7.1 `kaine/modules/thymos/paracosm_appraisal.py` (new file) — appraisal rules from §7.4
- [ ] 7.2 Wire as an optional appraisal source; gracefully no-op when Kosmos disabled
- [ ] 7.3 Tests covering each rule (dying → arousal spike, eclipse → awe, pleasure → valence gain, etc.)

## 8. Mortality / final state

- [ ] 8.1 `kaine/modules/kosmos/final_state.py` — `collect()` helper that gathers Eidolon snapshot + top-K Mnemos memories + identity header
- [ ] 8.2 Schema: `{schema: "kaine.kosmos.v1", entity_id, kaine_version, eidolon: {...}, memories: [...], world_time, position}`
- [ ] 8.3 MessagePack encode, truncate to `final_state_max_bytes`
- [ ] 8.4 Send `{kind: "final_state", encoding: "msgpack", data: <bytes>}` over bridge before close
- [ ] 8.5 `shutdown_grace_s` wait so other modules can react to `kosmos.shutdown`

## 9. Operator doc + ARCHITECTURE / SECURITY updates

- [ ] 9.1 `kaine/modules/kosmos/KOSMOS.md` — operator guide (two-layer gate, effector gating, mortality flow, rollback)
- [ ] 9.2 `ARCHITECTURE.md` — new Kosmos row in the module table
- [ ] 9.3 `SETUP.md` — Paracosm prereqs (world server + agent-client + bridge port), env var, opt-in steps
- [ ] 9.4 `SECURITY.md` — new §10 on Kosmos: two-layer gate, default-off effectors, mortality preparation, zero-persistence on visual/audio bytes
- [ ] 9.5 `FIRST_BOOT.md` — note Kosmos defaults off; document opt-in ceremony
- [ ] 9.6 `DEPENDENCIES.md` — `msgpack` (already a likely dep; verify) and any new test fixtures

## 10. Tests

- [ ] 10.1 `tests/test_kosmos_two_layer_gate.py` — config-off + env-off + both-on matrix
- [ ] 10.2 `tests/test_kosmos_bridge_decoder.py` — each frame kind round-trips through `_on_*` correctly
- [ ] 10.3 `tests/test_kosmos_intent_dispatch.py` — each intent translates to the right action frame; gated effectors drop
- [ ] 10.4 `tests/test_kosmos_reconnect.py` — failure → backoff → recovery
- [ ] 10.5 `tests/test_kosmos_eidolon_body.py` — proprio frame updates `paracosm_body`
- [ ] 10.6 `tests/test_kosmos_thymos_appraisal.py` — each appraisal rule fires
- [ ] 10.7 `tests/test_kosmos_shutdown_final_state.py` — shutdown → final_state within grace
- [ ] 10.8 `tests/test_kosmos_zero_persistence.py` — `kosmos.visual.raw` / `kosmos.audio.raw` payloads carry NO byte data; audit log carries no payload bytes
- [ ] 10.9 `tests/test_kosmos_real_paracosm.py` (gated on `KAINE_HAS_PARACOSM=1`) — end-to-end against a live bridge

## 11. Fake bridge fixture

- [ ] 11.1 `tests/fixtures/fake_paracosm_bridge.py` — in-process TCP server speaking the bridge protocol
- [ ] 11.2 Helpers to push specific frame kinds and assert what came back
- [ ] 11.3 Used by 10.2 / 10.3 / 10.4 / 10.7

## 12. Spec deltas

- [ ] 12.1 `specs/embodiment/kosmos.md` — capability spec for the new module
- [ ] 12.2 Cross-reference from `specs/bus/schema.md` if it lists known event prefixes

## 13. Cross-project asks (Paracosm)

Tracked in `paracosm-counterpart-asks.md`. Each should be opened as a
GitHub issue against `kaineone/Paracosm` when this change starts:

- [ ] 13.1 P0: Real visual feed (render-to-texture)
- [ ] 13.2 P0: Widen `decode_action_frame`
- [ ] 13.3 P0: Inventory + pleasure in proprio
- [ ] 13.4 P0: Forward `ActionResult` to bridge (added 2026-05-31 from live test)
- [ ] 13.5 P0: Forward `DeathSequence` phase to bridge (added 2026-05-31 from live test)
- [ ] 13.6 P1: `event` feed forwarding
- [ ] 13.7 P1: `entity_update` feed forwarding
- [ ] 13.8 P1: `t_world` in proprio
- [ ] 13.9 P2: `Adopt` action via bridge
- [ ] 13.10 P2: `world_facts` summary feed
- [ ] 13.11 ~~P3: Headless agent-client mode~~ — `--headless` flag exists
       (build `paracosm_26.05.01`) but **crashes on AssetServer not
       registered**: separate ask = "fix --headless crash"
- [ ] 13.12 P3: `final_state` schema convention doc
- [ ] 13.13 P0: Fix `--headless` AssetServer panic (see 13.11 note)

## 14. Operator runbook checklist (post-implementation)

Validate the full embodiment flow end-to-end:

- [ ] 14.1 Launch Paracosm world server
- [ ] 14.2 Launch Paracosm agent-client, confirm agent_id assigned
- [ ] 14.3 Edit `[kosmos].enabled = true` in local kaine.toml (do NOT commit per `[First-boot module toggles]`)
- [ ] 14.4 Set `KAINE_KOSMOS_OPERATOR_APPROVED=1`
- [ ] 14.5 Launch KAINE (`KAINE_CYCLE_OPERATOR_PRESENT=1`)
- [ ] 14.6 Observe first `kosmos.proprio` event in Nexus diagnostics
- [ ] 14.7 Observe `paracosm_body` field populated in Eidolon self-model
- [ ] 14.8 Operator manually publishes an `intent.avatar.move` and observes position change in VR observer
- [ ] 14.9 Trigger a controlled death (lifespan expiry or operator-issued teleport into fire), observe `kosmos.shutdown` → `final_state` flow
- [ ] 14.10 Verify memory diamond placement carries the encoded state (size matches what we sent)
