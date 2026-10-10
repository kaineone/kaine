# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.eidolon import Eidolon, SelfModel


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source: str, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type="t",
        payload={},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(sources: list[str]) -> WorkspaceSnapshot:
    events = [(f"e{i}", _event(s)) for i, s in enumerate(sources)]
    return WorkspaceSnapshot(tick_index=0, selected_events=events, inhibited=False)


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus, tmp_path: Path):
    p = tmp_path / "model.json"
    with pytest.raises(ValueError):
        Eidolon(bus, persistence_path=p, baseline_salience=2.0)
    with pytest.raises(ValueError):
        Eidolon(bus, persistence_path=p, alert_salience=-0.1)
    with pytest.raises(ValueError):
        Eidolon(bus, persistence_path=p, drift_threshold=-0.1)
    with pytest.raises(ValueError):
        Eidolon(bus, persistence_path=p, save_interval_s=0)


@pytest.mark.asyncio
async def test_initialize_loads_existing_model(bus: AsyncBus, tmp_path: Path):
    p = tmp_path / "model.json"
    p.write_text(
        SelfModel(values=["honesty"]).to_json(), encoding="utf-8"
    )
    eidolon = Eidolon(bus, persistence_path=p, save_interval_s=60)
    await eidolon.initialize()
    try:
        assert eidolon.model.values == ["honesty"]
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_initialize_empty_file_yields_empty_model(bus: AsyncBus, tmp_path: Path):
    p = tmp_path / "model.json"
    eidolon = Eidolon(bus, persistence_path=p, save_interval_s=60)
    await eidolon.initialize()
    try:
        # Empty except for the launch name assigned on first boot.
        assert eidolon.model.name.startswith("Kaine ")
        assert eidolon.model.with_updates(name="") == SelfModel()
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_workspace_below_threshold_no_event(bus: AsyncBus, tmp_path: Path):
    eidolon = Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        drift_threshold=100.0,  # essentially unreachable
        save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        # Eidolon publishes an initial self-model seed to eidolon.out at boot
        # (the bus-mediated persona snapshot a split-host Lingua consumes). Seek
        # past it so this test measures only the below-threshold drift behavior.
        tail = await bus.client.xrevrange("eidolon.out", count=1)
        cursor = (tail[0][0] if tail else "0")
        for _ in range(5):
            await eidolon.on_workspace(_snapshot(["soma", "chronos"]))
        entries = await bus.read("eidolon.out", last_id=cursor)
        assert len(entries) == 0
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_workspace_above_threshold_publishes_diagnostics_only(bus: AsyncBus, tmp_path: Path):
    eidolon = Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        drift_threshold=0.0,  # any drift triggers
        save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        await eidolon.on_workspace(_snapshot(["soma", "chronos"]))
        await eidolon.on_workspace(_snapshot(["mnemos"]))
        entries = await bus.read("eidolon.out", last_id="0")
        assert len(entries) >= 1
        _, ev = entries[-1]
        # Diagnostics-only payload
        keys = set(ev.payload.keys())
        assert keys == {
            "score",
            "recent_count",
            "historical_count",
            "reference_count",
            "top_drifted_sources",
        }
        assert ev.salience == pytest.approx(eidolon._alert_salience)
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_drift_event_carries_no_contents(bus: AsyncBus, tmp_path: Path):
    eidolon = Eidolon(
        bus, persistence_path=tmp_path / "m.json",
        drift_threshold=0.0, save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        # Seek past the boot self-model seed so entries[0] is the drift event.
        tail = await bus.client.xrevrange("eidolon.out", count=1)
        cursor = (tail[0][0] if tail else "0")
        await eidolon.on_workspace(_snapshot(["soma"]))
        entries = await bus.read("eidolon.out", last_id=cursor)
        _, ev = entries[0]
        # Forbidden keys per the privacy boundary.
        for forbidden in ("text", "payload", "value", "belief"):
            assert forbidden not in ev.payload
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_internal_speech_increments_counter(bus: AsyncBus, tmp_path: Path):
    import asyncio
    eidolon = Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        internal_speech_stream="lingua.internal",
        save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        # Publish three events to lingua.internal directly.
        for _ in range(3):
            await bus.client.xadd(
                "lingua.internal",
                {
                    "source": "lingua",
                    "type": "internal.thought",
                    "salience": "0.1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "causal_parent": "",
                    "payload": "{}",
                },
            )
        for _ in range(50):
            if eidolon.model.internal_speech_count >= 3:
                break
            await asyncio.sleep(0.01)
        assert eidolon.model.internal_speech_count == 3
    finally:
        await eidolon.shutdown()


async def _publish_speech(bus: AsyncBus, stream: str, text: str) -> None:
    import json as _json

    await bus.client.xadd(
        stream,
        {
            "source": "lingua",
            "type": "internal_speech" if stream.endswith("internal") else "external_speech",
            "salience": "0.1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causal_parent": "",
            "payload": _json.dumps({"text": text}),
        },
    )


async def _wait_until(predicate, attempts: int = 100, delay: float = 0.01) -> None:
    import asyncio

    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(delay)


@pytest.mark.asyncio
async def test_voice_observation_records_features_both_channels(
    bus: AsyncBus, tmp_path: Path
):
    eidolon = Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        internal_speech_stream="lingua.internal",
        external_speech_stream="lingua.external",
        save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        await _publish_speech(bus, "lingua.internal", "thinking quietly here")
        await _publish_speech(bus, "lingua.external", "hello world out loud now")

        await _wait_until(
            lambda: len(eidolon.model.voice_observations) >= 2
            and eidolon.model.internal_speech_count >= 1
            and eidolon.model.external_speech_count >= 1
        )

        obs = eidolon.model.voice_observations
        assert len(obs) == 2
        assert eidolon.model.internal_speech_count == 1
        assert eidolon.model.external_speech_count == 1

        by_channel = {o["channel"]: o for o in obs}
        assert set(by_channel) == {"internal", "external"}

        internal = by_channel["internal"]
        assert internal["length"] == len("thinking quietly here")
        assert internal["word_count"] == 3
        assert isinstance(internal["timestamp"], float)

        external = by_channel["external"]
        assert external["length"] == len("hello world out loud now")
        assert external["word_count"] == 5
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_voice_observation_stores_no_raw_text(bus: AsyncBus, tmp_path: Path):
    eidolon = Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        secret = "do not persist this sentence anywhere"
        await _publish_speech(bus, "lingua.internal", secret)
        await _wait_until(lambda: len(eidolon.model.voice_observations) >= 1)

        obs = eidolon.model.voice_observations[0]
        # Derived features only — no raw text under any key, and the
        # serialized JSON must not contain the utterance content.
        assert set(obs.keys()) == {"timestamp", "channel", "length", "word_count"}
        serialized = eidolon.model.to_json()
        assert secret not in serialized
        # Per-word paranoia, but skip short common words: a 2-3 char token like
        # "do" collides with substrings of unrelated JSON (e.g. a random entity
        # name such as "Shadow"), which is a false positive, not a leak. The
        # distinctive content words are the meaningful check.
        for word in secret.split():
            if len(word) >= 5:
                assert word not in serialized
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_voice_observations_capped(bus: AsyncBus, tmp_path: Path):
    eidolon = Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        voice_observations_cap=3,
        save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        for i in range(7):
            await _publish_speech(bus, "lingua.internal", f"utterance number {i}")
        await _wait_until(lambda: eidolon.model.internal_speech_count >= 7)

        # Count keeps climbing; the buffer is capped to the most recent N.
        assert eidolon.model.internal_speech_count == 7
        assert len(eidolon.model.voice_observations) == 3
        # All retained observations carry the per-utterance word_count (== 3
        # for "utterance number i"), confirming they are real entries.
        assert all(o["word_count"] == 3 for o in eidolon.model.voice_observations)
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_voice_cap_invalid_construction(bus: AsyncBus, tmp_path: Path):
    with pytest.raises(ValueError):
        Eidolon(bus, persistence_path=tmp_path / "m.json", voice_observations_cap=-1)


@pytest.mark.asyncio
async def test_voice_observations_uncapped_by_default(bus: AsyncBus, tmp_path: Path):
    """Cap 0 (the default) keeps every voice observation."""
    eidolon = Eidolon(bus, persistence_path=tmp_path / "m.json", save_interval_s=60)
    assert eidolon._voice_observations_cap == 0
    await eidolon.initialize()
    try:
        # Wait until the speech loop is live (its "$" cursor resolved) so no
        # utterance published below is missed.
        while eidolon.model.internal_speech_count == 0:
            await _publish_speech(bus, "lingua.internal", "warm up")
            await _wait_until(lambda: eidolon.model.internal_speech_count >= 1)
        start = eidolon.model.internal_speech_count
        for i in range(300):
            await _publish_speech(bus, "lingua.internal", f"utterance number {i}")
        await _wait_until(
            lambda: eidolon.model.internal_speech_count >= start + 300, attempts=1000
        )
        assert eidolon.model.internal_speech_count == start + 300
        assert len(eidolon.model.voice_observations) == start + 300
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_shutdown_persists_final_state(bus: AsyncBus, tmp_path: Path):
    p = tmp_path / "model.json"
    eidolon = Eidolon(
        bus,
        persistence_path=p,
        drift_threshold=0.0,
        save_interval_s=60,
    )
    await eidolon.initialize()
    await eidolon.on_workspace(_snapshot(["soma"]))
    await eidolon.on_workspace(_snapshot(["mnemos"]))
    await eidolon.shutdown()
    loaded = SelfModel.from_json(p.read_text())
    # identity_history should have at least one entry from the drift event.
    assert len(loaded.identity_history) >= 1


class _ScriptedDrift:
    """Drift detector returning scripted scores (threshold 0.5 in the tests)."""

    def __init__(self, scores, sources=("topos",)):
        self._scores = list(scores)
        self._sources = tuple(sources)

    def observe(self, _sources):
        from kaine.modules.eidolon.drift import DriftResult

        score = self._scores.pop(0) if self._scores else 0.0
        return DriftResult(score, 10, 100, self._sources)

    def reset(self):
        pass


def _episodes(scores_per_episode: int, episodes: int) -> list[float]:
    """``episodes`` runs of alerting scores, each followed by one quiet score."""
    out: list[float] = []
    for e in range(episodes):
        out += [0.6 + 0.01 * (i % 7) for i in range(scores_per_episode)]
        out.append(0.1)
    return out


def _eidolon_with(bus, tmp_path, scores, **kw):
    return Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        drift_threshold=0.5,
        drift_detector=_ScriptedDrift(scores),
        save_interval_s=60,
        **kw,
    )


