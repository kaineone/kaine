# Tasks: remote-perception-bridge

> Reconciliation: the bridge shipped to `main` ahead of this checklist. Each
> box is ticked with a `file:symbol` evidence pointer; all boxes are backed by
> `tests/test_remote_bridge.py` (29 passed) and `lint-imports` (5 contracts
> kept). No greenfield code was required.

## 1. Bridge core (`kaine/remote/bridge.py`)
- [x] 1.1 `RemoteBridgeConfig.from_section`: enabled, host, port, token,
      video_max_fps, audio (sample_rate/vad settings), claim_senses.
      — `kaine/remote/bridge.py:RemoteBridgeConfig.from_section` (also threads
      speech_queue_size, allowed_origins, max_message_bytes, ssl_*). Tests:
      `test_config_threads_new_security_fields`,
      `test_parse_origins_maps_null_and_empty_to_none`.
- [x] 1.2 WebSocket server (websockets.serve), path routing:
      /ingest/video, /ingest/audio, /speech, /transcript; token check at
      handshake when configured; connection counters + structured logs.
      — `kaine/remote/bridge.py:RemoteBridge.start` / `RemoteBridge._handle`
      (+ `_serve_affect` extends the read-only channel set); token via
      `_authorized`. Tests: `test_token_rejects_and_accepts`,
      `test_bearer_header_path_still_works`,
      `test_token_via_subprotocol_authenticates`.
- [x] 1.3 Video path: bytes → PIL.Image (in-memory) → topos.process_frame;
      latest-wins rate limiting; drops counted and logged, not silent.
      — `kaine/remote/bridge.py:RemoteBridge._ingest_frame` (frames_in /
      frames_dropped counters; MAX_FRAME_PIXELS bomb guard). Tests:
      `test_video_frame_reaches_topos_as_pil_image`,
      `test_video_rate_limit_drops_excess_frames`,
      `test_oversized_image_is_dropped_without_reaching_topos`.
- [x] 1.4 NetworkAudioStream (start/stop/close + callback) feeding
      a bridge-owned LiveMicrophone (sink=audition.process_audio,
      source_label="remote", desired_state_reader=client-connected).
      — `kaine/remote/bridge.py:NetworkAudioStream` +
      `RemoteBridge._start_network_mic`. Tests:
      `test_pcm_utterance_reaches_audition_with_remote_label`,
      `test_network_audio_stream_rechunks_exactly`,
      `test_audio_buffer_cap_trims_oldest_and_stays_bounded`.
- [x] 1.5 Speech tap: TapPlayer implementing the Player protocol; broadcast
      WAV to /speech clients via bounded per-client queues (drop-oldest,
      counted); registered with Vox.add_playback_tap.
      — `kaine/remote/bridge.py:SpeechTapPlayer` (registered in
      `RemoteBridge.start`). Tests: `test_speech_tap_broadcasts_to_client`,
      `test_vox_add_playback_tap_composes`,
      `test_tee_player_mirrors_and_survives_tap_failure`.
- [x] 1.6 Transcript task: bus.read loop on lingua.external + audition.out
      from "now"; forward {role, text, ts, type} JSON.
      — `kaine/remote/bridge.py:RemoteBridge._transcript_loop` /
      `_transcript_line`. Test: `test_transcript_forwards_entity_and_heard_lines`.
- [x] 1.7 claim_senses: write_desired_video/audio(False) while a producer is
      connected; restore prior on disconnect.
      — `kaine/remote/bridge.py:_SenseClaim` (acquire/release, per-sense
      refcount). Test: `test_claim_senses_sets_and_restores_physical_video`.

## 2. Module/cycle integration
- [x] 2.1 `Vox.add_playback_tap(player)` — composes with the existing player;
      tap failures never break local playback.
      — `kaine/modules/vox/module.py:Vox.add_playback_tap` wrapping
      `kaine/modules/vox/playback.py:TeePlayer`. Test:
      `test_tee_player_mirrors_and_survives_tap_failure`.
- [x] 2.2 `kaine/cycle/__main__.py`: build+start bridge after module init when
      enabled; stop in the shutdown path.
      — `kaine/cycle/__main__.py` (build_remote_bridge + start ~L905-916;
      stop in the shutdown path ~L1087-1091).
- [x] 2.3 `config/kaine.toml`: `[remote_bridge]` shipped disabled, documented.
      — `config/kaine.toml` `[remote_bridge]` (`enabled = false`,
      `host = "127.0.0.1"`). Test: `test_shipped_config_disables_bridge`.

## 3. Tests (`tests/test_remote_bridge.py`)
- [x] 3.1 Shipped config disabled; no-kill source guard (no kill()/terminate/
      subprocess in kaine/remote/).
      — `test_shipped_config_disables_bridge`,
      `test_bridge_source_has_no_kill_or_exec_primitives`.
- [x] 3.2 Real localhost WS server: token reject/accept.
      — `test_token_rejects_and_accepts` (+ subprotocol/bearer/constant-time
      variants).
- [x] 3.3 Video frame → stub topos got a PIL image; rate limit drops counted.
      — `test_video_frame_reaches_topos_as_pil_image`,
      `test_video_rate_limit_drops_excess_frames`.
- [x] 3.4 PCM utterance (RMS VAD) → stub audition got WAV + source_label.
      — `test_pcm_utterance_reaches_audition_with_remote_label`.
- [x] 3.5 Vox tap broadcast → client receives the WAV; local player also ran.
      — `test_speech_tap_broadcasts_to_client`,
      `test_vox_add_playback_tap_composes`.
- [x] 3.6 Transcript forwarding from fakeredis bus.
      — `test_transcript_forwards_entity_and_heard_lines`.
- [x] 3.7 Zero-persistence scan during a full ingest/egress exchange.
      — `test_full_exchange_writes_nothing_to_disk`.
- [x] 3.8 claim_senses set/restore.
      — `test_claim_senses_sets_and_restores_physical_video`.

## 4. Docs
- [x] 4.1 docs/configuration.md `[remote_bridge]` section.
      — `docs/configuration.md` `## [remote_bridge]`.
- [x] 4.2 docs/operations.md: remote operation over Tailscale (serve/cert
      note; the PWA client lives in the private Fieldtrip repo).
      — `docs/operations.md` remote perception bridge section (tailnet bind,
      token, cert note, zero-persistence).
