# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.topos import Topos
from kaine.modules.topos.encoder import Encoder


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


# ---------------------------------------------------------------------------
# Fake forward model for controlled testing
# ---------------------------------------------------------------------------

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


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_fake_encoder_satisfies_protocol():
    assert isinstance(FakeEncoder(), Encoder)


@pytest.mark.asyncio
async def test_playlist_item_provenance_is_stamped_on_report(bus: AsyncBus):
    """When a playlist feed is active, topos.report carries the CONTENT-FREE item
    identity (basename + manifest order) read off the shared clock, so the
    playing show is legible on the bus rather than inferred from file descriptors
    (playlist-realtime-av-sync task 3.2/3.3)."""
    import types

    from kaine.modules.topos.feed import PlaylistPosition

    enc = FakeEncoder([[1.0, 0.0, 0.0, 0.0]])
    topos = Topos(bus, encoder=enc)
    # Stand in for the LiveCamera whose source exposes the current playlist item.
    topos._live_camera = types.SimpleNamespace(
        current_item=PlaylistPosition(title="episode-01.mkv", order=0, offset=1.5, item_idx=0)
    )
    await topos.process_frame(object())
    _, event = (await bus.read("topos.out", last_id="0"))[0]
    assert event.type == "topos.report"
    assert event.payload["item"] == "episode-01.mkv"
    assert event.payload["item_order"] == 0
    # Content-free: only a basename str + an int order, never any pixels/bytes.
    assert isinstance(event.payload["item"], str)
    assert isinstance(event.payload["item_order"], int)
    for v in event.payload.values():
        assert not isinstance(v, (bytes, bytearray))


@pytest.mark.asyncio
async def test_report_has_no_item_keys_without_a_playlist(bus: AsyncBus):
    """No playlist feed -> no item provenance keys (the real camera / seeded feed
    path is unchanged)."""
    enc = FakeEncoder([[1.0, 0.0, 0.0, 0.0]])
    topos = Topos(bus, encoder=enc)  # no live camera wired
    await topos.process_frame(object())
    _, event = (await bus.read("topos.out", last_id="0"))[0]
    assert "item" not in event.payload
    assert "item_order" not in event.payload


@pytest.mark.asyncio
async def test_one_frame_produces_one_report(bus: AsyncBus):
    enc = FakeEncoder([[1.0, 0.0, 0.0, 0.0]])
    topos = Topos(bus, encoder=enc)
    entry_id = await topos.process_frame(object())
    assert entry_id
    entries = await bus.read("topos.out", last_id="0")
    assert len(entries) == 1
    _, event = entries[0]
    assert event.type == "topos.report"
    assert event.payload["latent"] == [1.0, 0.0, 0.0, 0.0]
    assert event.payload["change_score"] == 0.0  # first frame
    assert 0.0 <= event.payload["habituation_score"] <= 1.0
    assert event.payload["encoder_model_id"] == "fake/encoder-test"


@pytest.mark.asyncio
async def test_orthogonal_frames_trigger_alert_salience(bus: AsyncBus):
    enc = FakeEncoder([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    topos = Topos(
        bus,
        encoder=enc,
        change_alert_threshold=0.5,
        alert_salience=0.85,
    )
    await topos.process_frame(None)
    await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    _, second = entries[1]
    assert second.payload["change_score"] >= 1.0 - 1e-9
    assert second.salience == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_identical_frames_keep_baseline_salience(bus: AsyncBus):
    enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]])
    topos = Topos(
        bus,
        encoder=enc,
        change_alert_threshold=0.5,
        baseline_salience=0.15,
    )
    await topos.process_frame(None)
    await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    _, second = entries[1]
    assert second.payload["change_score"] == pytest.approx(0.0, abs=1e-9)
    assert second.salience == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_initialize_loads_encoder_and_shutdown_releases(bus: AsyncBus):
    enc = FakeEncoder()
    topos = Topos(bus, encoder=enc)
    await topos.initialize()
    try:
        assert enc.loaded is True
    finally:
        await topos.shutdown()
    assert enc.shutdown_called is True


@pytest.mark.asyncio
async def test_invalid_construction_rejected(bus: AsyncBus):
    with pytest.raises(ValueError):
        Topos(bus, encoder=FakeEncoder(), baseline_salience=2.0)
    with pytest.raises(ValueError):
        Topos(bus, encoder=FakeEncoder(), alert_salience=-0.1)
    with pytest.raises(ValueError):
        Topos(bus, encoder=FakeEncoder(), change_alert_threshold=-1.0)


