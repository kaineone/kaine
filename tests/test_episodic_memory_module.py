# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory import module as episodic_memory_module


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _new_episodic_memory(bus: AsyncBus, *, capacity: int = 4, **kwargs) -> EpisodicMemory:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(embedder=emb, storage=storage, short_term_capacity=capacity)
    return EpisodicMemory(bus, core=core, **kwargs)


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events or [],
        inhibited=False,
    )


def _event(source="interoception", type_="wellness.update", salience=0.5, eid="e1"):
    return eid, Event(
        source=source,
        type=type_,
        payload={"x": 1},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_workspace_broadcast_stores_short_term(bus: AsyncBus):
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        await episodic_memory.on_workspace(_snapshot([_event()]))
        assert episodic_memory.core.short_term_size == 1
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_empty_snapshot_is_noop(bus: AsyncBus):
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        # An empty snapshot still serializes to "active"/"inhibited" so it
        # counts as a store; verify behavior with explicitly empty.
        snap = WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
        await episodic_memory.on_workspace(snap)
        # The serialized text is non-empty ("active"), so one entry stored.
        assert episodic_memory.core.short_term_size == 1
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_capacity_consolidates_to_episodic(bus: AsyncBus):
    episodic_memory = await _new_episodic_memory(bus, capacity=2)
    await episodic_memory.initialize()
    try:
        for i in range(4):
            await episodic_memory.on_workspace(_snapshot([_event(eid=f"e{i}")]))
        assert episodic_memory.core.short_term_size == 2
        episodic = episodic_memory.core.collection_name("episodic")
        assert await episodic_memory.core.storage.count(episodic) == 2
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_recall_publishes_diagnostics_only(bus: AsyncBus):
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        await episodic_memory.core.store(
            "I remember the fire",
            payload={"some": "details"},
            affect={"label": "fear", "intensity": 0.7},
            collection="episodic",
        )
        results = await episodic_memory.recall("fire", collection="episodic")
        assert len(results) == 1
        entries = await bus.read("episodic_memory.out", last_id="0")
        assert len(entries) == 1
        _, event = entries[0]
        assert event.type == "episodic_memory.recall"
        payload = event.payload
        assert set(payload.keys()) >= {
            "count",
            "collection",
            "query_length",
            "max_affect_intensity",
        }
        # Privacy: no memory contents leak through the bus event.
        for value in payload.values():
            if isinstance(value, str):
                assert "fire" not in value
                assert "details" not in value
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_recall_with_high_affect_uses_alert_salience(bus: AsyncBus):
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        await episodic_memory.core.store(
            "intense recall",
            affect={"intensity": 0.9, "label": "joy"},
            collection="episodic",
        )
        await episodic_memory.recall("intense", collection="episodic")
        entries = await bus.read("episodic_memory.out", last_id="0")
        _, event = entries[0]
        assert event.salience == pytest.approx(episodic_memory._alert_salience)
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_invalid_construction_rejected(bus: AsyncBus):
    with pytest.raises(ValueError):
        EpisodicMemory(bus, core=None, embedder=FakeEmbedder(), backend="qdrant")  # missing api_key
    with pytest.raises(ValueError):
        EpisodicMemory(bus, baseline_salience=2.0)
    with pytest.raises(ValueError):
        EpisodicMemory(bus, recall_top_k=0)


@pytest.mark.asyncio
async def test_consolidate_now_returns_count(bus: AsyncBus):
    episodic_memory = await _new_episodic_memory(bus, capacity=4)
    await episodic_memory.initialize()
    try:
        for _ in range(3):
            await episodic_memory.on_workspace(_snapshot([_event()]))
        moved = await episodic_memory.consolidate_now()
        assert moved == 3
        assert episodic_memory.core.short_term_size == 0
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_serialize_yields_state(bus: AsyncBus):
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        await episodic_memory.on_workspace(_snapshot([_event()]))
        state = episodic_memory.serialize()
        assert state["short_term_size"] == 1
        assert state["collection_prefix"] == "mnemos_"
    finally:
        await episodic_memory.shutdown()


# --- Spontaneous cue-based recall in the live loop ----------------------------


async def _recall_events(bus: AsyncBus) -> list:
    entries = await bus.read("episodic_memory.out", last_id="0")
    return [e for _, e in entries if e.type == "episodic_memory.recall"]


@pytest.mark.asyncio
async def test_cued_tick_with_cooldown_elapsed_triggers_recall(bus: AsyncBus):
    # Scenario: A cued experiential tick (cooldown elapsed) triggers recall and
    # publishes exactly one episodic_memory.recall event.
    episodic_memory = await _new_episodic_memory(bus, recall_cooldown_s=0.0)
    await episodic_memory.initialize()
    try:
        await episodic_memory.on_workspace(_snapshot([_event()]))
        recalls = await _recall_events(bus)
        assert len(recalls) == 1
        assert recalls[0].type == "episodic_memory.recall"
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_cooldown_suppresses_repeated_recall(bus: AsyncBus):
    # Scenario: rapid ticks faster than the cooldown -> at most one recall per
    # window. A frozen subjective clock (the injected EntityClock's monotonic
    # source stays put) means no time elapses across the rapid ticks.
    frozen = EntityClock(monotonic=lambda: 1000.0)
    episodic_memory = await _new_episodic_memory(bus, recall_cooldown_s=5.0, entity_clock=frozen)
    await episodic_memory.initialize()
    try:
        for i in range(5):
            await episodic_memory.on_workspace(_snapshot([_event(eid=f"e{i}")]))
        recalls = await _recall_events(bus)
        assert len(recalls) == 1  # only the first tick within the window fired
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_recall_fires_again_after_cooldown_elapses(bus: AsyncBus):
    # A controllable clock: first recall at t=1000, second tick after the
    # cooldown window should fire again. The injected EntityClock reads its
    # monotonic source on every now() call, so advancing it advances the clock.
    clock = {"now": 1000.0}
    episodic_memory = await _new_episodic_memory(
        bus, recall_cooldown_s=5.0, entity_clock=EntityClock(monotonic=lambda: clock["now"])
    )
    await episodic_memory.initialize()
    try:
        await episodic_memory.on_workspace(_snapshot([_event(eid="a")]))
        clock["now"] = 1003.0  # within cooldown -> suppressed
        await episodic_memory.on_workspace(_snapshot([_event(eid="b")]))
        clock["now"] = 1006.0  # cooldown elapsed -> fires again
        await episodic_memory.on_workspace(_snapshot([_event(eid="c")]))
        recalls = await _recall_events(bus)
        assert len(recalls) == 2
    finally:
        await episodic_memory.shutdown()


def test_serialize_snapshot_omits_raw_perceptual_payload():
    """S6 — a selected raw-perceptual event's verbatim payload is never put in
    the memory text at the encoding site (independent of downstream redaction)."""
    secret = "this is a VERBATIM transcript of a private conversation"
    transcription = (
        "e_audio",
        Event(
            source="audition",
            type="audition.transcription",
            payload={"text": secret},
            salience=0.9,
            timestamp=datetime.now(timezone.utc),
        ),
    )
    visual = (
        "e_vis",
        Event(
            source="embodiment",
            type="embodiment.visual.raw",
            payload={"frame_b64": "RAWPIXELS"},
            salience=0.9,
            timestamp=datetime.now(timezone.utc),
        ),
    )
    # A non-perceptual event still has its payload serialized as before.
    ordinary = _event(source="interoception", type_="interoception.report", eid="e_interoception")
    text = episodic_memory_module._serialize_snapshot(_snapshot([transcription, visual, ordinary]))
    assert secret not in text
    assert "RAWPIXELS" not in text
    assert "<raw-perceptual omitted>" in text
    # The metadata (source:type) is still recorded for both perceptual events,
    # but the bus entry IDs and tick index are omitted from the memory text.
    assert "audition:audition.transcription" in text
    assert "embodiment:embodiment.visual.raw" in text
    assert "tick=" not in text
    assert "@" not in text
    # The ordinary event's payload survives.
    assert "interoception:interoception.report={'x': 1}" in text


def test_serialize_snapshot_records_replay_without_its_text():
    replay = (
        "e_rep",
        Event(
            source="episodic_memory",
            type="episodic_memory.replay",
            payload={
                "memory_id": "abc123",
                "text": "an old trace with SECRET words",
                "affect": None,
                "affect_intensity": 0.4,
                "source_timestamp": 1.0,
                "replayed_at": 2.0,
            },
            salience=0.15,
            timestamp=datetime.now(timezone.utc),
        ),
    )
    text = episodic_memory_module._serialize_snapshot(
        _snapshot([replay, _event(source="interoception", type_="interoception.report", eid="e_interoception")])
    )
    assert "SECRET" not in text
    assert "episodic_memory:episodic_memory.replay=<replay of abc123>" in text
    assert "interoception:interoception.report" in text


@pytest.mark.asyncio
async def test_no_cue_no_recall(bus: AsyncBus):
    # Scenario: a broadcast with no meaningful cue -> no recall (and no store).
    # _serialize_snapshot returns "" only when there are no pieces; we force an
    # empty serialization via a snapshot whose serialization is empty.
    episodic_memory = await _new_episodic_memory(bus, recall_cooldown_s=0.0)
    await episodic_memory.initialize()
    try:
        # Patch the cue derivation to simulate an empty cue.
        import kaine.modules.episodic_memory.module as mod

        original = mod._serialize_snapshot
        mod._serialize_snapshot = lambda snap: ""
        try:
            await episodic_memory.on_workspace(_snapshot([_event()]))
        finally:
            mod._serialize_snapshot = original
        recalls = await _recall_events(bus)
        assert recalls == []
        assert episodic_memory.core.short_term_size == 0  # empty cue -> no store either
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_recall_not_inhibition_gated(bus: AsyncBus):
    # Scenario: an inhibited cued tick (cooldown elapsed) STILL fires recall,
    # because recall is internal cognition, not an outward action.
    episodic_memory = await _new_episodic_memory(bus, recall_cooldown_s=0.0)
    await episodic_memory.initialize()
    try:
        snap = WorkspaceSnapshot(tick_index=0, selected_events=[_event()], inhibited=True)
        await episodic_memory.on_workspace(snap)
        recalls = await _recall_events(bus)
        assert len(recalls) == 1
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_store_happens_every_tick_regardless_of_recall(bus: AsyncBus):
    # Scenario: storing still happens every experiential tick, independent of
    # whether recall fired. With the subjective clock frozen, only the first
    # tick fires recall, yet every tick stores.
    frozen = EntityClock(monotonic=lambda: 1000.0)
    episodic_memory = await _new_episodic_memory(bus, capacity=8, recall_cooldown_s=5.0, entity_clock=frozen)
    await episodic_memory.initialize()
    try:
        for i in range(3):
            await episodic_memory.on_workspace(_snapshot([_event(eid=f"e{i}")]))
        assert episodic_memory.core.short_term_size == 3  # every tick stored
        recalls = await _recall_events(bus)
        assert len(recalls) == 1  # only one recall in the window
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_recall_on_workspace_false_is_store_only(bus: AsyncBus):
    # Scenario: recall_on_workspace=False -> store-only, matching prior behavior
    # (no recall, no episodic_memory.recall events, snapshot still stored each tick).
    episodic_memory = await _new_episodic_memory(bus, recall_on_workspace=False, recall_cooldown_s=0.0)
    await episodic_memory.initialize()
    try:
        await episodic_memory.on_workspace(_snapshot([_event()]))
        await episodic_memory.on_workspace(_snapshot([_event(eid="e2")]))
        recalls = await _recall_events(bus)
        assert recalls == []
        assert episodic_memory.core.short_term_size == 2
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_recall_cooldown_negative_rejected(bus: AsyncBus):
    with pytest.raises(ValueError):
        EpisodicMemory(bus, recall_cooldown_s=-1.0)


# --- Deferred embedding (performance-test-coverage) -----------------------


@pytest.mark.asyncio
async def test_hot_path_store_never_embeds_and_recall_embeds_query_and_new_entries(bus: AsyncBus):
    """Storing into short_term never embeds; spontaneous on_workspace recall
    embeds the query plus each uncached entry once, so after 100 ticks with no
    eviction the total encode_count is 2 per tick after the first."""
    episodic_memory = await _new_episodic_memory(bus, capacity=128, recall_cooldown_s=0.0)
    await episodic_memory.initialize()
    try:
        for i in range(100):
            await episodic_memory.on_workspace(_snapshot([_event(eid=f"e{i}")]))
        assert episodic_memory.core.short_term_size == 100
        # Tick 0: empty short_term, no embedding. Ticks 1..99: one query embed
        # plus one embed for the entry stored in the previous tick.
        assert episodic_memory.core.embedder.encode_count == 2 * 99
        recalls = await _recall_events(bus)
        assert len(recalls) == 100
        # Every spontaneous recall reports the short_term collection.
        assert all(r.payload.get("collection") == "short_term" for r in recalls)
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_embedding_deferred_to_eviction(bus: AsyncBus):
    """Only when the short-term buffer overflows and a trace moves to episodic
    does the embedder run; spontaneous recall is suppressed so it does not add
    embed calls here."""
    episodic_memory = await _new_episodic_memory(bus, capacity=4, recall_cooldown_s=60.0)
    await episodic_memory.initialize()
    try:
        for i in range(6):
            await episodic_memory.on_workspace(_snapshot([_event(eid=f"e{i}")]))
        assert episodic_memory.core.short_term_size == 4
        # Two entries were evicted to episodic; each required one embed call.
        assert episodic_memory.core.embedder.encode_count == 2
        episodic = episodic_memory.core.collection_name("episodic")
        assert await episodic_memory.core.storage.count(episodic) == 2
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_explicit_episodic_recall_still_embeds(bus: AsyncBus):
    """Explicit recall against episodic (the non-hot path) still needs a vector
    and therefore still invokes the embedder."""
    episodic_memory = await _new_episodic_memory(bus, capacity=4)
    await episodic_memory.initialize()
    try:
        await episodic_memory.core.store("the cat sat on the mat", collection="episodic")
        before = episodic_memory.core.embedder.encode_count
        await episodic_memory.recall("cat", collection="episodic")
        assert episodic_memory.core.embedder.encode_count == before + 1
    finally:
        await episodic_memory.shutdown()


# --- Affect tagging (task 1.1 / 1.2) ----------------------------------------


@pytest.mark.asyncio
async def test_stored_traces_carry_affect_tag_from_affect_state(bus: AsyncBus):
    """Scenario: stored trace carries current affect — intensity + VAD from affect.state."""
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        # Simulate a affect.state arriving on the bus by directly calling the
        # internal handler (unit-style — avoids spinning up the affect module and a real bus
        # while still exercising the tagging path through the actual handler).
        from datetime import datetime, timezone

        from kaine.bus.schema import Event as BusEvent

        fake_event = BusEvent(
            source="affect",
            type="affect.state",
            payload={
                "state": {"valence": 0.5, "arousal": 0.8, "dominance": 0.2},
                "drives": {},
                "emotion": "neutral",
            },
            salience=0.1,
            timestamp=datetime.now(timezone.utc),
        )
        episodic_memory._handle_peer_event(episodic_memory._affect_stream, fake_event)

        # Cached affect should now reflect the affect module's state.
        assert episodic_memory.cached_affect is not None
        assert episodic_memory.cached_affect["intensity"] == pytest.approx(0.8)
        assert episodic_memory.cached_affect["valence"] == pytest.approx(0.5)
        assert episodic_memory.cached_affect["dominance"] == pytest.approx(0.2)

        # Now store a trace; it should receive the cached affect tag.
        await episodic_memory.on_workspace(_snapshot([_event()]))
        assert episodic_memory.core.short_term_size == 1
        stored = list(episodic_memory.core._short_term)[0]
        assert stored.affect is not None
        assert stored.affect["intensity"] == pytest.approx(0.8)
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_stored_trace_has_no_affect_tag_before_affect_state(bus: AsyncBus):
    """Without a affect.state event, stored traces have affect=None."""
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        assert episodic_memory.cached_affect is None
        await episodic_memory.on_workspace(_snapshot([_event()]))
        stored = list(episodic_memory.core._short_term)[0]
        assert stored.affect is None
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_affect_tag_updates_on_new_affect_state(bus: AsyncBus):
    """A second affect.state event replaces the cached affect."""
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        from datetime import datetime, timezone

        from kaine.bus.schema import Event as BusEvent

        def _affect_event(arousal: float, valence: float) -> BusEvent:
            return BusEvent(
                source="affect",
                type="affect.state",
                payload={
                    "state": {"valence": valence, "arousal": arousal, "dominance": 0.0},
                    "drives": {},
                    "emotion": "neutral",
                },
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            )

        episodic_memory._handle_peer_event(episodic_memory._affect_stream, _affect_event(0.3, 0.1))
        assert episodic_memory.cached_affect["intensity"] == pytest.approx(0.3)

        episodic_memory._handle_peer_event(episodic_memory._affect_stream, _affect_event(0.9, -0.5))
        assert episodic_memory.cached_affect["intensity"] == pytest.approx(0.9)
        assert episodic_memory.cached_affect["valence"] == pytest.approx(-0.5)
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_recall_affect_bias_intact(bus: AsyncBus):
    """Recall still uses alert_salience when recalled memories have high affect."""
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        await episodic_memory.core.store(
            "intense event",
            affect={"intensity": 0.9, "valence": 0.8, "dominance": 0.0},
            collection="episodic",
        )
        await episodic_memory.recall("intense event", collection="episodic")
        entries = await bus.read("episodic_memory.out", last_id="0")
        _, ev = entries[0]
        assert ev.type == "episodic_memory.recall"
        assert ev.salience == pytest.approx(episodic_memory._alert_salience)
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_sleep_owns_the_replay_window(bus: AsyncBus):
    """The sleep module opens the replay window through the episodic memory module; sleep start on the bus does not open it, and sleep completion closes it."""
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        from datetime import datetime, timezone

        from kaine.bus.schema import Event as BusEvent

        assert not episodic_memory.replay_engine.window_active

        started = BusEvent(
            source="sleep",
            type="sleep.sleep.started",
            payload={"started_at": 0.0},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        episodic_memory._handle_peer_event(episodic_memory._sleep_stream, started)
        assert not episodic_memory.replay_engine.window_active

        episodic_memory.open_replay_window()
        assert episodic_memory.replay_engine.window_active

        completed = BusEvent(
            source="sleep",
            type="sleep.sleep.completed",
            payload={},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        episodic_memory._handle_peer_event(episodic_memory._sleep_stream, completed)
        assert not episodic_memory.replay_engine.window_active

        episodic_memory.open_replay_window()
        assert episodic_memory.replay_engine.window_active
        episodic_memory.close_replay_window()
        assert not episodic_memory.replay_engine.window_active
    finally:
        await episodic_memory.shutdown()


# --- select_cross_period_traces (real episodic memory module, phase-3 gap closure) -----------


async def _episodic_memory_with_traces(
    bus: AsyncBus,
    *,
    capacity: int = 32,
    short_term_texts: list[tuple[str, float]] | None = None,
    episodic_texts: list[tuple[str, float]] | None = None,
) -> "EpisodicMemory":
    """Build an episodic memory module with pre-populated short-term and/or episodic traces.

    Each entry is ``(text, timestamp)`` so callers can spread traces across
    distinct timestamps (and therefore distinct time-window buckets).
    """

    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    # Use a controllable clock so we can pin timestamps precisely.
    clock_val: dict[str, float] = {"t": 0.0}
    core = EpisodicMemoryCore(
        embedder=emb,
        storage=storage,
        short_term_capacity=capacity,
        clock=lambda: clock_val["t"],
    )
    episodic_memory = EpisodicMemory(bus, core=core)

    for text, ts in short_term_texts or []:
        clock_val["t"] = ts
        await core.store(text, collection="short_term")

    await core.initialize()  # ensures episodic collection exists

    for text, ts in episodic_texts or []:
        clock_val["t"] = ts
        await core.store(
            text,
            payload={"timestamp": ts},
            collection="episodic",
        )

    return episodic_memory


@pytest.mark.asyncio
async def test_select_cross_period_returns_two_distinct_periods(bus: AsyncBus):
    """The real episodic memory module returns ≥2 populated period buckets when traces span two epochs."""
    # Two short-term traces early, two short-term traces late — guaranteed to
    # fall in different time-window buckets when divided into 2 periods.
    episodic_memory = await _episodic_memory_with_traces(
        bus,
        short_term_texts=[
            ("early trace alpha", 1000.0),
            ("early trace beta", 1010.0),
            ("late trace gamma", 2000.0),
            ("late trace delta", 2010.0),
        ],
    )
    by_period = await episodic_memory.select_cross_period_traces(periods=2, per_period=3)

    # Must have at least 2 populated buckets.
    populated = [p for p, traces in by_period.items() if traces]
    assert len(populated) >= 2, f"Expected ≥2 periods, got {populated!r}"

    # Each returned trace dict carries the expected keys.
    for traces in by_period.values():
        for trace in traces:
            assert "point_id" in trace
            assert "text" in trace


@pytest.mark.asyncio
async def test_select_cross_period_per_period_caps_samples(bus: AsyncBus):
    """per_period=1 returns at most 1 trace per bucket."""
    episodic_memory = await _episodic_memory_with_traces(
        bus,
        short_term_texts=[
            ("old a", 100.0),
            ("old b", 110.0),
            ("old c", 120.0),
            ("new a", 900.0),
            ("new b", 910.0),
            ("new c", 920.0),
        ],
    )
    by_period = await episodic_memory.select_cross_period_traces(periods=2, per_period=1)
    for period, traces in by_period.items():
        assert len(traces) <= 1, f"period {period!r} has {len(traces)} traces (expected ≤1)"


@pytest.mark.asyncio
async def test_select_cross_period_episodic_included(bus: AsyncBus):
    """Episodic storage points are included alongside short-term traces."""
    episodic_memory = await _episodic_memory_with_traces(
        bus,
        short_term_texts=[("short trace", 500.0)],
        episodic_texts=[("episodic trace", 1500.0)],
    )
    by_period = await episodic_memory.select_cross_period_traces(periods=2, per_period=5)
    all_point_ids = [t["point_id"] for traces in by_period.values() for t in traces]
    # At least one short_term: prefixed and at least one bare UUID (episodic).
    has_short_term = any(pid.startswith("short_term:") for pid in all_point_ids)
    has_episodic = any(not pid.startswith("short_term:") for pid in all_point_ids)
    assert has_short_term, "Expected short-term traces in result"
    assert has_episodic, "Expected episodic traces in result"


@pytest.mark.asyncio
async def test_select_cross_period_empty_returns_empty(bus: AsyncBus):
    """No traces → empty dict (no crash; phase 3 handles it gracefully)."""
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(embedder=emb, storage=storage)
    await core.initialize()
    episodic_memory = EpisodicMemory(bus, core=core)
    result = await episodic_memory.select_cross_period_traces(periods=2, per_period=3)
    assert result == {}


@pytest.mark.asyncio
async def test_select_cross_period_all_same_timestamp(bus: AsyncBus):
    """All traces at the same timestamp → only period_0 populated (degenerate case)."""
    episodic_memory = await _episodic_memory_with_traces(
        bus,
        short_term_texts=[
            ("a", 1000.0),
            ("b", 1000.0),
            ("c", 1000.0),
        ],
    )
    by_period = await episodic_memory.select_cross_period_traces(periods=3, per_period=2)
    # Degenerate: all fall in bucket 0.
    assert "period_0" in by_period
    assert all(k == "period_0" for k in by_period)


# --- Phase-3 driven by REAL episodic memory module (not a fake) ------------------------------


@pytest.mark.asyncio
async def test_phase3_with_real_episodic_memory_spans_two_periods(bus: AsyncBus):
    """Phase 3 driven by the real episodic memory module yields a batch spanning ≥2 periods.

    This is the load-bearing integration test: ensures the spec requirement
    'traces from at least two distinct memory periods appear in the same
    replay batch' is satisfied by the real episodic memory module's implementation, not just
    by a duck-typed fake.
    """
    from kaine.modules.sleep.phases import associative_replay

    episodic_memory = await _episodic_memory_with_traces(
        bus,
        short_term_texts=[
            ("early memory one", 1000.0),
            ("early memory two", 1020.0),
            ("recent memory one", 5000.0),
            ("recent memory two", 5020.0),
        ],
    )

    result = await associative_replay(
        enabled=True,
        episodic_memory=episodic_memory,  # type: ignore[arg-type]  # real episodic memory module satisfies the duck-type
        world_model=None,
        periods=2,
        per_period=3,
    )

    assert result.success is True, f"phase 3 failed: {result.error}"
    assert result.metadata["distinct_periods"] >= 2, (
        f"Expected ≥2 distinct periods from real Episodic memory, "
        f"got {result.metadata['distinct_periods']}: {result.metadata['periods_selected']}"
    )
    assert result.metadata["cross_period_traces"] >= 2
