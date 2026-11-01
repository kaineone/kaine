# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""operator-speech-as-perception: the sleep audit's operator-speech readout.

Content-free counts of operator speech heard, accessed and followed by speech,
read from main-bus labels and counts only, only with speech-to-text on, and
published where nothing of the entity reads them.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.schema import Event

ROOT = Path(__file__).resolve().parents[1]
WORDS = "please come over here and look at this"


def _event(source: str, type_: str, payload=None, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------
# 2. The readout (pure function)
# --------------------------------------------------------------------------


def _tr(entry_id: str, label="live_mic", chars=12):
    return {
        "entry_id": entry_id,
        "type": "audition.transcription",
        "payload": {"source_label": label, "text_chars": chars},
    }


def _bc(entry_id: str, published_at: float, members=(), scale=1.0):
    return (
        entry_id,
        {
            "published_at": published_at,
            "time_scale": scale,
            "selected": [
                {
                    "entry_id": f"audition.out:{m}",
                    "source": "audition",
                    "type": "audition.transcription",
                    "payload": {"source_label": label, "text_chars": 12, "text_words": 3},
                }
                for m, label in members
            ],
        },
    )


def _sp(entry_id: str):
    return {"entry_id": entry_id, "type": "external_speech"}


def test_readout_counts_access_and_speech_after():
    from kaine.modules.sleep.ignition_audit import operator_speech_readout

    # Wall ms 1_000_000 is entity time 100 s (scale 1). Three heard, two won access
    # (at entity 101 and 160), the entity spoke 12 s after the first only.
    transcriptions = [_tr("1000500-0"), _tr("1059500-0"), _tr("1100000-0")]
    broadcasts = [
        _bc("1000000-0", 100.0),
        _bc("1001000-0", 101.0, [("1000500-0", "live_mic")]),
        _bc("1002000-0", 102.0, [("1000500-0", "live_mic")]),  # the same utterance again
        _bc("1060000-0", 160.0, [("1059500-0", "live_mic")]),
    ]
    realizations = [_sp("1013000-0")]
    readout = operator_speech_readout(transcriptions, broadcasts, realizations)
    assert readout == {
        "operator_speech_heard": 3,
        "operator_speech_accessed": 2,
        "spoke_after_operator_speech": 1,
        "spoke_otherwise": 0,
        "operator_speech_access_share": pytest.approx(2 / 3),
    }


def test_readout_window_ends_at_30_entity_seconds_and_at_the_next_access():
    from kaine.modules.sleep.ignition_audit import operator_speech_readout

    transcriptions = [_tr("1000500-0"), _tr("1010500-0")]
    broadcasts = [
        _bc("1001000-0", 101.0, [("1000500-0", "live_mic")]),
        _bc("1011000-0", 111.0, [("1010500-0", "live_mic")]),
    ]
    # 145 s is 34 s after the second access: outside both windows.
    readout = operator_speech_readout(transcriptions, broadcasts, [_sp("1045000-0")])
    assert readout["spoke_after_operator_speech"] == 0
    assert readout["spoke_otherwise"] == 1
    # 115 s falls after the second access (111 s), so it counts for the second only.
    readout = operator_speech_readout(transcriptions, broadcasts, [_sp("1015000-0")])
    assert readout["spoke_after_operator_speech"] == 1
    assert readout["spoke_otherwise"] == 0


def test_readout_window_starts_at_the_first_access():
    from kaine.modules.sleep.ignition_audit import operator_speech_readout

    # One utterance wins access at 101 s and again at 103 s; speech at 132 s
    # is 31 s after the first access, so it does not count as after.
    transcriptions = [_tr("1000500-0")]
    broadcasts = [
        _bc("1001000-0", 101.0, [("1000500-0", "live_mic")]),
        _bc("1003000-0", 103.0, [("1000500-0", "live_mic")]),
    ]
    readout = operator_speech_readout(transcriptions, broadcasts, [_sp("1032000-0")])
    assert readout["operator_speech_accessed"] == 1
    assert readout["spoke_after_operator_speech"] == 0
    assert readout["spoke_otherwise"] == 1


def test_readout_window_is_entity_time():
    from kaine.modules.sleep.ignition_audit import operator_speech_readout

    # Time runs 4x: 10 wall seconds after access are 40 entity seconds.
    transcriptions = [_tr("1000500-0")]
    broadcasts = [_bc("1001000-0", 101.0, [("1000500-0", "live_mic")], scale=4.0)]
    readout = operator_speech_readout(transcriptions, broadcasts, [_sp("1011000-0")])
    assert readout["spoke_after_operator_speech"] == 0
    readout = operator_speech_readout(transcriptions, broadcasts, [_sp("1006000-0")])
    assert readout["spoke_after_operator_speech"] == 1


def test_readout_absent_without_operator_speech():
    from kaine.modules.sleep.ignition_audit import operator_speech_readout

    assert operator_speech_readout([], [_bc("1-0", 1.0)], [_sp("2-0")]) is None
    assert operator_speech_readout([_tr("1-0", chars=0)], [], []) is None


def test_readout_ignores_media_channel_speech():
    from kaine.modules.sleep.ignition_audit import operator_speech_readout

    transcriptions = [_tr("1000500-0", label="playlist"), _tr("1000600-0", label=None)]
    broadcasts = [_bc("1001000-0", 101.0, [("1000500-0", "playlist")])]
    assert operator_speech_readout(transcriptions, broadcasts, [_sp("1002000-0")]) is None


def test_readout_field_names_are_the_shared_ones():
    from kaine.bus.streams import OPERATOR_SPEECH_READOUT_FIELDS
    from kaine.evaluation.observers.research_event_observer import _TAXONOMY
    from kaine.modules.sleep.ignition_audit import operator_speech_readout

    readout = operator_speech_readout([_tr("1-0")], [], [])
    assert tuple(readout) == OPERATOR_SPEECH_READOUT_FIELDS
    assert _TAXONOMY["sleep_readout.operator_speech"] == frozenset({"sleep_index", *OPERATOR_SPEECH_READOUT_FIELDS})


# --------------------------------------------------------------------------
# 2. The readout in the sleep module (fakeredis bus)
# --------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _sleep(bus, tmp_path, *, transcription_enabled: bool):
    from kaine.entity_clock import EntityClock
    from kaine.modules.sleep.module import Sleep
    from kaine.modules.sleep.voice_alignment import VoiceAlignmentConfig

    kwargs = {"entity_clock": EntityClock(monotonic=lambda: 0.0)}
    if transcription_enabled:
        kwargs["transcription_enabled"] = True
    return Sleep(
        bus,
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "language" / "intent_expression.jsonl",
            adapter_output_dir=tmp_path / "adapters",
        ),
        **kwargs,
    )