@pytest.mark.asyncio
async def test_custom_components_substitute(bus: AsyncBus):
    enc = FakeEncoder([[1.0, 0.0]])

    class TrackingChange:
        def __init__(self):
            self.calls = 0

        def observe(self, e):  # noqa: ARG002
            self.calls += 1
            return 99.0

        def reset(self):
            pass

    class TrackingHab:
        def __init__(self):
            self.calls = 0

        def observe(self, e):  # noqa: ARG002
            self.calls += 1
            return 0.42

        def reset(self):
            pass

    tc, th = TrackingChange(), TrackingHab()
    topos = Topos(
        bus, encoder=enc, change_detector=tc, habituator=th,
        change_alert_threshold=200.0,  # 99.0 doesn't trigger
    )
    await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    _, ev = entries[0]
    assert ev.payload["change_score"] == 99.0
    assert ev.payload["habituation_score"] == pytest.approx(0.42)
    assert tc.calls == 1
    assert th.calls == 1


@pytest.mark.asyncio
async def test_serialize_records_encoder_id(bus: AsyncBus):
    enc = FakeEncoder()
    topos = Topos(bus, encoder=enc)
    state = topos.serialize()
    assert state["encoder_model_id"] == "fake/encoder-test"
    topos.deserialize(state)  # no-op for matching encoder


# ---------------------------------------------------------------------------
# Forward-prediction integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prediction_error_on_payload(bus: AsyncBus):
    """process_frame() always includes prediction_error on the payload."""
    enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]])
    topos = Topos(bus, encoder=enc, forward_prediction=True)
    topos._forward_model = FakeForwardModel(latent_dim=4, preset_errors=[0.0])
    await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    _, event = entries[0]
    assert "prediction_error" in event.payload
    assert isinstance(event.payload["prediction_error"], float)


@pytest.mark.asyncio
async def test_payload_retains_change_and_habituation(bus: AsyncBus):
    """Even with forward_prediction enabled, change_score and habituation_score
    must remain on the event payload for diagnostics continuity."""
    enc = FakeEncoder([[1.0, 0.0, 0.0, 0.0]])
    topos = Topos(bus, encoder=enc, forward_prediction=True)
    topos._forward_model = FakeForwardModel(latent_dim=4, preset_errors=[0.0])
    await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    _, event = entries[0]
    assert "change_score" in event.payload
    assert "habituation_score" in event.payload
    assert 0.0 <= event.payload["habituation_score"] <= 1.0


@pytest.mark.asyncio
async def test_predictable_motion_lower_salience_than_surprise(bus: AsyncBus):
    """Spec scenario: predictable → low salience; surprise → high salience.

    We use a FakeForwardModel that returns LOW error (0.01, well below mean)
    for a predictable sequence, and HIGH error (100.0, far above mean) for
    a surprise frame.  The predictable frame should get baseline_salience and
    the surprise frame alert_salience.
    """
    baseline_sal = 0.1
    alert_sal = 0.9

    # --- Predictable sequence: low error throughout ---
    enc_pred = FakeEncoder([[0.3, 0.3, 0.3, 0.3]] * 10)
    topos_pred = Topos(
        bus,
        encoder=enc_pred,
        forward_prediction=True,
        baseline_salience=baseline_sal,
        alert_salience=alert_sal,
    )
    # Seed many low-error steps so the rolling mean is low.
    low_errors = [0.01] * 10
    topos_pred._forward_model = FakeForwardModel(latent_dim=4, preset_errors=low_errors)
    # Prime the pred_errors deque with many low values so mean stays low.
    from collections import deque
    topos_pred._pred_errors = deque([0.01] * 30, maxlen=32)

    # Feed a "predictable" frame with low error (the last preset).
    # After 9 priming steps, error[9] = 0.01 < mean ≈ 0.01 → normalised ≤ 1.0
    for _ in range(9):
        await topos_pred.process_frame(None)

    await bus.client.delete("topos.out")  # clear bus for isolation
    await topos_pred.process_frame(None)

    entries_pred = await bus.read("topos.out", last_id="0")
    _, ev_pred = entries_pred[-1]
    predictable_salience = ev_pred.salience

    # --- Surprise frame: very high error against a low-error mean ---
    await bus.client.delete("topos.out")
    enc_surp = FakeEncoder([[0.9, 0.9, 0.9, 0.9]])
    topos_surp = Topos(
        bus,
        encoder=enc_surp,
        forward_prediction=True,
        baseline_salience=baseline_sal,
        alert_salience=alert_sal,
    )
    # Pre-load rolling mean with small errors, then inject a huge error.
    topos_surp._forward_model = FakeForwardModel(
        latent_dim=4, preset_errors=[100.0]
    )
    topos_surp._pred_errors = deque([0.01] * 31, maxlen=32)

    await topos_surp.process_frame(None)

    entries_surp = await bus.read("topos.out", last_id="0")
    _, ev_surp = entries_surp[-1]
    surprise_salience = ev_surp.salience

    assert surprise_salience > predictable_salience, (
        f"surprise salience ({surprise_salience}) must be greater than "
        f"predictable salience ({predictable_salience})"
    )


