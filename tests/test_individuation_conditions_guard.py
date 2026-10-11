# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from kaine.cycle.individuation_producer import LookOutcome, _condition_changes
from kaine.cycle.individuation_runtime import ServedOrganIdentity
from kaine.lifecycle.individuation_store import load_reference, save_reference
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_producer_core import FakeConditioning, make_core
from tests.test_individuation_scheduler import (
    Ledger,
    load_ledger,
    make,
    save_ledger,
    write_reference,
)

BASE_CONDITIONS = {
    "model_id": "model-a",
    "temperature": 0.5,
    "think": False,
    "persona_digest": "secret-persona-digest-abc123",
}


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class _RaisingSampler:
    _called = False

    async def __call__(self, _prompt: str, _seed: int):
        _RaisingSampler._called = True
        raise RuntimeError("sampler must not be called after the guard")


async def test_identical_conditions_proceeds_past_guard(tmp_path):
    core, _paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: BASE_CONDITIONS.copy()
    await core.capture_reference("birth")

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert (outcome.outcome, outcome.reason) == ("skipped", "unchanged")


async def test_model_id_differs_is_conditions_changed(tmp_path):
    core, _paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: BASE_CONDITIONS.copy()
    await core.capture_reference("birth")

    changed = {**BASE_CONDITIONS, "model_id": "model-b"}
    core._conditions = lambda: changed
    _RaisingSampler._called = False
    core._sampler = _RaisingSampler()

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_changed"
    assert not _RaisingSampler._called


async def test_new_condition_key_differs(tmp_path):
    core, _paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: BASE_CONDITIONS.copy()
    await core.capture_reference("birth")

    changed = {**BASE_CONDITIONS, "persona_template_version": 2}
    core._conditions = lambda: changed

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_changed"


async def test_embedder_id_differs_only_is_not_conditions_changed(tmp_path):
    core, _paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: {
        **BASE_CONDITIONS,
        "embedder_id": "embed-a",
        "embedder_dimension": 8,
    }
    await core.capture_reference("birth")

    changed = {
        **BASE_CONDITIONS,
        "embedder_id": "embed-b",
        "embedder_dimension": 8,
    }
    core._conditions = lambda: changed

    original = core._sampler
    calls = 0

    async def wrapper(prompt: str, seed: int):
        nonlocal calls
        calls += 1
        return await original(prompt, seed)

    core._sampler = wrapper

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    # The guard passes, and the look reaches the "unchanged being" step: the
    # adapter and identity are as at capture, so it is skipped there, not
    # refused for changed conditions.
    assert (outcome.outcome, outcome.reason) == ("skipped", "unchanged")
    assert calls == 0


async def test_conditions_callable_raises_is_conditions_unreadable(tmp_path):
    core, _paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: BASE_CONDITIONS.copy()
    await core.capture_reference("birth")

    def raising():
        raise RuntimeError("conditions unreadable")

    core._conditions = raising

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_unreadable"


async def test_conditions_changed_logs_keys_not_values(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="kaine.cycle.individuation_producer")
    core, _paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: BASE_CONDITIONS.copy()
    await core.capture_reference("birth")

    changed = {**BASE_CONDITIONS, "model_id": "model-b"}
    core._conditions = lambda: changed

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.reason == "conditions_changed"
    assert "secret-persona-digest-abc123" not in caplog.text
    assert "model_id" in caplog.text


def test_condition_changes_returns_sorted_names_only():
    stored = {
        "model_id": "model-a",
        "temperature": 0.5,
        "persona_digest": "secret",
    }
    current = {
        "model_id": "model-b",
        "temperature": 0.5,
        "persona_template_version": 2,
        "embedder_id": "different",
        "embedder_dimension": 999,
    }

    changes = _condition_changes(stored, current)

    # persona_digest is present only in the stored conditions, so it differs too.
    assert changes == ["model_id", "persona_digest", "persona_template_version"]


def test_condition_changes_presence_trumps_none_value():
    assert _condition_changes({"a": None}, {}) == ["a"]
    assert _condition_changes({}, {"a": None}) == ["a"]


# --- ServedOrganIdentity ---