@pytest.mark.asyncio
async def test_sustained_drift_is_one_episode(bus: AsyncBus, tmp_path: Path):
    """N consecutive alerting broadcasts produce ONE episode with count N."""
    n = 5000
    scores = [0.6 + 0.01 * (i % 7) for i in range(n)]
    scores[1234] = 0.95  # the peak
    eidolon = _eidolon_with(bus, tmp_path, scores)
    await eidolon.initialize()
    try:
        for _ in range(n):
            await eidolon.on_workspace(_snapshot(["topos"]))
        history = eidolon.model.identity_history
        assert len(history) == 1
        ep = history[0]
        assert ep["kind"] == "drift_episode"
        assert ep["count"] == n
        assert ep["peak_score"] == pytest.approx(0.95)
        assert ep["score"] == pytest.approx(0.95)
        assert ep["sources"] == {"topos": n}
        assert ep["top_sources"] == ["topos"]
        assert ep["onset"] <= ep["end"]
        assert ep["timestamp"] == ep["onset"]
        assert eidolon._drift_count == n
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_quiet_broadcast_closes_the_episode(bus: AsyncBus, tmp_path: Path):
    eidolon = _eidolon_with(bus, tmp_path, _episodes(3, 4))
    await eidolon.initialize()
    try:
        for _ in range(16):
            await eidolon.on_workspace(_snapshot(["topos"]))
        history = eidolon.model.identity_history
        assert [ep["count"] for ep in history] == [3, 3, 3, 3]
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_save_stays_small_under_sustained_drift(bus: AsyncBus, tmp_path: Path):
    """The persisted self-model does not grow with the number of alerts."""
    path = tmp_path / "m.json"
    sizes = []
    eidolon = _eidolon_with(bus, tmp_path, [0.7] * 20000)
    await eidolon.initialize()
    try:
        for chunk in range(4):
            for _ in range(5000):
                await eidolon.on_workspace(_snapshot(["topos"]))
            await eidolon._save_to_disk()
            sizes.append(path.stat().st_size)
    finally:
        await eidolon.shutdown()
    assert max(sizes) - min(sizes) < 64
    assert max(sizes) < 4096