@pytest.mark.asyncio
async def test_forward_model_disabled_behavior_unchanged(bus: AsyncBus):
    """With forward_prediction=False, salience uses legacy change_score path."""
    enc = FakeEncoder([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    topos = Topos(
        bus,
        encoder=enc,
        forward_prediction=False,
        change_alert_threshold=0.5,
        alert_salience=0.85,
    )
    assert topos._forward_model is None
    await topos.process_frame(None)
    await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    _, second = entries[1]
    # Orthogonal frames → change_score ≈ 1.0 > 0.5 → alert_salience
    assert second.salience == pytest.approx(0.85)
    # prediction_error field present with value 0.0 (no model active)
    assert second.payload["prediction_error"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_serialize_roundtrip_with_forward_model(bus: AsyncBus):
    """serialize() / deserialize() round-trips forward-model weights."""
    from kaine.modules.topos.forward import LatentForwardModel

    enc = FakeEncoder([[0.4, 0.4, 0.4, 0.4]])
    topos = Topos(bus, encoder=enc, forward_prediction=True)
    # Build a real forward model (latent_dim=4) and adapt it.
    fm = LatentForwardModel(latent_dim=4, units=16, seed=7, lr=0.05)
    for _ in range(5):
        fm.step([0.4] * 4)
    topos._forward_model = fm

    state = topos.serialize()
    assert "forward_model" in state
    assert "buffer_summary" in state

    # Restore into a fresh Topos with a new LatentForwardModel.
    fresh_fm = LatentForwardModel(latent_dim=4, units=16, seed=99)
    enc2 = FakeEncoder([[0.4, 0.4, 0.4, 0.4]])
    fresh_topos = Topos(bus, encoder=enc2, forward_prediction=True)
    fresh_topos._forward_model = fresh_fm
    fresh_topos.deserialize(state)

    # Compare with empty buffer on both models so the buffer context matches.
    # The buffer is not serialised (only a statistical summary is), so a
    # restored model correctly starts with an empty buffer.
    fm._buffer.clear()
    probe = [0.2] * 4
    assert fm.predict(probe) == pytest.approx(fresh_fm.predict(probe), abs=1e-5)


# ---------------------------------------------------------------------------
# Attention-driven foveation integration (topos-foveation)
# ---------------------------------------------------------------------------


def _rgb_frame(h=240, w=320, fill=0):
    return np.full((h, w, 3), fill, dtype=np.uint8)


@pytest.mark.asyncio
async def test_foveation_off_is_single_encode_and_no_extra_keys(bus: AsyncBus):
    """Default (foveation off): one encode, `latent` present, no fovea keys."""
    enc = FakeEncoder([[1.0, 0.0, 0.0, 0.0]])
    topos = Topos(bus, encoder=enc)
    await topos.process_frame(_rgb_frame())
    assert enc.calls == 1  # single whole-frame encode
    entries = await bus.read("topos.out", last_id="0")
    _, ev = entries[0]
    assert ev.payload["latent"] == [1.0, 0.0, 0.0, 0.0]
    assert "peripheral" not in ev.payload
    assert "foveal" not in ev.payload
    assert "fovea" not in ev.payload
    assert "predicted_fovea" not in ev.payload


@pytest.mark.asyncio
async def test_foveation_on_emits_two_latents_and_content_free_fovea(bus: AsyncBus):
    """Foveation on: two encodes (peripheral then foveal); `latent` is the
    peripheral gist; `fovea` carries only normalized floats."""
    enc = FakeEncoder([[0.1, 0.2, 0.3, 0.4], [0.9, 0.8, 0.7, 0.6]])
    topos = Topos(bus, encoder=enc, foveation_enabled=True)
    await topos.process_frame(_rgb_frame())
    assert enc.calls == 2  # peripheral + foveal
    entries = await bus.read("topos.out", last_id="0")
    _, ev = entries[0]
    # First encode (peripheral) drives `latent`; second is the foveal detail.
    assert ev.payload["latent"] == [0.1, 0.2, 0.3, 0.4]
    assert ev.payload["peripheral"] == [0.1, 0.2, 0.3, 0.4]
    assert ev.payload["foveal"] == [0.9, 0.8, 0.7, 0.6]
    fovea = ev.payload["fovea"]
    assert set(fovea) == {"x", "y", "size"}
    for v in fovea.values():
        assert isinstance(v, float)
        assert 0.0 <= v <= 1.0
    # Attention schema: the content-free predicted next fovea rides alongside.
    predicted = ev.payload["predicted_fovea"]
    assert set(predicted) == {"x", "y", "size"}
    for v in predicted.values():
        assert isinstance(v, float)
        assert 0.0 <= v <= 1.0


@pytest.mark.asyncio
async def test_attention_schema_predicts_toward_the_fovea_trajectory(bus: AsyncBus):
    """The predicted next fovea extrapolates the fovea's motion: as a localized
    change pulls the fovea toward the lower-right over successive ticks, the
    prediction leads the current fovea in that direction."""
    enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]] * 12)
    # A fine grid so the argmax can march tile-by-tile toward the corner.
    topos = Topos(bus, encoder=enc, foveation_enabled=True, foveation_grid=(16, 16))
    await topos.process_frame(_rgb_frame(fill=0))  # prime saliency baseline
    # Two ticks of the bright patch marching toward the lower-right corner.
    f1 = _rgb_frame(fill=0)
    f1[120:180, 160:220] = 255
    await topos.process_frame(f1)
    f2 = _rgb_frame(fill=0)
    f2[180:240, 260:320] = 255
    await topos.process_frame(f2)
    entries = await bus.read("topos.out", last_id="0")
    _, ev = entries[-1]
    fovea = ev.payload["fovea"]
    predicted = ev.payload["predicted_fovea"]
    # A rightward+downward drift → the prediction leads the current fovea.
    assert predicted["x"] >= fovea["x"]
    assert predicted["y"] >= fovea["y"]


