# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""An entity-free, seeded harness for the stimulus-control disabled-identity test.

It drives the parts stimulus control touches, as a build without the component
has them: the affect module (drives, the credit rule, its published events),
the action layer (the drive-biased policy, signing), the effectors module
(provenance, the whitelist, the audit log, ``effectors.action``), the welfare
observer's record writes and the playlist video source on the shared clock. The
input is a fixed script that includes realized ``stimulus`` actions on the
effectors stream and a signed act intent naming ``stimulus``, which a build
without the component ignores.

It imports only names that exist in the build before stimulus control, so the
same file computes the golden digest on that build (origin/main d7fabdc0) (see
``tests/test_stimulus_disabled_identity.py``).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET = b"stimulus-identity-harness-secret-32"


class _FakeDecoder:
    """One item's video at 10 fps: frame ``i`` at ``i / 10`` s, tagged
    ``(basename, i)``; seek lands on the frame at or before the target."""

    def __init__(self, path: str, frame_count: int) -> None:
        self._path = path
        self._n = frame_count
        self._i = 0
        self.duration = frame_count / 10.0
        self.frame_interval = 0.1

    def next(self):
        if self._i >= self._n:
            return None
        i = self._i
        self._i += 1
        return i / 10.0, (self._path, i)

    def seek(self, seconds: float) -> None:
        self._i = max(0, min(self._n - 1, int(seconds * 10.0)))

    @staticmethod
    def image(frame):
        return frame

    def close(self) -> None:
        return None


def _fake_decoders(frame_counts: dict[str, int]):
    def _factory(path, item):  # noqa: ANN001, ANN202
        base = os.path.basename(str(path))
        return _FakeDecoder(base, frame_counts[base])

    return _factory


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def write(self, entry: dict[str, Any]) -> None:
        self.rows.append({k: v for k, v in entry.items() if k != "ts"})


_RUN_IDS = re.compile(r"[0-9a-f]{32}|(?:[a-z_]+\.out:)?\d+-\d+")


def _round(value: Any, ids: dict[str, str] | None = None) -> Any:
    """Floats exactly (hex); goal ids and bus entry ids by order of appearance."""
    ids = {} if ids is None else ids
    if isinstance(value, float):
        return float.hex(value) if math.isfinite(value) else repr(value)
    if isinstance(value, str) and _RUN_IDS.fullmatch(value):
        return ids.setdefault(value, f"id{len(ids)}")
    if isinstance(value, dict):
        return {
            str(k): _round(v, ids) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_round(v, ids) for v in value]
    return value


def _event(source: str, type_: str, payload: dict[str, Any], salience: float = 0.5):
    from kaine.bus.schema import Event

    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=salience,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _video_trace(tmp_path: Path) -> list[Any]:
    import hashlib as _h

    from kaine.modules.vision.feed import PlaylistClock, PlaylistSource, load_playlist_manifest

    root = tmp_path / "films"
    root.mkdir(parents=True, exist_ok=True)
    lines = []
    for name in ("a.mp4", "b.mp4"):
        (root / name).write_bytes(name.encode())
        lines.append(
            f'[[item]]\npath = "{name}"\nsha256 = "{_h.sha256(name.encode()).hexdigest()}"\nfps = 10\n'
        )
    (root / "programme.toml").write_text("\n".join(lines), encoding="utf-8")
    manifest = load_playlist_manifest(root / "programme.toml")
    t = [0.0]
    clock = PlaylistClock(len(manifest.items), clock=lambda: t[0])
    source = PlaylistSource(
        manifest, playlist_clock=clock, decoder_factory=_fake_decoders({"a.mp4": 20, "b.mp4": 20})
    )
    opened = source.open()
    assert opened
    trace: list[Any] = []
    for k in range(50):
        t[0] = 0.09 * k
        if k == 12:
            clock.pause("sleep")
        if k == 20:
            clock.resume("sleep")
        ok, frame = source.read()
        trace.append([ok, list(frame) if ok else None, clock.locate()[0]])
    return trace


