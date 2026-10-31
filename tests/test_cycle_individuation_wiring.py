# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import tomllib
from pathlib import Path

from kaine.cycle.__main__ import (
    _compose_maturation_hooks,
    _individuation_refusal,
    _run_individuation,
)
from kaine.cycle.individuation_runtime import DEFAULT_DISCLOSURE, IndividuationConfig
from kaine.evaluation.observers.research_event_observer import _TAXONOMY


def test_individuation_refusal_disabled_by_default():
    cfg, reason = _individuation_refusal({})
    assert cfg is not None
    assert cfg.enabled is False
    assert reason is None


def test_individuation_refusal_missing_self_model():
    cfg, reason = _individuation_refusal(
        {"individuation": {"enabled": True}, "modules": {"language": True}}
    )
    assert cfg is not None
    assert reason is None

    _, reason = _individuation_refusal(
        {"individuation": {"enabled": True}, "modules": {"self_model": True}}
    )
    assert reason is not None
    assert "[modules].language" in reason
    assert "self_model" not in reason


def test_individuation_refusal_unknown_key():
    _, reason = _individuation_refusal({"individuation": {"bogus": 1}})
    assert reason is not None
    assert reason.startswith("[individuation]:")


def test_individuation_refusal_runnable():
    cfg, reason = _individuation_refusal(
        {
            "individuation": {"enabled": True},
            "modules": {"language": True, "self_model": True},
        }
    )
    assert cfg is not None
    assert cfg.enabled is True
    assert reason is None


def test_shipped_config_parses():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "config" / "kaine.toml"
    with config_path.open("rb") as f:
        data = tomllib.load(f)

    section = data["individuation"]
    cfg = IndividuationConfig.from_dict(section)

    assert cfg.enabled is False
    assert cfg.disclosure == DEFAULT_DISCLOSURE
    # from_dict raises on unknown keys, so reaching this point means every key
    # in the shipped section is accepted.


def test_compose_maturation_hooks_empty_and_continues():
    assert _compose_maturation_hooks(None, None) is None

    calls = []

    def bad_hook():
        raise RuntimeError("boom")

    def good_hook():
        calls.append("good")

    composed = _compose_maturation_hooks(bad_hook, good_hook)
    assert composed is not None
    composed()
    assert calls == ["good"]


class FakeRuntime:
    def __init__(self, start_ok: bool = True):
        self.start_ok = start_ok
        self.run_called = False
        self.run_event = None

    async def start(self):
        if not self.start_ok:
            raise RuntimeError("start failed")

    async def run(self, stop_event: asyncio.Event):
        self.run_called = True
        self.run_event = stop_event


async def test_run_individuation_start_failure_stops_cycle():
    stop = asyncio.Event()
    runtime = FakeRuntime(start_ok=False)
    await _run_individuation(runtime, stop)
    assert stop.is_set()
    assert runtime.run_called is False


async def test_run_individuation_runs_until_stop():
    stop = asyncio.Event()
    runtime = FakeRuntime(start_ok=True)
    await _run_individuation(runtime, stop)
    assert runtime.run_called is True
    assert runtime.run_event is stop
    assert not stop.is_set()


def test_openai_chat_client_applies_lora():
    from kaine.modules.language.client import OpenAIChatClient

    client = OpenAIChatClient(base_url="http://127.0.0.1:1/v1")
    assert client.applies_lora is False

    client.set_lora_resolver(object())
    assert client.applies_lora is True


def test_research_observer_allow_list_contains_alert():
    assert "individuation.alert" in _TAXONOMY
    assert _TAXONOMY["individuation.alert"] == frozenset(
        {"kind", "inconclusive_since", "days", "capture_reason"}
    )


def test_research_observer_alert_copies_only_closed_labels():
    from kaine.evaluation.observers.research_event_observer import _apply_taxonomy_fields

    record = _apply_taxonomy_fields(
        "individuation.alert",
        {
            "kind": "individuation_inconclusive",
            "capture_reason": "organ_resting",
            "inconclusive_since": "2026-01-01T00:00:00+00:00",
            "days": 14.0,
            "last_reason": "no_reference",
            "reference_id": "abc",
        },
        {},
    )
    assert record == {
        "kind": "individuation_inconclusive",
        "capture_reason": "organ_resting",
        "inconclusive_since": "2026-01-01T00:00:00+00:00",
        "days": 14.0,
    }

    # Anything outside the closed sets is dropped, never copied as text.
    smuggled = _apply_taxonomy_fields(
        "individuation.alert",
        {
            "kind": "I remember the garden",
            "capture_reason": "the entity said: hello",
            "inconclusive_since": "yesterday, after it spoke",
            "days": "14",
        },
        {},
    )
    assert smuggled == {}
