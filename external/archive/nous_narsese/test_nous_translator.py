from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.modules.nous.translator import EventTranslator, Translator


def _event(source="soma", type_="wellness.update", salience=0.5, causal_parent=None) -> Event:
    return Event(
        source=source,
        type=type_,
        payload={"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
        causal_parent=causal_parent,
    )


def test_protocol_runtime_checkable():
    assert isinstance(EventTranslator(), Translator)


def test_v1_template_for_simple_event():
    t = EventTranslator()
    stmts = t.translate(_event(salience=0.7))
    assert len(stmts) == 1
    assert stmts[0] == "<soma --> [wellness_update]>. :|: %0.7;0.9%"


def test_causal_parent_adds_implication():
    t = EventTranslator()
    parent_id = "1234-0"
    stmts = t.translate(_event(causal_parent=parent_id))
    assert len(stmts) == 2
    assert stmts[0].startswith("<soma --> [wellness_update]>.")
    # Second statement is a temporal implication from the parent term to
    # the event term.
    assert " =/> " in stmts[1]
    assert "<soma --> [wellness_update]>" in stmts[1]


def test_invalid_default_confidence_rejected():
    with pytest.raises(ValueError):
        EventTranslator(default_confidence=1.5)
    with pytest.raises(ValueError):
        EventTranslator(default_confidence=-0.1)


def test_translation_is_deterministic_for_same_event():
    t = EventTranslator()
    e = _event()
    assert t.translate(e) == t.translate(e)