def _write_wav(path: Path, *, tone_hz: float, seconds: float, rate: int = 16000) -> None:
    import av  # type: ignore[import-untyped]
    import numpy as np

    container = av.open(str(path), mode="w")
    stream = container.add_stream("pcm_s16le", rate=rate)
    stream.layout = "mono"
    t = np.arange(int(rate * seconds))
    samples = (0.25 * np.sin(2 * np.pi * tone_hz * t / rate) * 32767).astype(np.int16)
    for k in range(0, len(samples), 1600):
        frame = av.AudioFrame.from_ndarray(
            samples[k:k + 1600].reshape(1, -1), format="s16", layout="mono"
        )
        frame.rate = rate
        frame.pts = k
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()


def _audio_trace(tmp_path: Path) -> list[Any]:
    """The real playlist audio producer over two real WAV items, paced by a
    manual shared clock that its waits advance, with one stall that makes it
    skip forward and one pause."""
    import hashlib as _h

    from kaine.modules.audition.feed import PlaylistAudioStream
    from kaine.modules.vision.feed import PlaylistClock, load_playlist_manifest

    root = tmp_path / "sound"
    root.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, tone in (("a.wav", 300.0), ("b.wav", 500.0)):
        _write_wav(root / name, tone_hz=tone, seconds=1.5)
        digest = _h.sha256((root / name).read_bytes()).hexdigest()
        lines.append(f'[[item]]\npath = "{name}"\nsha256 = "{digest}"\nfps = 10\n')
    (root / "programme.toml").write_text("\n".join(lines), encoding="utf-8")
    manifest = load_playlist_manifest(root / "programme.toml")
    t = [0.0]
    clock = PlaylistClock(len(manifest.items), clock=lambda: t[0])
    trace: list[Any] = []
    holder: list[Any] = []

    def _on_pcm(pcm: bytes) -> None:
        n = len(trace)
        trace.append([_h.sha256(pcm).hexdigest()[:16], list(holder[0]._delivered), t[0]])
        if n == 20:
            t[0] += 0.9  # a stall: the producer skips forward to the clock
        if n == 40:
            clock.pause("sleep")
            t[0] += 5.0
            clock.resume("sleep")

    stream = PlaylistAudioStream(
        manifest, callback=_on_pcm, sample_rate=16000, channels=1,
        frames_per_block=480, playlist_clock=clock,
    )
    holder.append(stream)

    def _advance(seconds: float) -> bool:
        t[0] += seconds
        return False

    stream._pace_wait = _advance
    stream._produce()
    trace.append(["skips", stream._skips, "failures", stream._item_failures])
    return trace


