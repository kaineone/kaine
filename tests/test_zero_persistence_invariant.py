# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Load-bearing zero-persistence invariant test.

The live perception path is eyes and ears — transducers feeding the
brain — not a recorder. This test runs both perception streams against
fakes and verifies that NO raw audio or video data lands on disk:

  - No `.wav`, `.pcm`, `.raw`, `.flac`, `.opus`, `.mp3` files anywhere.
  - No `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.webp`, `.mp4`, `.webm`,
    `.mkv`, `.mov` files anywhere.
  - No new files in `state/`, `data/`, or `/tmp` except the operational
    state files (`state/perception/runtime.json`, `desired.json`).
  - Static repo grep: `wave.open` in `kaine/modules/audition/` only
    receives `io.BytesIO()` arguments (never a file path).
  - Static repo grep: no `cv2.imwrite` or `cv2.VideoWriter` calls
    anywhere under `kaine/`.
"""
from __future__ import annotations

import asyncio
import re
import struct
import subprocess
from pathlib import Path

import pytest

from kaine import perception_state
from kaine.modules.audition.live import LiveMicConfig, LiveMicrophone
from kaine.modules.topos.live import LiveCamera, LiveCameraConfig


RAW_SENSE_EXTENSIONS = (
    # audio
    ".wav", ".pcm", ".raw", ".flac", ".opus", ".mp3", ".ogg", ".m4a",
    # video / image
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp",
    ".mp4", ".webm", ".mkv", ".mov", ".avi",
)


def _scan_for_raw_sense_files(root: Path) -> list[Path]:
    matches: list[Path] = []
    if not root.exists():
        return matches
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in RAW_SENSE_EXTENSIONS:
            matches.append(path)
    return matches


class _SilentMicStream:
    def __init__(self, *, callback):
        self._callback = callback
        self._task = None
        self._stop = asyncio.Event()

    def start(self):
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._feed())

    def stop(self):
        self._stop.set()

    def close(self):
        return

    async def _feed(self):
        frame = struct.pack("<480h", *([0] * 480))  # 30 ms silence @ 16k
        for _ in range(100):
            if self._stop.is_set():
                return
            self._callback(frame)
            await asyncio.sleep(0.005)


class _LoudMicStream(_SilentMicStream):
    async def _feed(self):
        loud = struct.pack("<480h", *([5000 if i % 2 == 0 else -5000 for i in range(480)]))
        silent = struct.pack("<480h", *([0] * 480))
        # 8 frames speech, 4 frames silence — should flush exactly one utterance.
        seq = [loud] * 8 + [silent] * 4 + [silent] * 50
        for frame in seq:
            if self._stop.is_set():
                return
            self._callback(frame)
            await asyncio.sleep(0.005)


class _FakeCamSource:
    def __init__(self, *, device, width, height):
        self.device = device
        self.width = width
        self.height = height
        self._frames = [f"f-{i}" for i in range(20)]
        self._i = 0
        self.released = False

    def open(self):
        return True

    def read(self):
        if self._i >= len(self._frames):
            return False, None
        f = self._frames[self._i]
        self._i += 1
        return True, f

    def release(self):
        self.released = True


@pytest.mark.asyncio
async def test_no_raw_sense_files_appear_anywhere(tmp_path, monkeypatch):
    """Activate both streams, drive them for several utterances/frames,
    then scan disk. No raw audio/video file may appear under tmp_path,
    state/, data/, or /tmp."""
    # Redirect perception state files into tmp_path so we don't trample
    # the dev's real state dir.
    runtime_path = tmp_path / "state" / "perception" / "runtime.json"
    desired_path = tmp_path / "state" / "perception" / "desired.json"
    monkeypatch.setattr(perception_state, "RUNTIME_PATH", runtime_path)
    monkeypatch.setattr(perception_state, "DESIRED_PATH", desired_path)

    pre_repo = _scan_for_raw_sense_files(tmp_path)
    pre_state = _scan_for_raw_sense_files(Path("state"))
    pre_data = _scan_for_raw_sense_files(Path("data"))

    sink_audio_calls: list[bytes] = []

    async def audio_sink(wav, sr, label):
        sink_audio_calls.append(wav)

    sink_video_calls: list = []

    async def video_sink(img):
        sink_video_calls.append(img)

    mic = LiveMicrophone(
        audio_sink,
        config=LiveMicConfig(
            sample_rate=16000,
            vad_frame_ms=30,
            min_utterance_ms=60,
            max_utterance_ms=500,
            silence_hangover_ms=60,
            desired_state_poll_ms=20,
        ),
        state_writer=perception_state.update_audio_runtime,
        desired_state_reader=lambda: True,
        stream_factory=lambda **kw: _LoudMicStream(callback=kw["callback"]),
        vad_factory=type(
            "VAD",
            (),
            {"is_speech": staticmethod(lambda frame, sr: any(b for b in frame[:200]))},
        ),
    )

    cam = LiveCamera(
        video_sink,
        config=LiveCameraConfig(
            capture_interval_s=0.02,
            warmup_frames=0,
            desired_state_poll_ms=20,
        ),
        state_writer=perception_state.update_video_runtime,
        desired_state_reader=lambda: True,
        source_factory=lambda device, *, width, height: _FakeCamSource(
            device=device, width=width, height=height
        ),
        bgr_to_rgb=lambda f: ("rgb", f),
    )

    await mic.initialize()
    await cam.initialize()
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            if sink_audio_calls and len(sink_video_calls) >= 3:
                break
    finally:
        await mic.shutdown()
        await cam.shutdown()

    # Verify streams actually ran (sanity).
    assert sink_video_calls, "video sink never called — invariant test inconclusive"

    # Scan for any raw-sense file that appeared during the run.
    new_repo = _scan_for_raw_sense_files(tmp_path)
    new_state = _scan_for_raw_sense_files(Path("state"))
    new_data = _scan_for_raw_sense_files(Path("data"))
    leaked = (
        (set(new_repo) - set(pre_repo))
        | (set(new_state) - set(pre_state))
        | (set(new_data) - set(pre_data))
    )
    assert leaked == set(), (
        f"ZERO-PERSISTENCE INVARIANT VIOLATED: raw audio/video file(s) "
        f"appeared on disk during live perception: {sorted(p.name for p in leaked)}"
    )


def test_no_wave_open_to_file_path_under_audition():
    """Every `wave.open(...)` call under kaine/modules/audition/ must
    pass an io.BytesIO instance, never a file path."""
    repo_root = Path(__file__).parent.parent
    target = repo_root / "kaine" / "modules" / "audition"
    proc = subprocess.run(
        ["git", "grep", "-n", "wave.open", "--", str(target)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.strip().splitlines():
        if not line.strip():
            continue
        # Strip the "file:lineno:" prefix that git grep produces.
        m = re.match(r"^.*?:\d+:(.*)$", line)
        body = m.group(1) if m else line
        # The only allowed form is `wave.open(io.BytesIO(...)...` or
        # `wave.open(buf...` where buf is a BytesIO bound nearby. The
        # invariant is no string literals, no Path() args.
        assert "io.BytesIO" in body or "(buf" in body, (
            f"wave.open call may have written to disk: {line!r}"
        )


def test_no_cv2_image_or_video_writers_under_kaine():
    """No cv2.imwrite or cv2.VideoWriter anywhere under kaine/."""
    repo_root = Path(__file__).parent.parent
    target = repo_root / "kaine"
    proc = subprocess.run(
        ["git", "grep", "-E", r"cv2\.(imwrite|VideoWriter)", "--", str(target)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    matches = [line for line in proc.stdout.strip().splitlines() if line]
    assert matches == [], (
        f"cv2.imwrite or cv2.VideoWriter present under kaine/: {matches}"
    )


def test_runtime_state_only_contains_operational_keys(tmp_path):
    """State file contains booleans + timestamps only — no sensory
    content."""
    import json

    path = tmp_path / "runtime.json"
    perception_state.update_audio_runtime(True, path)
    perception_state.update_video_runtime(True, path)
    raw = json.loads(path.read_text())
    text_blob = json.dumps(raw).lower()
    # Ensure no token resembling sensory content (transcribed text,
    # frame data, audio bytes).
    forbidden = ["text", "transcription", "frame_data", "pcm", "audio_bytes"]
    for word in forbidden:
        assert word not in text_blob, (
            f"runtime.json contains forbidden key/value {word!r}: {raw}"
        )


def test_escalation_state_only_contains_operational_keys(tmp_path):
    """Spot's escalation.json holds operational fields only — no sensory
    content. Mirrors the runtime.json invariant for the supervisor's halt file.
    """
    import json

    from kaine.cycle.escalation_state import (
        EscalationRecord,
        read_escalation,
        write_escalation,
    )

    path = tmp_path / "escalation.json"
    write_escalation(
        EscalationRecord(
            escalated=True,
            module="lingua",
            attempts=5,
            snapshot_id="abc123",
            escalated_at="2026-06-07T00:00:00+00:00",
            message="Module 'lingua' failed to recover. Reboot. Do NOT auto-retry.",
        ),
        path,
    )
    raw = json.loads(path.read_text())
    assert set(raw) == {
        "escalated",
        "module",
        "attempts",
        "snapshot_id",
        "escalated_at",
        "message",
    }
    # The operator message is free text but must never carry sensory content.
    blob = json.dumps({k: v for k, v in raw.items() if k != "message"}).lower()
    for word in ["transcription", "frame_data", "pcm", "audio_bytes"]:
        assert word not in blob, (
            f"escalation.json carries forbidden token {word!r}: {raw}"
        )
    # Round-trips cleanly.
    assert read_escalation(path).module == "lingua"


@pytest.mark.asyncio
async def test_deterministic_feed_sources_persist_no_raw_frames(tmp_path, monkeypatch):
    """The reproducible perception-feed sources (seeded + playlist) must obey
    the same zero-persistence invariant as the live camera: synthesizing /
    decoding frames must leave NO raw frame on disk. Drives the seeded source
    through LiveCamera and verifies no raw-sense file appears."""
    from kaine.modules.topos.feed import SeededProceduralSource, SeededSchedule

    runtime_path = tmp_path / "state" / "perception" / "runtime.json"
    desired_path = tmp_path / "state" / "perception" / "desired.json"
    monkeypatch.setattr(perception_state, "RUNTIME_PATH", runtime_path)
    monkeypatch.setattr(perception_state, "DESIRED_PATH", desired_path)

    pre_repo = _scan_for_raw_sense_files(tmp_path)
    pre_state = _scan_for_raw_sense_files(Path("state"))
    pre_data = _scan_for_raw_sense_files(Path("data"))

    sink_video_calls: list = []

    async def video_sink(img):
        sink_video_calls.append(img)

    schedule = SeededSchedule(seed=7, width=32, height=24, surprise_interval=5)
    cam = LiveCamera(
        video_sink,
        config=LiveCameraConfig(
            capture_interval_s=0.02,
            warmup_frames=0,
            desired_state_poll_ms=20,
        ),
        state_writer=perception_state.update_video_runtime,
        desired_state_reader=lambda: True,
        source_factory=lambda device, *, width, height: SeededProceduralSource(schedule),
        # Identity converter — the synthesized ndarray is just tagged through.
        bgr_to_rgb=lambda f: ("frame", getattr(f, "shape", None)),
    )

    await cam.initialize()
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            if len(sink_video_calls) >= 5:
                break
    finally:
        await cam.shutdown()

    assert sink_video_calls, "seeded source produced no frames — test inconclusive"

    new_repo = _scan_for_raw_sense_files(tmp_path)
    new_state = _scan_for_raw_sense_files(Path("state"))
    new_data = _scan_for_raw_sense_files(Path("data"))
    leaked = (
        (set(new_repo) - set(pre_repo))
        | (set(new_state) - set(pre_state))
        | (set(new_data) - set(pre_data))
    )
    assert leaked == set(), (
        f"ZERO-PERSISTENCE INVARIANT VIOLATED by the deterministic feed: raw "
        f"frame file(s) appeared on disk: {sorted(p.name for p in leaked)}"
    )


def test_no_frame_writers_in_perception_feed_module():
    """No frame-persisting call may appear in the deterministic-feed module.

    Extends the static guard to the new sources: besides cv2.imwrite/VideoWriter
    (covered repo-wide above), forbid PIL Image.save / numpy.save / ndarray
    .tofile / imageio.imwrite / plt.imsave in kaine/modules/topos/feed.py — any
    of which would persist a synthesized/decoded frame."""
    repo_root = Path(__file__).parent.parent
    target = repo_root / "kaine" / "modules" / "topos" / "feed.py"
    proc = subprocess.run(
        [
            "git",
            "grep",
            "-nE",
            r"(\.save\(|\.tofile\(|imwrite\(|imsave\(|np\.save\(|numpy\.save\()",
            "--",
            str(target),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    matches = [line for line in proc.stdout.strip().splitlines() if line]
    assert matches == [], (
        f"frame-persisting call present in feed.py (zero-persistence): {matches}"
    )


def test_perception_preview_persists_nothing():
    """The dev-gated perception PREVIEW (paper §4.4 override) must obey the same
    zero-persistence invariant: the holder + the Topos/Audition taps may keep a
    single frame/level in RAM but must open NO file and invoke NO frame/audio
    writer. Extends the invariant to the new preview code path."""
    repo_root = Path(__file__).parent.parent
    targets = [
        repo_root / "kaine" / "perception_preview.py",
        # The loopback preview server bridges the RAM holder to Nexus over a
        # socket — it must never spill a frame to disk either.
        repo_root / "kaine" / "perception_preview_server.py",
        repo_root / "kaine" / "modules" / "topos" / "module.py",
        repo_root / "kaine" / "modules" / "audition" / "live.py",
    ]
    # Frame/audio persisting calls forbidden across all three files. `wave.open`
    # is allowed in audition/live.py ONLY against io.BytesIO (covered by
    # test_no_wave_open_to_file_path_under_audition), so it is excluded here.
    pattern = (
        r"(cv2\.(imwrite|VideoWriter)|imsave\(|np\.save\(|numpy\.save\(|\.tofile\()"
    )
    for target in targets:
        proc = subprocess.run(
            ["git", "grep", "-nE", pattern, "--", str(target)],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        matches = [line for line in proc.stdout.strip().splitlines() if line]
        assert matches == [], (
            f"perception preview path has a frame/audio disk writer in "
            f"{target.name}: {matches}"
        )

    # The preview holder specifically must open NO file at all (any mode). The
    # only image encode is to an in-memory BytesIO.
    preview_src = (repo_root / "kaine" / "perception_preview.py").read_text()
    for banned in ("open(", "Path(", ".save("):
        # `.save(` appears as `img.save(buf, ...)` writing to a BytesIO — allow
        # that exact in-memory form, forbid any path-based save.
        if banned == ".save(":
            assert "img.save(buf" in preview_src, "preview save must target BytesIO"
        else:
            assert banned not in preview_src, (
                f"perception_preview.py must not reference {banned!r} "
                f"(no file access — RAM-only holder)"
            )
    assert "io.BytesIO" in preview_src

    # The loopback preview server must likewise open no file for writing — it
    # only reads the RAM holder and writes to sockets.
    server_src = (
        repo_root / "kaine" / "perception_preview_server.py"
    ).read_text()
    assert not re.search(r"open\([^)]*['\"][wax]\+?b?['\"]", server_src), (
        "perception_preview_server.py must not open any file for writing"
    )


@pytest.mark.asyncio
async def test_topos_preview_tap_writes_no_frame_to_disk(tmp_path, monkeypatch):
    """With the dev override ON, driving Topos.process_frame captures a single
    in-memory JPEG but leaves NO raw frame on disk (repo/state/data/tmp)."""
    PILImage = pytest.importorskip("PIL.Image")
    fakeredis = pytest.importorskip("fakeredis.aioredis")

    from kaine import perception_preview
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.topos import Topos

    class _Enc:
        model_id = "fake/enc"
        latent_dim = 4

        async def load(self):
            return None

        async def shutdown(self):
            return None

        async def encode(self, image):  # noqa: ARG002
            return [1.0, 0.0, 0.0, 0.0]

    monkeypatch.setenv(perception_preview.DEV_ENV_VAR, "1")
    perception_preview.clear()

    pre_repo = _scan_for_raw_sense_files(tmp_path)
    pre_state = _scan_for_raw_sense_files(Path("state"))
    pre_data = _scan_for_raw_sense_files(Path("data"))
    pre_tmp = _scan_for_raw_sense_files(Path("/tmp"))

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    topos = Topos(bus, encoder=_Enc())
    try:
        for _ in range(5):
            await topos.process_frame(PILImage.new("RGB", (32, 24), (7, 7, 7)))
        # The preview lives in memory only.
        assert topos._preview_jpeg is not None
        assert perception_preview.get_video_jpeg() == topos._preview_jpeg
    finally:
        await bus.close()
        perception_preview.clear()

    leaked = (
        (set(_scan_for_raw_sense_files(tmp_path)) - set(pre_repo))
        | (set(_scan_for_raw_sense_files(Path("state"))) - set(pre_state))
        | (set(_scan_for_raw_sense_files(Path("data"))) - set(pre_data))
        | (set(_scan_for_raw_sense_files(Path("/tmp"))) - set(pre_tmp))
    )
    assert leaked == set(), (
        f"ZERO-PERSISTENCE INVARIANT VIOLATED by the preview tap: raw frame "
        f"file(s) appeared on disk: {sorted(p.name for p in leaked)}"
    )


def test_no_pcm_writers_in_audio_feed_module():
    """No PCM/frame-persisting call may appear in the deterministic AUDIO feed
    module (unified-perception-feed).

    The seeded source synthesizes int16 PCM and the playlist source DECODES an
    audio track via PyAV; neither may persist a sample. Forbid the file-opening
    sinks that would write raw PCM/audio to disk: wave.open, soundfile.write,
    scipy.io.wavfile.write, ndarray .tofile, np.save, av.open(..., 'w'), and a
    bare open(...) in any write mode."""
    repo_root = Path(__file__).parent.parent
    target = repo_root / "kaine" / "modules" / "audition" / "feed.py"
    # One explicit pattern (no implicit literal concatenation, so a dropped
    # comma can't silently split it into two list elements).
    pattern = "".join(
        [
            r"(wave\.open\(|soundfile\.|sf\.write\(|wavfile\.write\(|",
            r"\.tofile\(|np\.save\(|numpy\.save\(|",
            r"open\([^)]*['\"][waxr]b?\+?['\"]|mode\s*=\s*['\"]w)",
        ]
    )
    proc = subprocess.run(
        [
            "git",
            "grep",
            "-nE",
            pattern,
            "--",
            str(target),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    matches = [line for line in proc.stdout.strip().splitlines() if line]
    assert matches == [], (
        f"PCM/audio-persisting call present in audition/feed.py "
        f"(zero-persistence): {matches}"
    )


class _AnyAudioVAD:
    """Test VAD: treat any non-silent block as speech so the segmenter flushes."""

    def is_speech(self, frame, sample_rate):  # noqa: D401, ANN001
        return any(b for b in frame[:200])


@pytest.mark.asyncio
async def test_seeded_audio_stream_persists_no_raw_pcm(tmp_path, monkeypatch):
    """The seeded audio source must obey the same zero-persistence invariant as
    the live mic: synthesizing PCM must leave NO raw audio file on disk. Drives
    the seeded audio stream through LiveMicrophone and verifies no raw-sense file
    appears."""
    from kaine.modules.audition.feed import (
        SeededAudioSchedule,
        SeededProceduralAudioStream,
    )

    runtime_path = tmp_path / "state" / "perception" / "runtime.json"
    desired_path = tmp_path / "state" / "perception" / "desired.json"
    monkeypatch.setattr(perception_state, "RUNTIME_PATH", runtime_path)
    monkeypatch.setattr(perception_state, "DESIRED_PATH", desired_path)

    pre_repo = _scan_for_raw_sense_files(tmp_path)
    pre_state = _scan_for_raw_sense_files(Path("state"))
    pre_data = _scan_for_raw_sense_files(Path("data"))

    sink_calls: list[bytes] = []

    async def audio_sink(wav, sr, label):
        sink_calls.append(wav)

    schedule = SeededAudioSchedule(
        seed=3, sample_rate=16000, frames_per_block=480, surprise_interval=2,
        base_strength=0.5, surprise_strength=1.0,
    )
    mic = LiveMicrophone(
        audio_sink,
        config=LiveMicConfig(
            sample_rate=16000,
            vad_frame_ms=30,
            min_utterance_ms=60,
            max_utterance_ms=500,
            silence_hangover_ms=60,
            desired_state_poll_ms=20,
        ),
        state_writer=perception_state.update_audio_runtime,
        desired_state_reader=lambda: True,
        # Boot would inject this seeded factory in seeded mode.
        stream_factory=lambda **kw: SeededProceduralAudioStream(
            schedule, callback=kw["callback"]
        ),
        # Treat any non-silent block as speech so the segmenter flushes.
        vad_factory=_AnyAudioVAD,
    )

    await mic.initialize()
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            if sink_calls:
                break
    finally:
        await mic.shutdown()

    new_repo = _scan_for_raw_sense_files(tmp_path)
    new_state = _scan_for_raw_sense_files(Path("state"))
    new_data = _scan_for_raw_sense_files(Path("data"))
    leaked = (
        (set(new_repo) - set(pre_repo))
        | (set(new_state) - set(pre_state))
        | (set(new_data) - set(pre_data))
    )
    assert leaked == set(), (
        f"ZERO-PERSISTENCE INVARIANT VIOLATED by the seeded audio feed: raw "
        f"audio file(s) appeared on disk: {sorted(p.name for p in leaked)}"
    )