@pytest.mark.asyncio
async def test_foveation_targets_the_changed_region(bus: AsyncBus):
    """A localized change on a static field pulls the fovea toward that region."""
    enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]] * 8)
    topos = Topos(bus, encoder=enc, foveation_enabled=True)
    await topos.process_frame(_rgb_frame(fill=0))  # prime saliency baseline
    f = _rgb_frame(fill=0)
    f[180:240, 260:320] = 255  # brighten lower-right
    await topos.process_frame(f)
    entries = await bus.read("topos.out", last_id="0")
    _, ev = entries[-1]
    fovea = ev.payload["fovea"]
    assert fovea["x"] > 0.5 and fovea["y"] > 0.5  # lower-right


@pytest.mark.asyncio
async def test_top_down_bias_provider_moves_the_fovea(bus: AsyncBus):
    """An injected top-down bias can override the bottom-up argmax."""
    enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]] * 8)
    topos = Topos(bus, encoder=enc, foveation_enabled=True, foveation_grid=(4, 4))

    # Bias hard toward the top-left tile regardless of bottom-up saliency.
    bias = np.zeros((4, 4), dtype=np.float32)
    bias[0, 0] = 1.0e4  # dwarfs any per-tile pixel-change magnitude (≤255)
    topos.set_top_down_bias_provider(lambda: bias)

    await topos.process_frame(_rgb_frame(fill=0))
    f = _rgb_frame(fill=0)
    f[180:240, 260:320] = 255  # bottom-up wants lower-right...
    await topos.process_frame(f)
    entries = await bus.read("topos.out", last_id="0")
    _, ev = entries[-1]
    fovea = ev.payload["fovea"]
    assert fovea["x"] < 0.5 and fovea["y"] < 0.5  # ...but top-down wins: top-left