@pytest.mark.asyncio
async def test_identity_history_cap_keeps_most_recent_episodes(bus: AsyncBus, tmp_path: Path):
    eidolon = _eidolon_with(bus, tmp_path, _episodes(2, 10), identity_history_cap=4)
    await eidolon.initialize()
    try:
        closed = []
        for i in range(30):
            await eidolon.on_workspace(_snapshot(["topos"]))
            if i % 3 == 2:  # the quiet broadcast after each episode
                closed.append(eidolon.model.identity_history[-1])
        assert list(eidolon.model.identity_history) == closed[-4:]
        assert all(ep["count"] == 2 for ep in eidolon.model.identity_history)
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_identity_history_uncapped_by_default(bus: AsyncBus, tmp_path: Path):
    """Cap 0 (the shipped default) keeps every episode."""
    eidolon = _eidolon_with(bus, tmp_path, _episodes(1, 300))
    assert eidolon._identity_history_cap == 0
    await eidolon.initialize()
    try:
        for _ in range(600):
            await eidolon.on_workspace(_snapshot(["topos"]))
        assert len(eidolon.model.identity_history) == 300
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_old_per_alert_history_loads_and_is_kept(bus: AsyncBus, tmp_path: Path):
    """A self-model saved with indent and per-alert entries loads unchanged;
    the next alert starts a new episode after them."""
    import json as _json

    legacy = [
        {"timestamp": 1.0 + i, "score": 0.7, "top_sources": ["topos"]} for i in range(3)
    ]
    path = tmp_path / "m.json"
    path.write_text(
        _json.dumps({"name": "Kaine Vale", "identity_history": legacy}, indent=2),
        encoding="utf-8",
    )
    eidolon = _eidolon_with(bus, tmp_path, [0.7, 0.7])
    await eidolon.initialize()
    try:
        assert eidolon.model.identity_history == legacy
        await eidolon.on_workspace(_snapshot(["topos"]))
        await eidolon.on_workspace(_snapshot(["topos"]))
        history = eidolon.model.identity_history
        assert history[:3] == legacy
        assert len(history) == 4
        assert history[3]["count"] == 2
    finally:
        await eidolon.shutdown()
    reloaded = SelfModel.from_json(path.read_text())
    assert reloaded.identity_history[:3] == legacy