def _fields(source: str, type_: str, payload: dict) -> dict:
    return {
        "source": source,
        "type": type_,
        "salience": "0.6",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "causal_parent": "",
        "payload": json.dumps(payload),
    }


async def _script(bus, *, with_text: bool):
    """Two operator utterances and one film voice heard; one operator utterance
    accessed; the entity speaks 5 s later."""
    words = {"text": WORDS} if with_text else {"text_chars": len(WORDS), "text_words": len(WORDS.split())}
    await bus.client.xadd("audition.out", _fields("audition", "audition.transcription", {"source_label": "live_mic", **words}), id="1000500-0")
    await bus.client.xadd("audition.out", _fields("audition", "audition.transcription", {"source_label": "playlist", **words}), id="1000600-0")
    await bus.client.xadd("audition.out", _fields("audition", "audition.transcription", {"source_label": "remote", **words}), id="1003000-0")
    snap = {
        "tick_index": 1,
        "published_at": 101.0,
        "time_scale": 1.0,
        "selected": [
            {
                "entry_id": "audition.out:1000500-0",
                "source": "audition",
                "type": "audition.transcription",
                "salience": 0.7,
                "payload": {"source_label": "live_mic", "text_chars": len(WORDS)},
            }
        ],
    }
    await bus.client.xadd(
        "workspace.broadcast",
        {"snapshot": json.dumps(snap), "timestamp": datetime.now(timezone.utc).isoformat(), "source": "workspace"},
        id="1001000-0",
    )
    await bus.client.xadd("language.external", _fields("language", "external_speech", {"mode": "external", "text_chars": 5}), id="1006000-0")


