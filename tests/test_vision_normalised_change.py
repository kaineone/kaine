# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.vision import Vision


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


_STEADY = [0.5, 0.5, 0.5, 0.5]
_STEP = [0.5, -0.5, 0.5, -0.5]


class FakeEncoder:
    model_id = "fake/encoder-test"
    latent_dim = 4
    clip_len = 1  # per-frame test double (clip seam: a 1-frame clip)

    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self.calls = 0
        self.loaded = False
        self.shutdown_called = False
        self._vectors = vectors or [[1.0, 0.0, 0.0, 0.0]]

    async def load(self) -> None:
        self.loaded = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def encode(self, image):  # noqa: ARG002
        vec = self._vectors[self.calls % len(self._vectors)]
        self.calls += 1
        return list(vec)

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


class FakeForwardModel:
    """Test double: always returns a preset prediction error; records steps."""

    def __init__(
        self,
        latent_dim: int = 4,
        *,
        preset_errors: list[float] | None = None,
    ) -> None:
        self.latent_dim = latent_dim
        self.visual_buffer_size = 16
        self.suspended: bool = False
        self._preset_errors = preset_errors or []
        self._call_count = 0
        self.steps: list[list[float]] = []
        # MLP weights placeholder for state_dict compatibility
        self._weight_val: list[list[float]] = [[0.0] * (2 * latent_dim)] * latent_dim
        self._bias_val: list[float] = [0.0] * latent_dim

    def step(self, latent: list[float]) -> float:
        self.steps.append(list(latent))
        idx = self._call_count
        self._call_count += 1
        if idx < len(self._preset_errors):
            return self._preset_errors[idx]
        return 0.0

    def state_dict(self) -> dict:
        return {
            "layers": [
                {"weight": self._weight_val, "bias": self._bias_val},
                {"weight": [[0.0] * self.latent_dim], "bias": [0.0]},
            ]
        }

    def matches_state_shape(self, state: dict) -> bool:
        layers = state.get("layers", [])
        return isinstance(layers, list) and len(layers) >= 2

    def load_state_dict(self, state: dict) -> None:
        layers = state.get("layers", [])
        if layers:
            self._weight_val = layers[0]["weight"]
            self._bias_val = layers[0]["bias"]

    def buffer_summary(self) -> dict:
        return {
            "n_frames": len(self.steps),
            "mean": [0.0] * self.latent_dim,
            "variance": [0.0] * self.latent_dim,
        }


async def _reports(bus: AsyncBus, vision: Vision, frames: list) -> list[dict]:
    for frame in frames:
        await vision.process_frame(frame)
    entries = await bus.read("vision.out", last_id="0")
    return [event.payload for _, event in entries]


@pytest.mark.asyncio
async def test_normalised_change_without_forward_prediction(bus):
    enc = FakeEncoder(vectors=[_STEADY, _STEADY, _STEADY, _STEADY, _STEP])
    vision = Vision(
        bus,
        encoder=enc,
        forward_prediction=False,
        change_alert_threshold=1e-4,
        change_alert_factor=2.0,
    )
    reports = await _reports(bus, vision, [None] * 5)

    for report in reports:
        assert "normalised_change" in report
    for report in reports[:4]:
        assert report["normalised_change"] == 0.0

    last = reports[4]
    assert last["normalised_change"] == pytest.approx(last["change_score"] / 0.2)
    assert last["normalised_change"] == pytest.approx(5.0)
    assert last["alert"] is True


@pytest.mark.asyncio
async def test_normalised_change_with_forward_prediction(bus):
    enc = FakeEncoder(vectors=[_STEADY, _STEADY, _STEADY, _STEADY, _STEP])
    vision = Vision(
        bus,
        encoder=enc,
        forward_prediction=True,
        change_alert_threshold=1e-4,
        change_alert_factor=2.0,
    )
    vision._forward_model = FakeForwardModel(latent_dim=4, preset_errors=[1.0] * 5)
    reports = await _reports(bus, vision, [None] * 5)

    for report in reports:
        assert "normalised_change" in report
    assert reports[4]["normalised_change"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_first_report_normalised_change_is_zero(bus):
    enc = FakeEncoder(vectors=[_STEADY])
    vision = Vision(bus, encoder=enc)
    reports = await _reports(bus, vision, [None])

    assert len(reports) == 1
    assert reports[0]["normalised_change"] == 0.0


@pytest.mark.asyncio
async def test_normalised_change_is_float(bus):
    enc = FakeEncoder(vectors=[_STEADY, _STEADY, _STEADY, _STEADY, _STEP])
    vision = Vision(bus, encoder=enc)
    reports = await _reports(bus, vision, [None] * 5)

    for report in reports:
        assert isinstance(report["normalised_change"], float)
