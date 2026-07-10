# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 1 tests for the InternVideo-Next encoder foundation.

Covers the vendoring/provenance, the security-critical no-remote-code loader, the
``encoder_backend`` selector, and the setup-time weights fetch — all with fakes.
NOTHING here loads the real 182 MB model, imports the heavy vendored stack, or
touches the network / GPU (CI stays hermetic; the live load is a shakedown step).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from kaine.modules.topos.encoder import (
    DEFAULT_ENCODER_BACKEND,
    DEFAULT_INTERNVIDEO_NEXT_MODEL_ID,
    DINOv2Encoder,
    Encoder,
    InternVideoNextEncoder,
    make_encoder,
)
from kaine.modules.topos.internvideo_next_loader import (
    DEFAULT_WEIGHTS_DIR,
    PINNED_REVISION,
    WEIGHTS_FILENAME,
    load_internvideo_next,
    vendored_code_dir,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VENDOR_DIR = _REPO_ROOT / "external" / "internvideo_next"


# --------------------------------------------------------------------------
# Vendoring / provenance
# --------------------------------------------------------------------------


def test_vendored_files_present():
    for name in (
        "modeling_internvideo_next.py",
        "modeling_config.py",
        "config.json",
        "preprocessor_config.json",
        "UPSTREAM",
        "__init__.py",
    ):
        assert (_VENDOR_DIR / name).is_file(), f"missing vendored file {name}"


def test_weights_not_vendored_into_git():
    # The 182 MB safetensors must NOT live under external/ (it is fetched to state/).
    assert not (_VENDOR_DIR / WEIGHTS_FILENAME).exists()


def test_pinned_revision_is_a_sha_and_consistent():
    assert re.fullmatch(r"[0-9a-f]{40}", PINNED_REVISION)
    upstream = (_VENDOR_DIR / "UPSTREAM").read_text()
    assert PINNED_REVISION in upstream, "UPSTREAM must record the pinned SHA"
    init = (_VENDOR_DIR / "__init__.py").read_text()
    assert PINNED_REVISION in init, "vendored __init__ must record the pinned SHA"


def test_upstream_declares_mit_and_no_remote_code_rationale():
    upstream = (_VENDOR_DIR / "UPSTREAM").read_text()
    assert "SPDX-License-Identifier: MIT" in upstream
    assert "MIT License" in upstream
    assert "trust_remote_code=False" in upstream


def test_vendored_code_dir_points_at_external_package():
    assert vendored_code_dir() == _VENDOR_DIR


# --------------------------------------------------------------------------
# Security-critical loader: no remote code, no runtime network
# --------------------------------------------------------------------------


class _FakeModel:
    """Minimal stand-in for a frozen transformers model."""

    def __init__(self):
        self.eval_called = False
        self.moved_to = None

    def eval(self):
        self.eval_called = True
        return self

    def parameters(self):
        return iter(())  # no params to freeze in the fake

    def to(self, device):
        self.moved_to = device
        return self


class _RecordingClass:
    """Fake config/model class recording every from_pretrained call."""

    calls: list[dict]

    def __init__(self, name):
        self.name = name
        self.calls = []

    def from_pretrained(self, path, **kwargs):
        self.calls.append({"path": path, "kwargs": kwargs})
        return _FakeModel() if self.name == "model" else {"config": True}


def test_loader_passes_trust_remote_code_false_and_local_only(tmp_path):
    wdir = tmp_path / "internvideo_next"
    wdir.mkdir()
    (wdir / WEIGHTS_FILENAME).write_text("stub")  # existence only

    fake_config = _RecordingClass("config")
    fake_model = _RecordingClass("model")
    env: dict[str, str] = {}

    model = load_internvideo_next(
        weights_dir=wdir,
        device="cpu",
        _classes=(fake_config, fake_model),
        _telemetry_env=env,
    )

    # Config loads from the VENDORED, reviewed, pinned in-tree package (config.json
    # is vendored, not re-downloaded); the weights load from the LOCAL fetch dir.
    # Both use the security kwargs.
    assert fake_config.calls[0]["path"] == str(vendored_code_dir())
    assert fake_model.calls[0]["path"] == str(wdir)
    for rec in (fake_config.calls[0], fake_model.calls[0]):
        assert rec["kwargs"]["trust_remote_code"] is False
        assert rec["kwargs"]["local_files_only"] is True
    # Telemetry disabled AND hub reachability forbidden before any load.
    assert env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert env["HF_HUB_OFFLINE"] == "1"
    # Frozen contract applied.
    assert isinstance(model, _FakeModel)
    assert model.eval_called is True
    assert model.moved_to == "cpu"


def test_loader_raises_when_weights_absent(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError, match="weights dir not found"):
        load_internvideo_next(
            weights_dir=missing,
            _classes=(_RecordingClass("config"), _RecordingClass("model")),
            _telemetry_env={},
        )


def test_loader_refuses_revision_mismatch(tmp_path):
    wdir = tmp_path / "iv"
    wdir.mkdir()
    (wdir / WEIGHTS_FILENAME).write_text("stub")
    (wdir / ".internvideo_next_revision").write_text("deadbeef" * 5)  # 40 hex, != pin
    with pytest.raises(RuntimeError, match="revision mismatch"):
        load_internvideo_next(
            weights_dir=wdir,
            _classes=(_RecordingClass("config"), _RecordingClass("model")),
            _telemetry_env={},
        )


def test_default_weights_dir_is_under_state(tmp_path):
    # Runtime loads from a git-ignored state/models dir, never the hub cache.
    assert DEFAULT_WEIGHTS_DIR.parts[0] == "state"
    assert DEFAULT_WEIGHTS_DIR.parts[1] == "models"


# --------------------------------------------------------------------------
# encoder_backend selector
# --------------------------------------------------------------------------


def test_default_backend_is_internvideo_next():
    # Phase 2: the temporally-native clip encoder is the shipped default; a
    # default install loads no Meta-owned model.
    assert DEFAULT_ENCODER_BACKEND == "internvideo_next"
    assert isinstance(make_encoder(), InternVideoNextEncoder)
    assert isinstance(make_encoder(None), InternVideoNextEncoder)
    # DINOv2 stays a selectable Apache-2.0 fallback.
    assert isinstance(make_encoder("dinov2"), DINOv2Encoder)


def test_selector_returns_internvideo_next_when_asked():
    enc = make_encoder("internvideo_next")
    assert isinstance(enc, InternVideoNextEncoder)
    assert enc.model_id == DEFAULT_INTERNVIDEO_NEXT_MODEL_ID
    assert enc.revision == PINNED_REVISION


def test_selector_case_insensitive_and_dinov2_model_id_override():
    assert isinstance(make_encoder("DINOv2"), DINOv2Encoder)
    enc = make_encoder("dinov2", model_id="facebook/dinov2-base")
    assert enc.model_id == "facebook/dinov2-base"


def test_selector_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown encoder_backend"):
        make_encoder("clip")


def test_internvideo_next_encoder_satisfies_protocol():
    assert isinstance(InternVideoNextEncoder(), Encoder)


def test_internvideo_next_clip_len_and_defaults():
    enc = InternVideoNextEncoder()
    assert enc.clip_len == 16
    assert enc.pooling == "attention"


@pytest.mark.asyncio
async def test_internvideo_next_latent_dim_requires_load():
    enc = InternVideoNextEncoder()
    with pytest.raises(RuntimeError, match="not loaded"):
        _ = enc.latent_dim


@pytest.mark.asyncio
async def test_internvideo_next_per_frame_encode_refused():
    # A clip encoder has no per-frame encode; it must direct to encode_clip
    # rather than silently encode one frame.
    enc = InternVideoNextEncoder()
    with pytest.raises(NotImplementedError, match="clip encoder"):
        await enc.encode(object())


def test_internvideo_next_rejects_unknown_pooling():
    with pytest.raises(ValueError, match="pooling"):
        InternVideoNextEncoder(pooling="softmax")


# --------------------------------------------------------------------------
# Setup-time weights fetch
# --------------------------------------------------------------------------


def test_download_cmd_pins_revision_and_local_dir():
    from kaine.setup.internvideo_next import (
        INTERNVIDEO_NEXT_REPO,
        internvideo_next_download_cmd,
    )

    cmd = internvideo_next_download_cmd()
    assert cmd[:3] == ["hf", "download", INTERNVIDEO_NEXT_REPO]
    assert WEIGHTS_FILENAME in cmd
    assert "--revision" in cmd and PINNED_REVISION in cmd
    i = cmd.index("--local-dir")
    assert cmd[i + 1] == str(DEFAULT_WEIGHTS_DIR)


def test_fetch_without_consent_runs_nothing_but_guides():
    from kaine.setup.internvideo_next import run_internvideo_next_download

    called = []
    result = run_internvideo_next_download(
        consent=False, runner=lambda *a, **k: called.append(a)
    )
    assert result.ok is False
    assert called == []  # no subprocess with consent=False
    assert "hf download" in result.detail


def test_fetch_success_with_mocked_runner():
    from kaine.setup.internvideo_next import run_internvideo_next_download

    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["check"] = kwargs.get("check")

        class _Proc:
            stdout = ""
            stderr = ""

        return _Proc()

    result = run_internvideo_next_download(consent=True, runner=fake_run)
    # hf may or may not be on PATH in CI; if absent the module reports honestly.
    if result.ok:
        assert recorded["cmd"][:2] == ["hf", "download"]
        assert recorded["check"] is True
        assert PINNED_REVISION in recorded["cmd"]
    else:
        assert "hf" in result.detail.lower()


# --------------------------------------------------------------------------
# Topos wiring: the selector reaches through the module + boot
# --------------------------------------------------------------------------


@pytest.fixture
async def bus():
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_topos_defaults_to_internvideo_next(bus):
    from kaine.modules.topos import Topos

    topos = Topos(bus)
    assert isinstance(topos._encoder, InternVideoNextEncoder)
    # The ring buffer is sized to the clip encoder's frame count.
    assert topos._clip_len == 16


@pytest.mark.asyncio
async def test_topos_dinov2_fallback_selectable(bus):
    from kaine.modules.topos import Topos

    topos = Topos(bus, encoder_backend="dinov2", encoder_model_id="facebook/dinov2-small")
    assert isinstance(topos._encoder, DINOv2Encoder)
    assert topos._encoder.model_id == "facebook/dinov2-small"
    assert topos._clip_len == 1


@pytest.mark.asyncio
async def test_topos_selects_internvideo_next_backend(bus):
    from kaine.modules.topos import Topos

    topos = Topos(bus, encoder_backend="internvideo_next")
    assert isinstance(topos._encoder, InternVideoNextEncoder)


def test_boot_make_topos_wires_backend():
    from kaine.boot import make_topos
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    topos = make_topos(b, {"encoder_backend": "internvideo_next"})
    assert isinstance(topos._encoder, InternVideoNextEncoder)


def test_boot_make_topos_threads_clip_knobs():
    from kaine.boot import make_topos
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    topos = make_topos(
        b,
        {
            "encoder_backend": "internvideo_next",
            "clip_len": 16,
            "clip_stride": 3,
            "clip_resolution": 224,
            "pooling": "mean",
        },
    )
    assert topos._clip_len == 16
    assert topos._clip_stride == 3
    assert topos._encoder.pooling == "mean"


# --------------------------------------------------------------------------
# Clip forward pass + pooling (fake torch model/processor — no weights, GPU,
# vendored-code deps, or network; validates the shape + pooling pipeline).
# --------------------------------------------------------------------------

torch = pytest.importorskip("torch")


def _pil(n: int = 8):
    from PIL import Image

    return [Image.new("RGB", (n, n), (100, 120, 140)) for _ in range(16)]


class _FakeIVModel:
    """Stands in for the frozen InternVideo-Next torch model.

    ``__call__`` mimics the native attention-pool head (→ ``[1, 768]``);
    ``extract_features`` mimics the patch-token output (``[1, 4096, 768]``)."""

    def __init__(self, dim: int = 768, tokens: int = 4096) -> None:
        self._dim = dim
        self._tokens = tokens
        self.forward_calls = 0
        self.extract_calls = 0

    def parameters(self):
        return iter(())  # frozen fake: no params → encoder skips the dtype cast

    def __call__(self, pixel_values):
        self.forward_calls += 1
        # A distinct constant per feature so pooling is observable.
        return torch.arange(self._dim, dtype=torch.float32).unsqueeze(0)

    def extract_features(self, pixel_values):
        self.extract_calls += 1
        base = torch.arange(self._dim, dtype=torch.float32)
        return base.view(1, 1, self._dim).expand(1, self._tokens, self._dim).clone()


class _FakeProc:
    """VideoMAE-style processor: emits pixel_values of shape [B, T, C, H, W]."""

    def __init__(self) -> None:
        self.last_nframes = 0

    def __call__(self, frames, return_tensors=None):  # noqa: ARG002
        self.last_nframes = len(frames)
        return {"pixel_values": torch.zeros(1, len(frames), 3, 8, 8)}


@pytest.mark.asyncio
async def test_attention_pooling_returns_768():
    enc = InternVideoNextEncoder(pooling="attention")
    model, proc = _FakeIVModel(), _FakeProc()
    await enc.load(_model=model, _processor=proc)
    assert enc.latent_dim == 768  # probed from a dummy 16-frame clip forward
    vec = await enc.encode_clip(_pil())
    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)
    # Native attention-pool head was used (forward), not extract_features.
    assert model.forward_calls >= 1 and model.extract_calls == 0
    # The processor was handed exactly clip_len frames.
    assert proc.last_nframes == 16