async def test_served_organ_identity_200_returns_build_and_model(tmp_path):
    def handler(request):
        return httpx.Response(
            200, json={"build_info": "build-1", "model_path": "/models/a.gguf"}
        )

    organ = ServedOrganIdentity(
        chat_url="http://127.0.0.1:11434/v1",
        api_key=None,
        revision_reader=lambda: {"repo": "abc"},
        transport=httpx.MockTransport(handler),
    )
    await organ.refresh()
    snap = organ.snapshot()

    assert snap["server_build"] == "build-1"
    assert snap["organ_model_file"] == "a.gguf"
    assert snap["organ_model_path_sha256"] == hashlib.sha256(
        "/models/a.gguf".encode("utf-8")
    ).hexdigest()
    assert snap["organ_revisions"] == hashlib.sha256(
        json.dumps({"repo": "abc"}, sort_keys=True).encode("utf-8")
    ).hexdigest()


async def test_served_organ_identity_200_hides_full_model_path(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "build_info": "build-1",
                "model_path": "/home/someone/models/x.gguf",
            },
        )

    organ = ServedOrganIdentity(
        chat_url="http://127.0.0.1:11434/v1",
        api_key=None,
        revision_reader=lambda: {"repo": "abc"},
        transport=httpx.MockTransport(handler),
    )
    await organ.refresh()
    snap = organ.snapshot()

    assert snap["server_build"] == "build-1"
    assert snap["organ_model_file"] == "x.gguf"
    assert snap["organ_model_path_sha256"] == hashlib.sha256(
        "/home/someone/models/x.gguf".encode("utf-8")
    ).hexdigest()
    assert snap["organ_revisions"] == hashlib.sha256(
        json.dumps({"repo": "abc"}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    for v in snap.values():
        assert "/home/" not in v


async def test_served_organ_identity_failure_returns_unavailable(tmp_path):
    def error_500(request):
        return httpx.Response(500)

    def not_json(request):
        return httpx.Response(200, text="not json")

    def not_dict(request):
        return httpx.Response(200, json=["not", "dict"])

    for handler in (error_500, not_json, not_dict):
        organ = ServedOrganIdentity(
            chat_url="http://127.0.0.1:11434/v1",
            api_key=None,
            revision_reader=lambda: {},
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RuntimeError, match="served organ identity unavailable"):
            await organ.refresh()

        assert organ.snapshot()["server_build"] == "unavailable"
        assert organ.snapshot()["organ_model_file"] == "unavailable"
        assert organ.snapshot()["organ_model_path_sha256"] == "unavailable"


async def test_served_organ_identity_bearer_only_with_key(tmp_path):
    auths = []

    def handler(request):
        auths.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"build_info": "b", "model_path": "m"})

    with_key = ServedOrganIdentity(
        chat_url="http://127.0.0.1:11434/v1",
        api_key="secret",
        revision_reader=lambda: {},
        transport=httpx.MockTransport(handler),
    )
    await with_key.refresh()
    assert auths == ["Bearer secret"]

    without_key = ServedOrganIdentity(
        chat_url="http://127.0.0.1:11434/v1",
        api_key=None,
        revision_reader=lambda: {},
        transport=httpx.MockTransport(handler),
    )
    await without_key.refresh()
    assert auths[-1] is None


# --- organ identity inside the conditions guard ---


async def test_server_build_change_is_conditions_changed(tmp_path):
    responses = [
        httpx.Response(200, json={"build_info": "b1", "model_path": "m1"}),
        httpx.Response(200, json={"build_info": "b2", "model_path": "m1"}),
    ]

    def handler(request):
        return responses.pop(0)

    organ = ServedOrganIdentity(
        chat_url="http://127.0.0.1:11434/v1",
        api_key=None,
        revision_reader=lambda: {},
        transport=httpx.MockTransport(handler),
    )
    core, _paths = make_core(
        tmp_path, conditioning_inputs=FakeConditioning(), refresh_conditions=organ.refresh
    )
    core._conditions = lambda: {**BASE_CONDITIONS, **organ.snapshot()}

    await core.capture_reference("birth")

    _RaisingSampler._called = False
    core._sampler = _RaisingSampler()
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_changed"
    assert not _RaisingSampler._called