@pytest.mark.asyncio
async def test_arousal_provider_sizes_the_fovea(bus: AsyncBus):
    """Higher arousal → tighter fovea (Easterbrook narrowing default)."""

    async def _size_at(arousal: float) -> float:
        b = pytest.importorskip("fakeredis.aioredis")
        client = b.FakeRedis(decode_responses=True)
        local_bus = AsyncBus(
            BusConfig(password="x", audit_required=False), client=client
        )
        enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]] * 2)
        topos = Topos(local_bus, encoder=enc, foveation_enabled=True)
        topos.set_arousal_provider(lambda: arousal)
        await topos.process_frame(_rgb_frame())
        entries = await local_bus.read("topos.out", last_id="0")
        await local_bus.close()
        return entries[-1][1].payload["fovea"]["size"]

    calm = await _size_at(0.0)
    tense = await _size_at(1.0)
    assert tense < calm


@pytest.mark.asyncio
async def test_provider_failure_degrades_to_bottom_up(bus: AsyncBus):
    """A throwing provider must not break perception — it degrades gracefully."""
    enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]] * 2)
    topos = Topos(bus, encoder=enc, foveation_enabled=True)

    def _boom():
        raise RuntimeError("provider exploded")

    topos.set_top_down_bias_provider(_boom)
    topos.set_arousal_provider(_boom)
    entry_id = await topos.process_frame(_rgb_frame())  # must not raise
    assert entry_id
    entries = await bus.read("topos.out", last_id="0")
    assert "fovea" in entries[-1][1].payload


@pytest.mark.asyncio
async def test_serialized_buffer_no_raw_tensors(bus: AsyncBus):
    """The serialized buffer_summary must contain only numeric summaries —
    no torch.Tensor values (zero raw-sense-data persistence requirement)."""
    import torch

    enc = FakeEncoder([[0.5, 0.5, 0.5, 0.5]])
    topos = Topos(bus, encoder=enc, forward_prediction=True)
    fm = FakeForwardModel(latent_dim=4, preset_errors=[0.1] * 20)
    topos._forward_model = fm
    for _ in range(5):
        await topos.process_frame(None)

    state = topos.serialize()
    buf = state.get("buffer_summary", {})

    def _assert_no_tensors(obj, path="buffer_summary"):
        if isinstance(obj, torch.Tensor):
            raise AssertionError(
                f"Raw tensor found in serialized buffer at {path}: {obj.shape}"
            )
        if isinstance(obj, dict):
            for k, v in obj.items():
                _assert_no_tensors(v, f"{path}[{k!r}]")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _assert_no_tensors(v, f"{path}[{i}]")

    _assert_no_tensors(buf)

    # Must have the expected statistical summary keys.
    assert "n_frames" in buf
    assert "mean" in buf
    assert "variance" in buf


# ---------------------------------------------------------------------------
# Self-calibrating change alert (perception-drives-salience)
# ---------------------------------------------------------------------------

_STEADY = [0.5, 0.5, 0.5, 0.5]
_STEP = [0.5, -0.5, 0.5, -0.5]  # orthogonal to _STEADY → cosine change ≈ 1.0


@pytest.mark.asyncio
async def test_change_step_alerts_relative_to_own_baseline(bus: AsyncBus):
    """A step-change — change far above the module's OWN rolling baseline —
    alerts, with no absolute constant tuned to the embedding scale. A steady
    stream stays at baseline. This is the fix for flat-baseline perception."""
    enc = FakeEncoder([_STEADY, _STEADY, _STEADY, _STEADY, _STEP])
    topos = Topos(
        bus,
        encoder=enc,
        forward_prediction=False,  # isolate the self-calibrating change path
        change_alert_threshold=1e-4,  # small floor guard, not the primary gate
        change_alert_factor=2.0,
        baseline_salience=0.2,
        alert_salience=0.7,
    )
    for _ in range(5):
        await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    saliences = [ev.salience for _, ev in entries]
    # The four steady frames stay at baseline; the step alerts.
    assert all(s == pytest.approx(0.2) for s in saliences[:4])
    assert saliences[4] == pytest.approx(0.7)
    assert entries[4][1].payload["alert"] is True
    assert all(entries[i][1].payload["alert"] is False for i in range(4))


