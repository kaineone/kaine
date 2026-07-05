# Remote perception bridge (Tailscale operator clients)

## Why

The operator must be able to run and supervise the entity while away from the
GPU host: stream a phone/laptop camera into the entity's vision, a microphone
into its hearing, hear its generated speech, and read the conversation
transcript — over the operator's Tailscale tailnet. The perception modules
live inside the cycle process (`Topos.process_frame`, `Audition.process_audio`,
Vox's `Player`), so remote A/V needs an in-process ingress/egress bridge; no
external client can reach those seams directly.

The injection seams already exist and were audit-confirmed clean:
`process_frame(PIL.Image)`, `process_audio(wav_bytes, sr, source_label=...)`,
`LiveMicrophone(stream_factory=...)` (server-side VAD/utterance assembly), the
`Player` protocol, and the `lingua.external` / `audition.out` bus streams.
The bridge composes them; it does not rewrite any module.

## What changes

- New cycle-layer component (like Spot, not a registry module):
  `kaine/remote/bridge.py` — a WebSocket server (`websockets`, already shipped
  via uvicorn[standard]) started by `kaine.cycle.__main__` when
  `[remote_bridge].enabled` is true. Ships **disabled**; binds `127.0.0.1` by
  default (the operator points it at the tailnet interface; Tailscale ACL is
  the boundary, with an optional shared-secret token as cheap hardening).
- Channels (path-routed on one port):
  - `/ingest/video` — binary JPEG/PNG frames → decoded to `PIL.Image`
    **in memory** → `Topos.process_frame()`. Latest-wins; rate-limited.
  - `/ingest/audio` — binary int16 PCM frames → a bridge-owned
    `LiveMicrophone` fed by a network `stream_factory`, reusing the existing
    VAD/utterance assembly → `Audition.process_audio(...,
    source_label="remote")`. Raw PCM lives only in the existing bounded queue.
  - `/speech` — server→client: synthesized WAV tapped from Vox via a new
    public `Vox.add_playback_tap(player)` (composes; local playback unchanged).
  - `/transcript` — server→client JSON: entity utterances (`lingua.external`)
    and heard transcriptions (`audition.out`), for the overlay UI.
- While a remote video/audio producer is connected the bridge marks the
  corresponding physical sense not-desired via the existing `perception_state`
  API (remote and physical sensors must not fight), restoring the prior
  desired state on disconnect (`claim_senses`, default true).
- Zero-raw-sense-data persistence holds: frames and audio are decoded in
  memory and released; the bridge writes nothing to disk. No kill/exec
  primitives; read-and-inject only.

The client apps (PWA, playlist feeder) live in the private `kaine-remote`
repo and are out of scope here — this change is only the entity-side seam
they connect to.

## Impact

- New spec capability: `remote-bridge`.
- Affected code: new `kaine/remote/` package; `kaine/cycle/__main__.py`
  (start/stop hook); `kaine/modules/vox/module.py` (`add_playback_tap`);
  `config/kaine.toml` (new `[remote_bridge]`, shipped disabled);
  docs.
- No new dependencies (`websockets` ships with uvicorn[standard]; Pillow with
  the vision extra the video path requires anyway).
- Shipped config stays guard-consistent: `enabled = false`, nothing runs.
