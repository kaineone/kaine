# Tasks: remote-perception-bridge

## 1. Bridge core (`kaine/remote/bridge.py`)
- [ ] 1.1 `RemoteBridgeConfig.from_section`: enabled, host, port, token,
      video_max_fps, audio (sample_rate/vad settings), claim_senses.
- [ ] 1.2 WebSocket server (websockets.serve), path routing:
      /ingest/video, /ingest/audio, /speech, /transcript; token check at
      handshake when configured; connection counters + structured logs.
- [ ] 1.3 Video path: bytes → PIL.Image (in-memory) → topos.process_frame;
      latest-wins rate limiting; drops counted and logged, not silent.
- [ ] 1.4 Audio path: NetworkAudioStream (start/stop/close + callback) feeding
      a bridge-owned LiveMicrophone (sink=audition.process_audio,
      source_label="remote", desired_state_reader=client-connected).
- [ ] 1.5 Speech tap: TapPlayer implementing the Player protocol; broadcast
      WAV to /speech clients via bounded per-client queues (drop-oldest,
      counted); registered with Vox.add_playback_tap.
- [ ] 1.6 Transcript task: bus.read loop on lingua.external + audition.out
      from "now"; forward {role, text, ts, type} JSON.
- [ ] 1.7 claim_senses: write_desired_video/audio(False) while a producer is
      connected; restore prior on disconnect.

## 2. Module/cycle integration
- [ ] 2.1 `Vox.add_playback_tap(player)` — composes with the existing player;
      tap failures never break local playback.
- [ ] 2.2 `kaine/cycle/__main__.py`: build+start bridge after module init when
      enabled; stop in the shutdown path.
- [ ] 2.3 `config/kaine.toml`: `[remote_bridge]` shipped disabled, documented.

## 3. Tests (`tests/test_remote_bridge.py`)
- [ ] 3.1 Shipped config disabled; no-kill source guard (no kill()/terminate/
      subprocess in kaine/remote/).
- [ ] 3.2 Real localhost WS server: token reject/accept.
- [ ] 3.3 Video frame → stub topos got a PIL image; rate limit drops counted.
- [ ] 3.4 PCM utterance (RMS VAD) → stub audition got WAV + source_label.
- [ ] 3.5 Vox tap broadcast → client receives the WAV; local player also ran.
- [ ] 3.6 Transcript forwarding from fakeredis bus.
- [ ] 3.7 Zero-persistence scan during a full ingest/egress exchange.
- [ ] 3.8 claim_senses set/restore.

## 4. Docs
- [ ] 4.1 docs/configuration.md `[remote_bridge]` section.
- [ ] 4.2 docs/operations.md: remote operation over Tailscale (serve/cert
      note; the PWA client lives in the private kaine-remote repo).