@pytest.mark.asyncio
async def test_change_alert_is_embedding_scale_agnostic(bus: AsyncBus):
    """The SAME step alerts whether the embedding scale is large or tiny — the
    criterion is relative to the module's own baseline, not an absolute constant.
    A fixed 0.005-style threshold would fire on one scale and never on the other."""
    async def _step_alerts(scale: float, local_bus: AsyncBus) -> bool:
        steady = [scale * v for v in _STEADY]
        step = [scale * v for v in _STEP]
        enc = FakeEncoder([steady, steady, steady, steady, step])
        topos = Topos(
            local_bus, encoder=enc, forward_prediction=False,
            change_alert_threshold=1e-6, change_alert_factor=2.0,
            baseline_salience=0.2, alert_salience=0.7,
        )
        for _ in range(5):
            await topos.process_frame(None)
        entries = await local_bus.read("topos.out", last_id="0")
        return entries[4][1].payload["alert"] is True

    # cosine change is scale-invariant, so both scales alert on the step — the
    # point is the criterion does not depend on an absolute embedding magnitude.
    assert await _step_alerts(1.0, bus) is True
    b = pytest.importorskip("fakeredis.aioredis")
    client = b.FakeRedis(decode_responses=True)
    other = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        assert await _step_alerts(1000.0, other) is True
    finally:
        await other.close()


@pytest.mark.asyncio
async def test_change_step_alerts_with_foveation_on(bus: AsyncBus):
    """Foveation on: the peripheral gist (encoded through the clip seam) drives
    the same self-calibrating alert — proving perception reaches salience with the
    guard against clip encoders retired (perception-drives-salience task 3)."""
    foveal = [0.9, 0.8, 0.7, 0.6]  # attended detail (2nd encode/tick), constant
    vectors: list[list[float]] = []
    for peripheral in (_STEADY, _STEADY, _STEADY, _STEADY, _STEP):
        vectors.append(peripheral)  # 1st encode/tick → peripheral gist → salience
        vectors.append(foveal)      # 2nd encode/tick → foveal detail
    enc = FakeEncoder(vectors)
    topos = Topos(
        bus,
        encoder=enc,
        foveation_enabled=True,
        forward_prediction=False,
        change_alert_threshold=1e-4,
        baseline_salience=0.2,
        alert_salience=0.7,
    )
    for _ in range(5):
        await topos.process_frame(_rgb_frame())
    entries = await bus.read("topos.out", last_id="0")
    saliences = [ev.salience for _, ev in entries]
    assert all(s == pytest.approx(0.2) for s in saliences[:4])
    assert saliences[4] == pytest.approx(0.7)
    # The peripheral gist is what drives `latent`/salience under foveation.
    assert entries[4][1].payload["latent"] == _STEP
    assert entries[4][1].payload["peripheral"] == _STEP


@pytest.mark.asyncio
async def test_perception_alert_stats_track_alert_rate(bus: AsyncBus):
    """The module exposes cumulative alert-level counts so a run's per-minute
    alert rate is legible (perception-drives-salience task 4.2)."""
    enc = FakeEncoder([_STEADY, _STEADY, _STEADY, _STEADY, _STEP])
    topos = Topos(
        bus, encoder=enc, forward_prediction=False,
        change_alert_threshold=1e-4, change_alert_factor=2.0,
    )
    for _ in range(5):
        await topos.process_frame(None)
    stats = topos.perception_alert_stats
    assert stats["reports"] == 5
    assert stats["alerts"] == 1
    assert stats["alert_rate"] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_change_alert_factor_validated(bus: AsyncBus):
    with pytest.raises(ValueError):
        Topos(bus, encoder=FakeEncoder(), change_alert_factor=0.5)


@pytest.mark.asyncio
async def test_foveation_accepts_pil_frames_from_the_live_feed(bus: AsyncBus):
    """The live camera / perception feed delivers PIL Images, not numpy arrays.
    Foveation's saliency + view derivation must coerce them (regression: the
    spatial-saliency path assumed ndarray and raised 'Image has no attribute ndim'
    when foveation first ran against the real feed)."""
    from PIL import Image

    enc = FakeEncoder([[0.1, 0.2, 0.3, 0.4], [0.9, 0.8, 0.7, 0.6]])
    topos = Topos(bus, encoder=enc, foveation_enabled=True)
    pil_frame = Image.new("RGB", (320, 240), (30, 60, 90))
    entry_id = await topos.process_frame(pil_frame)  # must not raise
    assert entry_id
    entries = await bus.read("topos.out", last_id="0")
    _, ev = entries[0]
    assert "peripheral" in ev.payload and "foveal" in ev.payload
    assert "fovea" in ev.payload