async def run(tmp_path: Path, *, affect_setup: Any = None) -> dict[str, Any]:
    """Run the script once; return the content of every output, floats exact.

    ``affect_setup(affect)`` runs before the script (the test turns the
    component on through it to show the harness sees it).
    """
    import fakeredis.aioredis  # type: ignore[import-untyped]

    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.cycle.types import WorkspaceSnapshot
    from kaine.evaluation.observers.welfare_observer import WelfareObserver
    from kaine.modules.affect import Affect
    from kaine.modules.effectors import Effectors, NotifyRequest
    from kaine.security.intent_signing import IntentSigner, compute_intent_signature
    from kaine.workspace.action_selection import INTENT_TYPES, ActionSelection
    from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy

    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    if affect_setup is not None:
        affect_setup(affect)
    effectors = Effectors(
        bus,
        sandbox_path=tmp_path / "sandbox",
        audit_log_path=tmp_path / "audit.log",
        notification_fallback_log=tmp_path / "notify.log",
        enabled_effectors=[],
        intent_secret=_SECRET,
    )
    selection = ActionSelection(
        DriveBiasedActionSelectionPolicy(clock=lambda: t[0]),
        signer=IntentSigner(_SECRET, "identity-run"),
    )
    intents: list[Any] = []
    drives: list[Any] = []
    cursor = "0"
    leads: list[Any] = []
    try:
        for k in range(1800):
            t[0] = 0.5 * k
            # A perceptual stream with a slow error trend and scene-cut alerts.
            error = 0.4 + 0.2 * math.sin(k / 37.0) - 0.0002 * k
            await affect._handle_peer_event(
                "vision.out",
                _event(
                    "vision",
                    "vision.report",
                    {
                        "prediction_error": error,
                        "alert": (k // 60) % 3 == 2 or (k % 23 == 0),
                        "normalised_error": 1.0 + (k % 5) * 0.3,
                        "normalised_change": 1.2,
                    },
                ),
            )
            if k % 41 == 7:
                # A realized stimulus act, as an enabled build would publish it.
                await affect._handle_peer_event(
                    "effectors.out",
                    _event("effectors", "effectors.action", {"effector": "stimulus", "success": True}),
                )
            await affect._tick(own_update=(k % 2 == 0))
            await affect._maybe_publish_state()
            entries, scanned = await bus.read_entries("affect.out", cursor, 10000, 0)
            if scanned is not None:
                cursor = scanned
            for eid, e in entries:
                if e.type == "affect.drive":
                    leads = [(f"affect.out:{eid}", e)]
            snapshot = WorkspaceSnapshot(
                tick_index=k,
                selected_events=leads,
                salience_scores={key: 0.9 for key, _ in leads},
            )
            for intent in selection.select(snapshot):
                payload = intent.to_event_payload()
                intents.append([k, payload])
                await affect._handle_peer_event(
                    "action_selection.out",
                    _event("action_selection", INTENT_TYPES[intent.kind], payload),
                )
            drives.append([k, affect.drives.to_dict(), affect.drives.outcomes_to_dict()])
        # A signed act intent naming stimulus: dropped by a build without it.
        params = {"action": "next"}
        await effectors._handle_intent(
            _event(
                "action_selection",
                "intent.act",
                {
                    "kind": "act",
                    "effector": "stimulus",
                    "params": params,
                    "run_id": "identity-run",
                    "seq": 10_000,
                    "sig": compute_intent_signature(
                        _SECRET, kind="act", effector="stimulus", params=params,
                        run_id="identity-run", seq=10_000,
                    ),
                },
            )
        )
        await effectors.act("notify", NotifyRequest(title="t", body="b"))
        affect_events = [
            [e.type, e.payload] for _, e in await bus.read("affect.out", last_id="0", count=100000)
        ]
        effector_events = [
            [e.type, e.payload] for _, e in await bus.read("effectors.out", last_id="0", count=1000)
        ]
        audit = []
        audit_path = tmp_path / "audit.log"
        if audit_path.exists():
            for line in audit_path.read_text().splitlines():
                rec = json.loads(line)
                audit.append({k: v for k, v in rec.items() if k in ("effector", "request", "success", "error", "blocked")})
        sink = _Sink()
        observer = WelfareObserver(bus, sink)
        for i, (kind, payload) in enumerate(affect_events):
            if kind == "affect.state":
                observer._affect_tally.observe_state(
                    0.5 * i,
                    float(payload["state"]["valence"]),
                    payload.get("drive_above"),
                    payload.get("drive_ends"),
                    payload.get("drive_reset_ends"),
                    payload.get("drive_open"),
                )
        await observer._cleanup()
    finally:
        await bus.close()
    return _round(
        {
            "intents": intents,
            "drives": drives,
            "affect_events": affect_events,
            "effector_events": effector_events,
            "audit": audit,
            "welfare_rows": sink.rows,
            "video": _video_trace(tmp_path),
            "audio": _audio_trace(tmp_path),
        }
    )


def digest(result: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":  # pragma: no cover - golden capture on a build without the component
    import asyncio
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        out = asyncio.run(run(Path(d)))
        print(digest(out))
        if len(sys.argv) > 1:
            Path(sys.argv[1]).write_text(json.dumps(out, sort_keys=True), encoding="utf-8")
