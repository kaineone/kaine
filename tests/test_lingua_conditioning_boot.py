# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot-seam acceptance for conditioning the language organ.

These exercise the wiring an operator boots for the live validation of the
``condition-language-organ`` change (tasks 6.1-6.3) — but with fakes only: no
entity, no GPU, no network. They cover the seam that the module/assembler unit
tests do not:

  - ``make_lingua`` threads the ``[lingua]`` persona / context-budget config
    into the ``ContextAssembler`` (tasks 3.4, 4.1, 4.2).
  - ``_wire_lingua_self_model`` seeds the first-person persona from the Eidolon
    self-model, and is a safe no-op when Eidolon is absent (task 3.4).

The offline analogue of operator step 6.1 ("the captured prompt contains the
conscious coalition") is asserted here: a wired ``speak`` produces a request
whose ``system`` carries the persona and whose ``prompt`` carries the rendered
coalition plus the triggering input. The live boot itself stays
operator-supervised (section 6); this only guards the wiring it depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot import _wire_lingua_self_model, make_lingua
from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.lingua import FakeChatClient
from kaine.modules.lingua.context import AWARENESS_HEADING
from kaine.modules.registry import ModuleRegistry


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _snap(triples):
    """triples: list of (entry_id, Event, salience)."""
    selected = [(eid, ev) for eid, ev, _ in triples]
    scores = {eid: s for eid, _, s in triples}
    return WorkspaceSnapshot(
        tick_index=1, selected_events=selected, salience_scores=scores
    )


def _soma_event(wellness: float = 0.5):
    return Event(
        source="soma",
        type="soma.report",
        payload={"wellness": wellness, "alerts": []},
        salience=0.9,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )


def _lingua(bus: AsyncBus, tmp_path, **extra):
    """Build Lingua through the real boot factory, then swap in a fake chat
    client so we can capture the assembled request with no network/model."""
    section = {"intent_log_path": str(tmp_path / "intent.jsonl")}
    section.update(extra)
    lingua = make_lingua(bus, section)
    lingua._chat_client = FakeChatClient(responses=["ok"])
    return lingua


class _FakeEidolonModel:
    def __init__(self, *, name=None, values=None, norms=None):
        self.name = name
        self.values = values or []
        self.behavioral_norms = norms or []
        self.personality_baseline: dict = {}


class _FakeEidolon:
    """Minimal Eidolon stand-in: the registry only reads ``.name`` and the
    wiring only reads ``.model`` (values / norms / name / baseline)."""

    def __init__(self, model: _FakeEidolonModel):
        self.name = "eidolon"
        self.model = model


@pytest.mark.asyncio
async def test_make_lingua_threads_persona_and_budget_config(bus, tmp_path):
    """The [lingua] persona/context keys reach the assembler: the captured
    request carries the configured name + persona text and the rendered
    coalition, not the bare utterance (task 4.2 + 6.1 offline analogue)."""
    lingua = _lingua(
        bus,
        tmp_path,
        persona_name="Testa",
        persona_external="CUSTOM-EXTERNAL-PERSONA.",
        context_max_events=3,
        context_char_budget=500,
    )
    snap = _snap([("e1", _soma_event(), 0.9)])
    await lingua.speak("hello there", snapshot=snap)

    req = lingua.chat_client.requests[-1]
    assert "Testa" in req.system
    assert "CUSTOM-EXTERNAL-PERSONA." in req.system
    # Working memory (the conscious coalition) is rendered into the prompt...
    assert AWARENESS_HEADING in req.prompt
    assert "Soma reports" in req.prompt
    # ...alongside the triggering input, and it is not the bare utterance alone.
    assert "hello there" in req.prompt
    assert req.prompt.strip() != "hello there"


@pytest.mark.asyncio
async def test_context_max_events_config_bounds_the_coalition(bus, tmp_path):
    """context_max_events threaded through make_lingua actually caps rendering:
    with a cap of 1, only the highest-salience event survives."""
    lingua = _lingua(bus, tmp_path, context_max_events=1)
    high = Event(
        source="soma", type="soma.report",
        payload={"wellness": 0.5, "alerts": []},
        salience=0.95, timestamp=datetime.now(timezone.utc), causal_parent=None,
    )
    low = Event(
        source="audition", type="audition.transcription",
        payload={"text": "a low-salience aside"},
        salience=0.10, timestamp=datetime.now(timezone.utc), causal_parent=None,
    )
    snap = _snap([("hi", high, 0.95), ("lo", low, 0.10)])
    await lingua.speak("status?", snapshot=snap)

    req = lingua.chat_client.requests[-1]
    assert "Soma reports" in req.prompt          # highest salience kept
    assert "a low-salience aside" not in req.prompt  # dropped by the cap of 1


@pytest.mark.asyncio
async def test_lingua_persona_seeds_from_bus_mediated_self_model(bus, tmp_path):
    """Lingua seeds its first-person persona from the Eidolon self-model it caches
    off the bus, so a populated self-model surfaces in the system prompt (task 3.4).

    The distributed-deployment change made ``_wire_lingua_self_model`` a documented
    no-op seam: the self-model now reaches Lingua as an ``eidolon.self_model``
    snapshot on ``eidolon.out``, cached by ``_self_model_cache_loop`` into
    ``_bus_self_model`` (the bus read itself is covered by
    ``test_lingua_bus_self_model.py``). Here we assert that the cached model
    surfaces in the persona — the behavior the old in-process wiring used to test."""
    lingua = _lingua(bus, tmp_path)
    # The snapshot _self_model_cache_loop stores from an eidolon.self_model event.
    lingua._bus_self_model = {"values": ["honesty", "curiosity"]}
    await lingua.speak("hi", snapshot=None)

    req = lingua.chat_client.requests[-1]
    assert "honesty" in req.system and "curiosity" in req.system


@pytest.mark.asyncio
async def test_wire_lingua_self_model_noop_without_eidolon(bus, tmp_path):
    """With Eidolon absent (all-modules-off shipped config, fresh start) the
    wiring is a no-op and the persona falls back to the minimal invariant —
    still a non-empty, first-person system prompt (task 3.4 / fresh start)."""
    lingua = _lingua(bus, tmp_path)
    registry = ModuleRegistry()
    registry.register(lingua)

    _wire_lingua_self_model(registry)  # eidolon not registered → safe no-op
    await lingua.speak("hi", snapshot=None)

    req = lingua.chat_client.requests[-1]
    assert req.system  # non-empty minimal invariant
    assert "KAINE entity" in req.system


@pytest.mark.asyncio
async def test_wire_lingua_fresh_start_empty_model_minimal_persona(bus, tmp_path):
    """Eidolon present but empty (no name/values/norms accumulated): the persona
    stays minimal — non-empty invariant, no invented identity clause."""
    lingua = _lingua(bus, tmp_path)
    eidolon = _FakeEidolon(_FakeEidolonModel())  # empty model
    registry = ModuleRegistry()
    registry.register(lingua)
    registry.register(eidolon)

    _wire_lingua_self_model(registry)
    await lingua.speak("hi", snapshot=None)

    req = lingua.chat_client.requests[-1]
    assert req.system  # non-empty
    assert "You value" not in req.system  # nothing accumulated to seed from