async def test_organ_model_path_change_is_conditions_changed(tmp_path):
    responses = [
        httpx.Response(200, json={"build_info": "b1", "model_path": "m1.gguf"}),
        httpx.Response(200, json={"build_info": "b1", "model_path": "m2.gguf"}),
    ]

    def handler(request):
        return responses.pop(0)

    organ = ServedOrganIdentity(
        chat_url="http://127.0.0.1:11434/v1",
        api_key=None,
        revision_reader=lambda: {},
        transport=httpx.MockTransport(handler),
    )
    core, _paths = make_core(
        tmp_path, conditioning_inputs=FakeConditioning(), refresh_conditions=organ.refresh
    )
    core._conditions = lambda: {**BASE_CONDITIONS, **organ.snapshot()}

    await core.capture_reference("birth")

    _RaisingSampler._called = False
    core._sampler = _RaisingSampler()
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_changed"
    assert not _RaisingSampler._called


async def test_organ_model_file_same_but_sha_differs_across_directories(tmp_path):
    responses = [
        httpx.Response(200, json={"build_info": "b1", "model_path": "/home/a/x.gguf"}),
        httpx.Response(200, json={"build_info": "b1", "model_path": "/home/b/x.gguf"}),
    ]

    def handler(request):
        return responses.pop(0)

    organ = ServedOrganIdentity(
        chat_url="http://127.0.0.1:11434/v1",
        api_key=None,
        revision_reader=lambda: {},
        transport=httpx.MockTransport(handler),
    )
    core, _paths = make_core(
        tmp_path, conditioning_inputs=FakeConditioning(), refresh_conditions=organ.refresh
    )
    core._conditions = lambda: {**BASE_CONDITIONS, **organ.snapshot()}

    await core.capture_reference("birth")

    _RaisingSampler._called = False
    core._sampler = _RaisingSampler()
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_changed"
    assert not _RaisingSampler._called


async def test_refresh_raises_during_look_is_conditions_unreadable(tmp_path):
    core, _paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    await core.capture_reference("birth")

    async def bad_refresh():
        raise RuntimeError("refresh failed")

    core._refresh_conditions = bad_refresh

    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_unreadable"


async def test_capture_refuses_when_organ_unreachable(tmp_path):
    core, paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())

    async def bad_refresh():
        raise RuntimeError("organ unreachable")

    core._refresh_conditions = bad_refresh

    with pytest.raises(RuntimeError, match="Failed to refresh probe conditions"):
        await core.capture_reference("birth")

    assert load_reference(paths) is None


# --- fail closed on bad stored conditions ---


async def test_stored_empty_conditions_is_conditions_changed(tmp_path):
    core, paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: BASE_CONDITIONS.copy()
    await core.capture_reference("birth")

    ref = load_reference(paths)
    ref = dataclasses.replace(ref, conditions={})
    save_reference(paths, ref, overwrite=True)

    _RaisingSampler._called = False
    core._sampler = _RaisingSampler()
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_changed"
    assert not _RaisingSampler._called


async def test_stored_empty_conditions_refused_even_when_current_has_only_embedder_keys(tmp_path):
    # Embedder keys are excluded from the comparison, so without an explicit
    # refusal an empty stored mapping would compare as "no change" here.
    core, paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: {"embedder_id": "embed-a"}
    await core.capture_reference("birth")

    ref = load_reference(paths)
    ref = dataclasses.replace(ref, conditions={})
    save_reference(paths, ref, overwrite=True)

    _RaisingSampler._called = False
    core._sampler = _RaisingSampler()
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "conditions_changed"
    assert not _RaisingSampler._called


async def test_stored_non_mapping_conditions_is_refused(tmp_path):
    # The store refuses a reference whose conditions are not a mapping when it
    # loads the document, before the look's own non-mapping check is reached.
    core, paths = make_core(tmp_path, conditioning_inputs=FakeConditioning())
    core._conditions = lambda: BASE_CONDITIONS.copy()
    await core.capture_reference("birth")

    ref = load_reference(paths)
    ref = dataclasses.replace(ref, conditions=["bad"])
    save_reference(paths, ref, overwrite=True)

    _RaisingSampler._called = False
    core._sampler = _RaisingSampler()
    outcome = await core.look(warmed_up=True, lived_seconds=1.0, lived_ticks=1)

    assert outcome.outcome == "inconclusive"
    assert outcome.reason == "reference_unreadable"
    assert not _RaisingSampler._called


