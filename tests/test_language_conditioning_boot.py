# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot-seam acceptance for conditioning the language organ.

These exercise the wiring an operator boots for the live validation of the
``condition-language-organ`` change (tasks 6.1-6.3) — but with fakes only: no
entity, no GPU, no network. They cover the seam that the module/assembler unit
tests do not:

  - ``make_language`` threads the ``[language]`` persona / context-budget config
    into the ``ContextAssembler`` (tasks 3.4, 4.1, 4.2).
  - ``_wire_language_self_model`` seeds the first-person persona from the self-model module
    self-model, and is a safe no-op when the self-model module is absent (task 3.4).

The offline analogue of operator step 6.1 ("the captured prompt contains the
conscious coalition") is asserted here: a wired ``speak`` produces a request
whose ``system`` carries the persona and whose ``prompt`` carries the rendered
coalition plus the triggering input. The live boot itself stays
operator-supervised (section 6); this only guards the wiring it depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot import _wire_language_self_model, make_language
from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.language import FakeChatClient
from kaine.modules.language.context import (
    AWARENESS_HEADING,
    HEARD_POINTER_INPUT,
)
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


def _interoception_event(wellness: float = 0.5):
    return Event(
        source="interoception",
        type="interoception.report",
        payload={"wellness": wellness, "alerts": []},
        salience=0.9,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )


def _language(bus: AsyncBus, tmp_path, **extra):
    """Build the language module through the real boot factory, then swap in a fake chat
    client so we can capture the assembled request with no network/model."""
    section = {"intent_log_path": str(tmp_path / "intent.jsonl")}
    section.update(extra)
    language = make_language(bus, section)
    language._chat_client = FakeChatClient(responses=["ok"])
    return language


class _FakeSelfModelModel:
    def __init__(self, *, name=None, values=None, norms=None):
        self.name = name
        self.values = values or []
        self.behavioral_norms = norms or []
        self.personality_baseline: dict = {}


class _FakeSelfModel:
    """Minimal self-model module stand-in: the registry only reads ``.name`` and the
    wiring only reads ``.model`` (values / norms / name / baseline)."""

    def __init__(self, model: _FakeSelfModelModel):
        self.name = "self_model"
        self.model = model


@pytest.mark.asyncio
async def test_make_language_threads_persona_and_budget_config(bus, tmp_path):
    """The [language] persona/context keys reach the assembler: the captured
    request carries the configured name + persona text and the rendered
    coalition, not the bare utterance (task 4.2 + 6.1 offline analogue)."""
    language = _language(
        bus,
        tmp_path,
        persona_name="Testa",
        persona_external="CUSTOM-EXTERNAL-PERSONA.",
        context_max_events=3,
        context_char_budget=500,
    )
    snap = _snap([("e1", _interoception_event(), 0.9)])
    await language.speak("hello there", snapshot=snap)

    req = language.chat_client.requests[-1]
    assert "Testa" in req.system
    assert "CUSTOM-EXTERNAL-PERSONA." in req.system
    # Working memory (the conscious coalition) is rendered into the prompt...
    assert AWARENESS_HEADING in req.prompt
    assert "Interoception reports" in req.prompt
    # ...and the heard trigger reaches the model as a separate attributed user turn,
    # not inside the entity's own notes.
    assert "hello there" in req.user_turn
    assert "hello there" not in req.prompt
    assert HEARD_POINTER_INPUT in req.prompt
    assert req.prompt.strip() != "hello there"


@pytest.mark.asyncio
async def test_context_max_events_config_bounds_the_coalition(bus, tmp_path):
    """context_max_events threaded through make_language actually caps rendering:
    with a cap of 1, only the highest-salience event survives."""
    language = _language(bus, tmp_path, context_max_events=1)
    high = Event(
        source="interoception", type="interoception.report",
        payload={"wellness": 0.5, "alerts": []},
        salience=0.95, timestamp=datetime.now(timezone.utc), causal_parent=None,
    )
    low = Event(
        source="audition", type="audition.transcription",
        payload={"text": "a low-salience aside"},
        salience=0.10, timestamp=datetime.now(timezone.utc), causal_parent=None,
    )
    snap = _snap([("hi", high, 0.95), ("lo", low, 0.10)])
    await language.speak("status?", snapshot=snap)

    req = language.chat_client.requests[-1]
    assert "Interoception reports" in req.prompt          # highest salience kept
    assert "a low-salience aside" not in req.prompt  # dropped by the cap of 1


@pytest.mark.asyncio
async def test_language_persona_seeds_from_bus_mediated_self_model(bus, tmp_path):
    """The language module seeds its first-person persona from the self-model it caches
    off the bus, so a populated self-model surfaces in the system prompt (task 3.4).

    The distributed-deployment change made ``_wire_language_self_model`` a documented
    no-op seam: the self-model now reaches the language module as an ``self_model.self_model``
    snapshot on ``self_model.out``, cached by ``_self_model_cache_loop`` into
    ``_bus_self_model`` (the bus read itself is covered by
    ``test_language_bus_self_model.py``). Here we assert that the cached model
    surfaces in the persona — the behavior the old in-process wiring used to test."""
    language = _language(bus, tmp_path)
    # The snapshot _self_model_cache_loop stores from an self_model.self_model event.
    language._bus_self_model = {"values": ["honesty", "curiosity"]}
    await language.speak("hi", snapshot=None)

    req = language.chat_client.requests[-1]
    assert "honesty" in req.system and "curiosity" in req.system


@pytest.mark.asyncio
async def test_wire_language_self_model_noop_without_self_model(bus, tmp_path):
    """With the self-model module absent (all-modules-off shipped config, fresh start) the
    wiring is a no-op and the persona falls back to the minimal invariant —
    still a non-empty, first-person system prompt (task 3.4 / fresh start)."""
    language = _language(bus, tmp_path)
    registry = ModuleRegistry()
    registry.register(language)

    _wire_language_self_model(registry)  # the self-model module not registered → safe no-op
    await language.speak("hi", snapshot=None)

    req = language.chat_client.requests[-1]
    assert req.system  # non-empty minimal invariant
    assert "I am this entity" in req.system


@pytest.mark.asyncio
async def test_wire_language_fresh_start_empty_model_minimal_persona(bus, tmp_path):
    """The self-model module present but empty (no name/values/norms accumulated): the persona
    stays minimal — non-empty invariant, no invented identity clause."""
    language = _language(bus, tmp_path)
    self_model = _FakeSelfModel(_FakeSelfModelModel())  # empty model
    registry = ModuleRegistry()
    registry.register(language)
    registry.register(self_model)

    _wire_language_self_model(registry)
    await language.speak("hi", snapshot=None)

    req = language.chat_client.requests[-1]
    assert req.system  # non-empty
    assert "You value" not in req.system  # nothing accumulated to seed from
