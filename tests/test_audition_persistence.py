# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import logging
import time
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_audition(bus: AsyncBus, **overrides) -> Audition:
    overrides.setdefault("stt_client", FakeSTTClient(responses=["hello world"]))
    overrides.setdefault("emotion_classifier", FakeEmotionClassifier())
    overrides.setdefault("stt_model", "fake-stt")
    overrides.setdefault("transcription_enabled", True)
    return Audition(bus, **overrides)


async def _close_module(module: Audition) -> None:
    await module.shutdown()
    for task in list(getattr(module, "_tasks", [])):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected: the task was cancelled just above.
                pass


@pytest.mark.asyncio
async def test_acoustic_forward_model_round_trip(bus):
    encoder = FakeAcousticEncoder(8)
    audition = _make_audition(bus, general_audition=True, acoustic_encoder=encoder)
    await audition.initialize()
    try:
        for i in range(5):
            audio = bytes([i] * 1024)
            await audition._perceive_acoustic(audio, 16000, "seeded")
        state = audition.serialize()
        weights_before = audition._acoustic_forward_model.state_dict()
    finally:
        await _close_module(audition)

    new_audition = _make_audition(bus, general_audition=True, acoustic_encoder=encoder)
    await new_audition.initialize()
    try:
        fresh_weights = new_audition._acoustic_forward_model.state_dict()
        new_audition.deserialize(state)
        # The weights round-trip exactly; the recurrent buffer is RAM-only by design.
        restored = new_audition._acoustic_forward_model.state_dict()
        assert restored == weights_before
        assert restored != fresh_weights
    finally:
        await _close_module(new_audition)


@pytest.mark.asyncio
async def test_acoustic_shape_mismatch_discarded_with_warning(bus, caplog):
    class _SharedIdEncoder8(FakeAcousticEncoder):
        def __init__(self):
            super().__init__(8)

        @property
        def model_id(self):
            return "fake/shared"

    class _SharedIdEncoder16(FakeAcousticEncoder):
        def __init__(self):
            super().__init__(16)

        @property
        def model_id(self):
            return "fake/shared"

    enc8 = _SharedIdEncoder8()
    audition = _make_audition(bus, general_audition=True, acoustic_encoder=enc8)
    await audition.initialize()
    try:
        for i in range(4):
            await audition._perceive_acoustic(bytes([i] * 1024), 16000, "seeded")
        state = audition.serialize()
    finally:
        await _close_module(audition)

    enc16 = _SharedIdEncoder16()
    new = _make_audition(bus, general_audition=True, acoustic_encoder=enc16)
    original_weights = new._acoustic_forward_model.state_dict()
    with caplog.at_level(logging.WARNING, logger="kaine.modules.audition"):
        new.deserialize(state)
    assert any(
        "discarding" in rec.message.lower() and "fake/shared" in rec.message
        for rec in caplog.records
    )
    assert new._acoustic_forward_model.state_dict() == original_weights
    await _close_module(new)


@pytest.mark.asyncio
async def test_switch_encoder_carries_other_encoder_state(bus):
    enc_a = FakeAcousticEncoder(8)
    enc_b = FakeAcousticEncoder(16)

    audition_a = _make_audition(bus, general_audition=True, acoustic_encoder=enc_a)
    await audition_a.initialize()
    try:
        for i in range(3):
            await audition_a._perceive_acoustic(bytes([i] * 1024), 16000, "seeded")
        state_a = audition_a.serialize()
        a_entry = state_a["acoustic_forward_models"][enc_a.model_id]
    finally:
        await _close_module(audition_a)

    audition_b = _make_audition(bus, general_audition=True, acoustic_encoder=enc_b)
    await audition_b.initialize()
    try:
        audition_b.deserialize(state_a)
        state_b = audition_b.serialize()
    finally:
        await _close_module(audition_b)

    assert enc_a.model_id in state_b["acoustic_forward_models"]
    assert state_b["acoustic_forward_models"][enc_a.model_id] == a_entry


@pytest.mark.asyncio
async def test_serialized_state_zero_persistence(bus):
    encoder = FakeAcousticEncoder(8)
    audition = _make_audition(bus, general_audition=True, acoustic_encoder=encoder)
    await audition.initialize()
    try:
        for i in range(4):
            await audition._perceive_acoustic(bytes([i] * 1024), 16000, "seeded")
        state = audition.serialize()
    finally:
        await _close_module(audition)

    mean_len = len(state.get("auditory_buffer_summary", {}).get("mean", []))

    def _walk(obj, path="root"):
        if isinstance(obj, bytes):
            raise AssertionError(f"bytes at {path}")
        if isinstance(obj, list):
            if (
                obj
                and all(isinstance(v, (int, float)) for v in obj)
                and len(obj) > mean_len
                and "layers" not in path
            ):
                raise AssertionError(
                    f"unexpected long numeric vector at {path} "
                    f"({len(obj)} > {mean_len})"
                )
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{path}[{k!r}]")

    _walk(state)