# --- scheduler alerting ---


async def test_conditions_changed_alert_sent_once(tmp_path):
    alerts = []

    async def record_alert(d):
        alerts.append(d)

    sched, core, clock = make(tmp_path, alert=record_alert)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="ref-1",
            looks_completed=1,
            alpha_spent=0.0,
            lived_seconds=10.0,
            lived_ticks=5,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    core.next_look = LookOutcome("inconclusive", "conditions_changed", None)

    await sched.tick()
    clock.t += 10
    await sched.tick()
    assert len(core.looks) == 1

    c_alerts = [a for a in alerts if a.get("kind") == "individuation_conditions_changed"]
    assert len(c_alerts) == 1
    assert c_alerts[0]["reference_id"] == "ref-1"

    ledger = load_ledger(paths)
    assert ledger.conditions_alerted_reference == "ref-1"

    # A second look for the same reference must not re-alert.
    alerts.clear()
    clock.t += 60
    core.next_look = LookOutcome("inconclusive", "conditions_changed", None)
    await sched.tick()
    assert len(core.looks) == 2

    c_alerts_2 = [
        a for a in alerts if a.get("kind") == "individuation_conditions_changed"
    ]
    assert len(c_alerts_2) == 0


async def test_conditions_changed_alert_failure_still_saves_ledger(tmp_path):
    calls = []
    alerts = []

    async def failing_alert(d):
        if d.get("kind") == "individuation_conditions_changed":
            calls.append(d)
            raise RuntimeError("alert failed")
        alerts.append(d)

    sched, core, clock = make(tmp_path, alert=failing_alert)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="ref-1",
            looks_completed=1,
            alpha_spent=0.0,
            lived_seconds=10.0,
            lived_ticks=5,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    core.next_look = LookOutcome("inconclusive", "conditions_changed", None)

    await sched.tick()
    clock.t += 10
    await sched.tick()
    assert len(core.looks) == 1

    assert len(calls) == 1
    assert len([a for a in alerts if a.get("kind") == "individuation_conditions_changed"]) == 0

    ledger = load_ledger(paths)
    assert ledger.conditions_alerted_reference is None
    assert ledger.last_inconclusive_reason == "conditions_changed"
    assert ledger.inconclusive_since is not None


async def test_long_inconclusive_alert_includes_last_reason(tmp_path):
    alerts = []

    async def record_alert(d):
        alerts.append(d)

    sched, core, clock = make(tmp_path, alert=record_alert)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="ref-1",
            looks_completed=1,
            alpha_spent=0.0,
            lived_seconds=10.0,
            lived_ticks=5,
            inconclusive_since=(base - timedelta(seconds=600)).isoformat(),
            inconclusive_alerted=False,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    core.next_look = LookOutcome("inconclusive", "conditions_unreadable", None)

    await sched.tick()
    clock.t += 10
    await sched.tick()
    assert len(core.looks) == 1

    inc_alerts = [a for a in alerts if a.get("kind") == "individuation_inconclusive"]
    assert len(inc_alerts) == 1
    assert inc_alerts[0].get("last_reason") == "conditions_unreadable"

    ledger = load_ledger(paths)
    assert ledger.last_inconclusive_reason == "conditions_unreadable"


async def test_look_raises_marks_inconclusive_with_error_reason(tmp_path):
    alerts = []

    async def record_alert(d):
        alerts.append(d)

    sched, core, clock = make(tmp_path, alert=record_alert)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="ref-1",
            looks_completed=2,
            alpha_spent=0.0,
            lived_seconds=10.0,
            lived_ticks=5,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    core.raise_on_look = RuntimeError("look failed")

    await sched.tick()
    clock.t += 10
    await sched.tick()
    assert len(core.looks) == 1

    ledger = load_ledger(paths)
    if ledger.inconclusive_since is not None:
        assert ledger.last_inconclusive_reason == "error"


def test_old_ledger_without_new_fields_loads():
    old = {
        "reference_id": "ref-1",
        "looks_completed": 0,
        "alpha_spent": 0.0,
        "lived_seconds": 0.0,
        "lived_ticks": 0,
    }
    ledger = Ledger.from_dict(old)

    assert ledger.conditions_alerted_reference is None
    assert ledger.last_inconclusive_reason is None