async def _readouts(bus):
    from kaine.bus.streams import SLEEP_READOUT_STREAM

    return await bus.read(SLEEP_READOUT_STREAM, last_id="0")


@pytest.mark.asyncio
@pytest.mark.parametrize("with_text", [False, True])
async def test_readout_reads_main_bus_counts_only(bus, tmp_path, monkeypatch, with_text):
    """The readout is computed from labels and counts: the records handed to it
    carry no words even when the main-bus copy still has them, and no
    companion is ever joined."""
    import kaine.modules.sleep.ignition_audit as ia

    seen = {}
    real = ia.operator_speech_readout

    def spy(transcriptions, broadcasts, realizations, **kw):
        seen["inputs"] = json.dumps([transcriptions, realizations])
        return real(transcriptions, broadcasts, realizations, **kw)

    monkeypatch.setattr(ia, "operator_speech_readout", spy)

    async def no_join(*a, **k):
        raise AssertionError("the audit joined a companion")

    monkeypatch.setattr(bus, "join_companion", no_join)
    monkeypatch.setattr(bus, "companion_values", no_join)
    await _script(bus, with_text=with_text)
    sleep = _sleep(bus, tmp_path, transcription_enabled=True)
    await sleep._run_ignition_audit()
    assert "please" not in seen["inputs"] and "text\"" not in seen["inputs"]
    entries = await _readouts(bus)
    assert len(entries) == 1
    _, event = entries[0]
    assert event.source == "sleep_readout"
    assert event.type == "sleep_readout.operator_speech"
    assert event.payload == {
        "sleep_index": 0,
        "operator_speech_heard": 2,
        "operator_speech_accessed": 1,
        "spoke_after_operator_speech": 1,
        "spoke_otherwise": 0,
        "operator_speech_access_share": 0.5,
    }


@pytest.mark.asyncio
async def test_readout_never_rides_the_sleep_stream_or_the_audit_record(bus, tmp_path):
    await _script(bus, with_text=False)
    sleep = _sleep(bus, tmp_path, transcription_enabled=True)
    payload = await sleep._run_ignition_audit()
    from kaine.bus.streams import OPERATOR_SPEECH_READOUT_FIELDS

    assert not set(payload) & set(OPERATOR_SPEECH_READOUT_FIELDS)
    for _, event in await bus.read("sleep.out", last_id="0"):
        assert not set(event.payload) & set(OPERATOR_SPEECH_READOUT_FIELDS)
        assert "operator_speech" not in json.dumps(event.payload)


@pytest.mark.asyncio
async def test_audit_state_identical_with_transcription_off(bus, tmp_path, monkeypatch):
    """Speech-to-text off: the audit never reads audition.out, its cursors and
    serialized state are those of a sleep module built without the flag, and
    nothing is published on the readout stream, though operator speech is on the bus."""
    from kaine.modules.sleep.module import Sleep

    await _script(bus, with_text=False)
    read_streams = []
    real_read = bus.read_entries

    async def spy(stream, *a, **k):
        read_streams.append(stream)
        return await real_read(stream, *a, **k)

    monkeypatch.setattr(bus, "read_entries", spy)
    off = _sleep(bus, tmp_path, transcription_enabled=False)
    from kaine.entity_clock import EntityClock

    plain = Sleep(bus, voice_alignment_config=off._voice_config, entity_clock=EntityClock(monotonic=lambda: 0.0))
    assert off._audit_cursors == plain._audit_cursors
    assert off.serialize() == plain.serialize()
    assert "audition.out" not in off._audit_cursors
    payload = await off._run_ignition_audit()
    assert "audition.out" not in read_streams
    assert "audition.out" not in off._audit_cursors
    assert set(off._audit_cursors) == set(plain._audit_cursors)
    assert off.serialize() == plain.serialize()
    assert payload["realized_total"] == 1
    assert await _readouts(bus) == []