@pytest.mark.asyncio
async def test_speech_forward_model_shape_mismatch_discarded(bus, caplog):
    audition = _make_audition(bus)
    original_weights = audition._forward_model.state_dict()
    bad_state = {
        "forward_model": {
            "layers": [
                {"weight": [[0.0] * 10] * 4, "bias": [0.0] * 4},
                {"weight": [[0.0] * 99] * 99, "bias": [0.0] * 99},
            ]
        }
    }
    with caplog.at_level(logging.WARNING, logger="kaine.modules.audition"):
        audition.deserialize(bad_state)
    assert any("discarding" in rec.message.lower() for rec in caplog.records)
    assert audition._forward_model.state_dict() == original_weights
    await _close_module(audition)


@pytest.mark.asyncio
async def test_sleep_suspends_both_forward_models(bus):
    encoder = FakeAcousticEncoder(8)
    audition = _make_audition(bus, general_audition=True, acoustic_encoder=encoder)
    await audition.initialize()
    try:
        start = time.monotonic()
        await bus.publish(
            Event(
                source="hypnos",
                type="hypnos.sleep.started",
                payload={},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            )
        )
        while not audition._in_hypnos and time.monotonic() - start < 2:
            await asyncio.sleep(0.05)
        assert audition._in_hypnos
        assert audition._forward_model.suspended
        assert audition._acoustic_forward_model.suspended

        weights_before = audition._acoustic_forward_model.state_dict()
        await audition._perceive_acoustic(b"\x01" * 1024, 16000, "seeded")
        weights_after = audition._acoustic_forward_model.state_dict()
        assert weights_before == weights_after

        await bus.publish(
            Event(
                source="hypnos",
                type="hypnos.sleep.completed",
                payload={},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            )
        )
        start = time.monotonic()
        while audition._in_hypnos and time.monotonic() - start < 2:
            await asyncio.sleep(0.05)
        assert not audition._in_hypnos
        assert not audition._forward_model.suspended
        assert not audition._acoustic_forward_model.suspended
    finally:
        await _close_module(audition)


def test_matches_state_shape_checks_each_dimension():
    from kaine.modules.audition.forward import AuditoryForwardModel

    model = AuditoryForwardModel(feature_dim=8, units=4)
    good = model.state_dict()
    assert model.matches_state_shape(good)
    wider_input = {"layers": [dict(good["layers"][0]), dict(good["layers"][-1])]}
    wider_input["layers"][0]["weight"] = [row + [0.0] for row in good["layers"][0]["weight"]]
    assert not model.matches_state_shape(wider_input)
    assert not model.matches_state_shape(AuditoryForwardModel(feature_dim=8, units=5).state_dict())
    assert not model.matches_state_shape(AuditoryForwardModel(feature_dim=9, units=4).state_dict())
    assert not model.matches_state_shape({"layers": []})


def test_matches_state_shape_rejects_bad_inner_shapes():
    """Matching outer dimensions are not enough: the hidden width, every bias,
    ragged rows, non-numeric values and extra layers must all fit, so
    load_state_dict can never fail part-way through a restore."""
    import copy

    from kaine.modules.audition.forward import AuditoryForwardModel

    model = AuditoryForwardModel(feature_dim=8, units=4)
    good = model.state_dict()

    # The output layer reads a wider hidden layer than this model has.
    wider_hidden = copy.deepcopy(good)
    wider_hidden["layers"][-1]["weight"] = [row + [0.0] for row in good["layers"][-1]["weight"]]
    # Bias lengths.
    long_bias = copy.deepcopy(good)
    long_bias["layers"][0]["bias"] = good["layers"][0]["bias"] + [0.0]
    short_bias = copy.deepcopy(good)
    short_bias["layers"][-1]["bias"] = good["layers"][-1]["bias"][:-1]
    # A ragged weight row.
    ragged = copy.deepcopy(good)
    ragged["layers"][0]["weight"][1] = good["layers"][0]["weight"][1][:-1]
    # A non-numeric value, and a missing bias.
    non_numeric = copy.deepcopy(good)
    non_numeric["layers"][0]["weight"][0][0] = "x"
    missing_bias = copy.deepcopy(good)
    del missing_bias["layers"][0]["bias"]
    # An extra layer.
    extra_layer = copy.deepcopy(good)
    extra_layer["layers"].append(copy.deepcopy(good["layers"][-1]))

    for bad in (wider_hidden, long_bias, short_bias, ragged, non_numeric, missing_bias, extra_layer):
        assert not model.matches_state_shape(bad)
    assert model.matches_state_shape(good)


@pytest.mark.asyncio
async def test_speech_forward_model_bad_bias_discarded_not_raised(bus, caplog):
    audition = _make_audition(bus)
    original_weights = audition._forward_model.state_dict()
    bad = audition._forward_model.state_dict()
    bad["layers"][-1]["bias"] = bad["layers"][-1]["bias"] + [0.0]
    with caplog.at_level(logging.WARNING, logger="kaine.modules.audition"):
        audition.deserialize({"forward_model": bad})
    assert any("discarding" in rec.message.lower() for rec in caplog.records)
    assert audition._forward_model.state_dict() == original_weights
    await _close_module(audition)
