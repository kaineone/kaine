# Mundus LEAP shim

Bridges a Firestorm/OpenSim viewer to a KAINE entity. The viewer launches
`mundus_leap.py` as a LEAP plugin (`--leap`), and the shim drives the avatar and
reads the world over the viewer's LEAP event APIs.

- **Control + symbolic perception:** stock LEAP — `LLAgent` (autopilot move,
  lookAt, sit/stand/touch, getPosition, getNearbyAvatarsList/ObjectsList) and
  `LLChatBar.sendChat`.
- **Vision:** `LLViewerWindow.captureFrame` — a new op added by our Firestorm
  fork (`indra/newview/llviewerwindowlistener.cpp`) that renders the avatar's
  first-person view to RGB and returns the bytes over LEAP. Requires the forked
  viewer; stock Firestorm only has the file-writing `saveSnapshot`.

## Run (live test)

Needs the **Kaine One** account password and a desktop session:

```bash
MUNDUS_BOT_PASSWORD='…' tools/mundus-leap/run-mundus-viewer.sh
```

This launches the forked viewer (`/tmp/phoenix-firestorm/build-linux-x86_64/newview/packaged`)
logged in as Kaine One, with the shim attached. Watch:

- `state/mundus/shim.log` — every step the shim runs
- `state/mundus/frame_0.ppm` — the captured first-person frame (proves vision)

## Modes (`MUNDUS_MODE`)

- `demo` (default): scripted proof — discover APIs, read position + nearby
  entities, say a line in local chat, capture a frame, autopilot a few metres.
- `bridge` (v2, TODO): relay frames/intents to the KAINE Mundus `BaseModule`
  over a length-prefixed-MessagePack TCP bridge, so the live cognitive loop
  perceives and acts through the avatar.

## Deps

`leap` + `llsd` (in the repo `.venv`). The shim has **no KAINE imports** — it's a
separate process, decoupled from the cognitive loop.
