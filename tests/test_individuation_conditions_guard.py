# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import logging

import pytest

from kaine.cycle.individuation_producer import _condition_changes
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_producer_core import FakeConditioning, make_core

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
