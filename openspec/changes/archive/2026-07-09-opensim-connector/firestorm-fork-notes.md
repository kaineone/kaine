# Firestorm fork notes (Mundus world adapter)

The fork is intentionally tiny. Stock LEAP already exposes the avatar control and
symbolic perception Mundus needs (see `design.md` §3.1); only vision (and possibly
inbound chat) require a patch. Everything here was located in a read-only probe of
`FirestormViewer/phoenix-firestorm@master` at `/tmp/phoenix-firestorm`.

## Build configuration

- Target: `ReleaseFS_open` (no KDU/FMOD) with **OpenSim ON**.
  - `autobuild configure -A 64 -c ReleaseFS_open`, ensuring `-DOPENSIM:BOOL=ON`.
  - `scripts/configure_firestorm.sh:39` defaults `WANTS_OPENSIM=$TRUE` and emits
    the flag at `:472`.
  - The flag selects `fsgridhandler.cpp` + `fsslurl.cpp` over the stock
    `llviewernetwork.cpp` + `llslurl.cpp` (`indra/newview/CMakeLists.txt:930-940`).
  - Note: the *documented* `ReleaseFS_open` blurb says "no OpenSim" — confirm the
    OpenSim flag is actually ON for our build output.
  - `OPENSIM` is forced OFF when Havok is used (`indra/cmake/Variables.cmake:200-212`);
    we are not using Havok (`HAVOK_TPV`), so this is fine.
- Build env: Ubuntu 22.04 x86_64, `autobuild`. Hours-long. A community Docker build
  environment exists (`uriesk/firestorm-dockerbuild`, `Teriks/debian_docker_firestorm_build`).
- **Do not** attempt to build during this design phase. Building is task 2.1.

## Point the viewer at the local grid (no patch)

- `LLGridManager::addGrid(const std::string& loginuri)` — `indra/newview/fsgridhandler.h:129`,
  impl `fsgridhandler.cpp:496`. Queries the loginuri's `get_grid_info` XML-RPC.
- Grids persist in `grids.xml` (`fsgridhandler.cpp:180`); login URI under
  `GRID_LOGIN_URI_VALUE` (`:359-361`). For the split topology the URI is the
  **laptop's Tailscale address**, e.g. `http://<laptop>.<tailnet>.ts.net:9000/`.

## Patch A — in-memory frame for vision (REQUIRED for vision v2)

Stock LEAP's only snapshot op writes a **file** (`LLViewerWindow.saveSnapshot`,
`indra/newview/llviewerwindowlistener.cpp:56,103`). Add an op that returns pixels.

- New op `captureFrame {w, h}` on `LLViewerWindowListener`
  (`indra/newview/llviewerwindowlistener.cpp`), calling:
  ```cpp
  // decl indra/newview/llviewerwindow.h:373 ; def indra/newview/llviewerwindow.cpp:6124
  bool LLViewerWindow::rawSnapshot(LLImageRaw* raw, S32 w, S32 h, /* … */);
  // RGB, 3 bytes/px (alloc *3 at :6135; glReadPixels at :6345,6356,6390)
  // lighter offscreen alternative: simpleSnapshot(LLImageRaw*, w, h, passes) — :377
  ```
- Reachable via the global `gViewerWindow` (the listener already holds
  `mViewerWindow`).
- **Return path:** LLSD binary is impractical for a full frame. Use a **side
  channel** — shared memory or a dedicated local socket the shim reads — and have
  the LEAP reply carry only metadata (`{w, h, encoding:"rgb8", seq}`). Decide
  shared-mem vs socket at implementation (`design.md` §13.2).

## Patch B — inbound nearby chat pump (MAYBE — verify first)

The probe found outbound `LLChatBar.sendChat` but did **not** confirm an
`LLEventPump` carrying *inbound* nearby chat that a LEAP plugin can `listen` on.

- **Verify** whether nearby chat is already published to a listenable pump
  (check `LLNearbyChat` / `LLIMProcessing::processNewMessage`
  `indra/newview/llimprocessing.cpp:703` and any existing event-pump posts).
- **Only if absent:** add a small patch publishing inbound nearby chat (and,
  optionally, the inbound notification stream) to a named `LLEventPump`. Keep the
  payload to sender name + text + channel; no persistence.

## Viewer embodiment settings (perceive as the avatar, first-person)

KAINE's viewer must perceive the world *as its avatar*, not as a free-floating
camera. Two settings, applied by the shim at bind:

- **Listener/ear at avatar position, not camera.** Most viewers default spatial
  audio to the *camera* position; set it to the **avatar** position via
  `LLViewerControl.set` (the LEAP op found at `indra/newview/llviewercontrollistener.cpp:62`).
  The relevant `gSavedSettings` key is the ear-location setting (`VoiceEarLocation`,
  value = avatar; confirm the exact key + enum in `settings.xml` at build). This
  ensures the entity hears from where its body is, and matches the vision POV.
- **Locked to mouselook (first-person POV).** The vision feed (Patch A
  `captureFrame`) captures the rendered view, so the camera must be the avatar's
  first-person mouselook view, not third-person orbit. Enter mouselook at bind
  (`gAgentCamera.changeCameraToMouselook()` — reachable via a small op or `LLWindow`
  synthetic input) and **keep it there**: a small patch to re-assert mouselook and
  suppress auto-exit (sit/stand and some actions drop out of mouselook) is the
  robust route. With no human at this viewer, nothing *intentionally* leaves
  mouselook, but action-driven exits must be re-asserted. Track as a small fork
  item (verify whether a setting alone suffices before patching).

## No patch needed — inbound-world safety uses stock LEAP

Auto-declining offers/dialogs uses the existing `LLNotifications` LEAP API
(`indra/llui/llnotificationslistener.cpp:41-69`: `requestAdd`/`respond`/`cancel`/
`ignore`). The shim listens for the notification channel and `respond`s with the
decline option. Handlers identified for reference:

- Script permission question: `script_question_cb` `indra/newview/llviewermessage.cpp:7229` (reg `:7349`) — **default-deny**
- Inventory offer: `LLOfferInfo` `indra/newview/llimprocessing.cpp:1555-1625` — **discard**
- Teleport lure: `lure_callback` `indra/newview/llviewermessage.cpp:2364` — **decline**
- Friendship offer: `friendship_offer_callback` `indra/newview/llviewermessage.cpp:315` — **decline**
- Group invite: `join_group_response` `indra/newview/llviewermessage.cpp:903` — **decline**

## Licensing

- Firestorm: **LGPL-2.1**. OpenSim: **BSD-3**. `secondlife/leap`: permissive.
- On a **private OpenSim grid**, Linden Lab's Third-Party-Viewer policy and the
  Second Life trademark do not apply (they govern connecting to LL's grid only), so
  a bot-driven forked viewer is fine for private use. We do **not** connect to LL's
  Second Life grid.
- For the eventual public release / CAL review: distributing an LGPL-derived fork
  carries LGPL obligations (offer corresponding source, permit relinking). Keep the
  fork's diff small and separately published so the obligation is clean.