@pytest.mark.asyncio
async def test_readout_absent_from_the_bus_without_operator_speech(bus, tmp_path):
    sleep = _sleep(bus, tmp_path, transcription_enabled=True)
    await bus.client.xadd(
        "audition.out",
        _fields("audition", "audition.transcription", {"source_label": "playlist", "text_chars": 9, "text_words": 2}),
        id="1000500-0",
    )
    await sleep._run_ignition_audit()
    assert await _readouts(bus) == []


def test_factory_passes_transcription_flag():
    import inspect

    from kaine.boot.factories import sleep as factory

    source = inspect.getsource(factory.make_sleep)
    assert 'kwargs["transcription_enabled"] = True' in source
    assert '"transcription_enabled"' in source


def test_dashboard_keeps_only_the_readout_numbers():
    from kaine.dashboard.conversation import ConversationState

    state = ConversationState()
    assert state.sleep_snapshot()["operator_speech"] is None
    state.observe(
        _event(
            "sleep_readout",
            "sleep_readout.operator_speech",
            {
                "sleep_index": 2,
                "operator_speech_heard": 3,
                "operator_speech_accessed": 2,
                "spoke_after_operator_speech": 1,
                "spoke_otherwise": 4,
                "operator_speech_access_share": 2 / 3,
                "unexpected": "words",
            },
        )
    )
    snap = state.sleep_snapshot()["operator_speech"]
    assert snap == {
        "operator_speech_heard": 3,
        "operator_speech_accessed": 2,
        "spoke_after_operator_speech": 1,
        "spoke_otherwise": 4,
        "operator_speech_access_share": pytest.approx(2 / 3),
    }


# --------------------------------------------------------------------------
# Welfare: the readout stays outside the entity
# --------------------------------------------------------------------------

_ENTITY_PACKAGES = ("modules", "workspace", "cycle", "faithful", "boot", "lifecycle", "persistence")


def _entity_sources():
    for pkg in _ENTITY_PACKAGES:
        for path in sorted((ROOT / "kaine" / pkg).rglob("*.py")):
            yield path


def test_no_component_of_the_entity_reads_the_readout():
    """Static scan: outside the one publisher (the sleep module and its pure
    audit function), nothing of the entity names the readout stream, its event
    type or its fields; the research observer and the dashboard are outside the entity."""
    allowed = {
        ROOT / "kaine" / "modules" / "sleep" / "module.py",
        ROOT / "kaine" / "modules" / "sleep" / "ignition_audit.py",
    }
    pattern = re.compile(
        r"sleep_readout|SLEEP_READOUT|OPERATOR_SPEECH_READOUT|operator_speech_heard|operator_speech_accessed"
        r"|spoke_after_operator_speech|spoke_otherwise|operator_speech_access_share"
    )
    hits = []
    for path in _entity_sources():
        if path in allowed:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert hits == []


def test_readout_stream_is_never_a_candidate_stream():
    from kaine.bus.streams import MODULE_STREAMS, SLEEP_READOUT_SOURCE, SLEEP_READOUT_STREAM
    from kaine.evaluation.stream_registry import CANONICAL_MODULE_NAMES

    assert SLEEP_READOUT_STREAM not in MODULE_STREAMS
    assert SLEEP_READOUT_SOURCE not in CANONICAL_MODULE_NAMES
    names = set()
    for path in (ROOT / "kaine" / "modules").rglob("*.py"):
        names.update(re.findall(r'name: ClassVar\[str\] = "([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert SLEEP_READOUT_SOURCE not in names