@pytest.mark.asyncio
async def test_identity_history_cap_negative_rejected(bus: AsyncBus, tmp_path: Path):
    with pytest.raises(ValueError):
        Eidolon(bus, persistence_path=tmp_path / "m.json", identity_history_cap=-1)


@pytest.mark.asyncio
async def test_serialize_roundtrips(bus: AsyncBus, tmp_path: Path):
    eidolon = Eidolon(
        bus,
        persistence_path=tmp_path / "m.json",
        drift_threshold=100.0,
        save_interval_s=60,
    )
    await eidolon.initialize()
    try:
        eidolon._model = eidolon._model.with_updates(
            values=["honesty"], internal_speech_count=7
        )
        state = eidolon.serialize()
        fresh = Eidolon(
            bus,
            persistence_path=tmp_path / "other.json",
            save_interval_s=60,
        )
        # We don't initialize() fresh because we just want to test deserialize.
        fresh.deserialize(state)
        assert fresh.model.values == ["honesty"]
        assert fresh.model.internal_speech_count == 7
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_eidolon_assigns_and_persists_launch_name(bus, tmp_path):
    from kaine.modules.eidolon.document import load
    path = tmp_path / "self_model.json"
    eid = Eidolon(bus, persistence_path=path)
    await eid.initialize()
    try:
        assert eid.model.name.startswith("Kaine ")
        assigned = eid.model.name
        # Persisted to disk...
        assert load(path).name == assigned
    finally:
        await eid.shutdown()
    # ...and stable across a fresh load (entity keeps its name).
    eid2 = Eidolon(bus, persistence_path=path)
    await eid2.initialize()
    try:
        assert eid2.model.name == assigned
    finally:
        await eid2.shutdown()