@pytest.mark.asyncio
async def test_mean_pooling_returns_768_via_extract_features():
    enc = InternVideoNextEncoder(pooling="mean")
    model, proc = _FakeIVModel(), _FakeProc()
    await enc.load(_model=model, _processor=proc)
    vec = await enc.encode_clip(_pil())
    assert len(vec) == 768
    # Mean pool goes through extract_features (patch tokens), not the head.
    assert model.extract_calls >= 1 and model.forward_calls == 0
    # mean over identical tokens == the per-feature value (arange).
    assert vec[0] == pytest.approx(0.0) and vec[1] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_encode_clip_rejects_wrong_frame_count():
    enc = InternVideoNextEncoder()
    await enc.load(_model=_FakeIVModel(), _processor=_FakeProc())
    with pytest.raises(ValueError, match="exactly clip_len"):
        await enc.encode_clip([object()] * 5)


@pytest.mark.asyncio
async def test_encoder_load_uses_offline_loader_not_automodel(monkeypatch):
    """The production load path (no injected model) goes through the vendored,
    no-remote-code loader — NOT AutoModel(trust_remote_code=True). Asserts the
    offline loader is invoked with the pinned revision, and no hub reachability."""
    import kaine.modules.topos.internvideo_next_loader as loader_mod

    recorded: dict = {}

    def fake_loader(**kwargs):
        recorded.update(kwargs)
        return _FakeIVModel()

    monkeypatch.setattr(loader_mod, "load_internvideo_next", fake_loader)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

    enc = InternVideoNextEncoder()
    # _model=None → real loader path; _processor injected to skip VideoMAE config.
    await enc.load(_processor=_FakeProc())
    assert recorded["revision"] == PINNED_REVISION
    assert enc.latent_dim == 768
    # Offline enforced before any hub call.
    assert os.environ.get("HF_HUB_OFFLINE") == "1"


