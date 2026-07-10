## 1. Stand up the world (no KAINE code)

- [ ] 1.1 Install `dotnet 8` runtime on the laptop; unzip OpenSim 0.9.3.0; copy the
      `.example` configs; bind the HTTP listener + region to the laptop's Tailscale
      address (not `0.0.0.0`); first-run create region + estate owner
- [ ] 1.2 `create user` for a dedicated bot avatar (the entity's body)
- [ ] 1.3 `load oar` a CC0 starter world (e.g. Linda Kellie pack); confirm a normal
      Firestorm login from the GPU host over the tailnet renders it
- [ ] 1.4 Document the bring-up in `kaine/modules/mundus/MUNDUS.md` (operator runbook)

## 2. Forked Firestorm (the world adapter)

- [ ] 2.1 Build Firestorm-for-OpenSim (`-DOPENSIM:BOOL=ON`) — Docker build env;
      confirm it logs into the local grid and the bot avatar
- [ ] 2.2 **Verify** whether inbound nearby chat is reachable via an existing
      `LLEventPump` (Patch B only if not — see `firestorm-fork-notes.md`)
- [ ] 2.3 Patch A: add LEAP op `captureFrame` on `LLViewerWindowListener` wrapping
      `rawSnapshot`/`simpleSnapshot`, returning RGB bytes over a side channel
- [ ] 2.4 Confirm the stock `LLAgent` / `LLChatBar` / `LLNotifications` ops behave
      as probed (autopilot move, lookAt, sit/stand, sendChat, respond)
- [ ] 2.5 Embodiment settings at bind: ear/listener at **avatar position** (via
      `LLViewerControl.set`, key `VoiceEarLocation`) and **lock to mouselook**
      (first-person POV); verify whether a setting suffices before a small
      mouselook-reassert patch

## 3. Mundus LEAP shim (`tools/mundus-leap/`)

- [ ] 3.1 LEAP plugin (Python, `secondlife/leap`): bootstrap, `getAPIs`, `listen`
- [ ] 3.2 Translate LEAP events → the length-prefixed-MessagePack bridge frames
      Mundus consumes; translate action frames → LEAP ops
- [ ] 3.3 Hold sustained locomotion state between cognitive ticks (autopilot target
      / held synthetic keys)
- [ ] 3.4 Inbound-world auto-handler: default-deny script permission questions;
      auto-decline inventory offers, teleport lures, friendship/group invites via
      `LLNotifications.respond`; surface each as a `notice` frame

## 4. Mundus module (`kaine/modules/mundus/`)

- [ ] 4.1 `BaseModule` owning the bridge socket (sibling to Kosmos); two-layer gate
      `[mundus].enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED=1`
- [ ] 4.2 Decode bridge feeds → `mundus.*` bus events (proprio/scene/entity/chat/
      notice/visual.raw/action.result); redact frame buffers from event payloads
- [ ] 4.3 Consume `intent.avatar.*` from `volition.out`; per-effector gating
      (world-mutating / economy / touch / teleport default off)
- [ ] 4.4 Synthesize `audio.in.transcription` from `mundus.chat` so existing
      Audio_In consumers see in-world speech without touching STT
- [ ] 4.5 `[mundus]` table in `config/kaine.toml` (shipped all-off)

## 5. Shared seams (coordinate with paracosm-connector)

- [ ] 5.1 Generalize the Eidolon body field to a world-tagged `embodiment` union
      (`world: "paracosm" | "opensim"`); populate from `mundus.proprio`
- [ ] 5.2 Reuse `intent.avatar.{move,turn,say,sleep,wake}`; add OpenSim-native
      `teleport`, `sit_on`, `stand`, `touch`, `animate`, `gesture`
- [ ] 5.3 Thymos appraisal inputs for in-world social signals (chat heard, avatar
      arrival) via the paracosm-connector pattern

## 6. Perception locus (physical XOR virtual)

- [ ] 6.1 Add `perception_locus` (`physical`/`virtual`/`off`) + lock to
      `kaine/perception_state.py`; central mutual-exclusion arbiter
- [ ] 6.2 Topos + Audio_In read the locus and bind input accordingly; selecting
      `virtual` turns real camera/mic capture off in the same transition
- [ ] 6.3 Mundus forwards `intent.avatar.*` only when locus is `virtual`
- [ ] 6.4 Nexus WebUI: three-way locus selector + lock; publishes
      `perception.locus.changed`
- [ ] 6.5 Volition `intent.perception.switch {locus}`; gated by
      `[perception].allow_self_switch` (default false), inhibition, and min dwell;
      audited; updates Eidolon `embodiment`
- [ ] 6.6 `[perception]` table in `config/kaine.toml` (default `physical`, self-switch off)

## 7. In-world voice bridge (Tier-2 fast-follow — operator wants remote voice)

- [ ] 7.1 Stand up FreeSWITCH on the laptop bound to the tailnet; enable OpenSim
      `[FreeSwitchVoice]` + `[FreeswitchService]`; confirm two human Firestorm
      clients (one remote over Tailscale) can voice-chat
- [ ] 7.2 KAINE voice bridge: join the avatar's parcel voice channel as a SIP/RTP
      endpoint (PJSIP/baresip); map FreeswitchService channel → SIP session
- [ ] 7.3 Bridge Chatterbox TTS → channel uplink; channel downlink → Speaches STT →
      `audio.in.transcription` (gated by `perception_locus == virtual`)
- [ ] 7.4 Confirm operator (remote, over Tailscale) can speak to and hear the entity

## 8. Validation

- [ ] 6.1 Unit: frame decoder, intent→LEAP-op mapping, gated-effector drop, inbound
      auto-decline policy
- [ ] 6.2 Integration: `FakeLeapShim` fixture drives Mundus without a live viewer
- [ ] 6.3 Gated real test (`KAINE_HAS_OPENSIM=1`): connect to the live laptop grid
      over tailnet, read scene/proprio, issue a move, observe position change
- [ ] 6.4 `openspec validate opensim-connector --strict`