# --------------------------------------------------------------------------
# Topos clip ring buffer + strided cadence + zero-persistence + dim guard
# --------------------------------------------------------------------------


class _FakeClipEncoder:
    """A clip_len=16 encoder double: one deterministic 768-d vector per clip."""

    model_id = "fake/internvideo-next"
    latent_dim = 768
    clip_len = 16

    def __init__(self) -> None:
        self.clip_calls = 0

    async def load(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def encode(self, image):  # noqa: ARG002
        raise NotImplementedError("clip encoder")

    async def encode_clip(self, frames):
        assert len(frames) == self.clip_len
        self.clip_calls += 1
        # Vary the vector across clips so change detection sees motion.
        return [float(self.clip_calls)] + [0.0] * 767


def _frame(n=8):
    from PIL import Image

    return Image.new("RGB", (n, n), (10, 20, 30))


@pytest.mark.asyncio
async def test_no_report_until_ring_buffer_fills(bus):
    from kaine.modules.topos import Topos

    enc = _FakeClipEncoder()
    topos = Topos(bus, encoder=enc, clip_stride=1)
    for _ in range(15):  # clip_len - 1
        rid = await topos.process_frame(_frame())
        assert rid == ""  # warmup: nothing published
    entries = await bus.read("topos.out", last_id="0")
    assert entries == []
    assert enc.clip_calls == 0
    # The 16th frame fills the buffer → first report.
    rid = await topos.process_frame(_frame())
    assert rid
    entries = await bus.read("topos.out", last_id="0")
    assert len(entries) == 1
    _, ev = entries[0]
    assert len(ev.payload["latent"]) == 768
    assert ev.payload["encoder_model_id"] == "fake/internvideo-next"


@pytest.mark.asyncio
async def test_one_clip_latent_per_stride_not_per_frame(bus):
    from kaine.modules.topos import Topos

    enc = _FakeClipEncoder()
    topos = Topos(bus, encoder=enc, clip_stride=3)
    reports = 0
    for _ in range(16 + 9):  # fill (16) then 9 more frames
        rid = await topos.process_frame(_frame())
        if rid:
            reports += 1
    # Reports at frames 16, 19, 22, 25 → 4 clip latents from 25 frames.
    assert reports == 4
    assert enc.clip_calls == 4


@pytest.mark.asyncio
async def test_serialize_excludes_frame_ring_buffer(bus):
    from kaine.modules.topos import Topos

    enc = _FakeClipEncoder()
    topos = Topos(bus, encoder=enc, clip_stride=1)
    for _ in range(20):
        await topos.process_frame(_frame())
    state = topos.serialize()
    # Only identity (+ optional forward-model summary) is persisted; no frames.
    assert set(state) <= {"encoder_model_id", "forward_model", "buffer_summary"}
    assert state["encoder_model_id"] == "fake/internvideo-next"


@pytest.mark.asyncio
async def test_foveation_rejected_with_clip_encoder(bus):
    from kaine.modules.topos import Topos

    with pytest.raises(ValueError, match="clip_len == 1|per-frame encoder"):
        Topos(bus, encoder=_FakeClipEncoder(), foveation_enabled=True)


@pytest.mark.asyncio
async def test_deserialize_discards_mismatched_forward_model(bus):
    """A 384/other-dim forward-model checkpoint must be discarded (not raised)
    when the running encoder latent_dim differs (dim cascade guard §3/task 4.2)."""
    from kaine.modules.topos import Topos
    from kaine.modules.topos.forward import LatentForwardModel

    # A checkpoint sized to a 768-dim encoder.
    big = LatentForwardModel(latent_dim=768, units=256, seed=1)
    big_state = big.state_dict()

    # A running Topos whose forward model is sized to a 4-dim encoder.
    small_enc = FakeSmall()
    topos = Topos(bus, encoder=small_enc, forward_prediction=True)
    topos._forward_model = LatentForwardModel(latent_dim=4, units=16, seed=2)
    before = topos._forward_model.state_dict()

    # Must NOT raise; must discard the mismatched checkpoint.
    topos.deserialize({"encoder_model_id": small_enc.model_id, "forward_model": big_state})

    after = topos._forward_model.state_dict()
    assert after == before  # weights untouched (checkpoint discarded)


class FakeSmall:
    model_id = "fake/small"
    latent_dim = 4
    clip_len = 1

    async def load(self):
        return None

    async def shutdown(self):
        return None

    async def encode(self, image):  # noqa: ARG002
        return [0.1, 0.2, 0.3, 0.4]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


# --------------------------------------------------------------------------
# Opt-in real-encoder test (task 6.3). Requires a CUDA host, the [internvideo]
# extra (einops/timm/flash_attn/easydict), and the fetched weights. Skipped
# unless KAINE_TOPOS_RUN_REAL_ENCODER=1 — CI never loads the 182 MB model.
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("KAINE_TOPOS_RUN_REAL_ENCODER") != "1",
    reason="set KAINE_TOPOS_RUN_REAL_ENCODER=1 (+ weights, CUDA, [internvideo]) to run",
)
@pytest.mark.asyncio
async def test_real_internvideo_next_produces_768_from_16_frame_clip():
    from PIL import Image

    if not (DEFAULT_WEIGHTS_DIR / WEIGHTS_FILENAME).exists():
        pytest.skip("InternVideo-Next weights not fetched; run kaine.setup.internvideo_next")

    enc = InternVideoNextEncoder()
    await enc.load()
    try:
        assert enc.clip_len == 16
        assert enc.latent_dim == 768
        frames = [Image.new("RGB", (224, 224), (i * 15 % 255, 128, 64)) for i in range(16)]
        vec = await enc.encode_clip(frames)
        assert len(vec) == 768
        assert all(isinstance(v, float) for v in vec)
    finally:
        await enc.shutdown()
