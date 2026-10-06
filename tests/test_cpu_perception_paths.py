# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import importlib.util
import io
import logging
import sys
import tomllib
import wave
from pathlib import Path

import numpy as np
import pytest
import torch

import kaine.hardware
import kaine.storage
from kaine.boot.factories.topos import make_topos
from kaine.modules.audition.emotion import (
    CATEGORIES,
    DEFAULT_EMOTION_MODEL_ID,
    Emotion2vecClassifier,
)
from kaine.modules.topos.encoder import DINOv2Encoder, InternVideoNextEncoder
from kaine.modules.topos.internvideo_next_loader import load_internvideo_next
from kaine.setup.internvideo_next import internvideo_next_download_cmd


def _tone_wav(frequency: int = 220, duration_s: int = 1, sample_rate: int = 16000) -> bytes:
    n = duration_s * sample_rate
    t = np.arange(n, dtype=np.float32) / sample_rate
    samples = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def _emotion_model_cached() -> bool:
    """Whether the default emotion2vec+ weights are in the local HF cache."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    found = try_to_load_from_cache(DEFAULT_EMOTION_MODEL_ID, "model.pt")
    return isinstance(found, str)


class _MockBus:
    pass


def _load_topos_section(tmp_path: Path, env: dict[str, str]) -> dict[str, object]:
    toml_path = tmp_path / "kaine.toml"
    toml_path.write_text(
        '[topos]\nencoder_local_dir = "state/models/internvideo_next_base_p14_res224_f16"\n'
    )
    with open(toml_path, "rb") as f:
        config = tomllib.load(f)
    normalized = kaine.storage.normalize_storage_paths(config, env)
    return normalized["topos"]


def _capture_topos(section: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    class CaptureTopos:
        def __init__(self, bus: object, *, entity_clock: object = None, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("kaine.modules.topos.module.Topos", CaptureTopos)
    make_topos(_MockBus(), section, entity_clock=None)
    return captured


@pytest.mark.asyncio
async def test_emotion2vec_cpu_load_and_classify():
    clf = Emotion2vecClassifier(device="cpu")
    # Reproduce the race seen in a multi-module process: another module loading
    # with torch_dtype=float16 switches the process-wide default dtype while
    # emotion2vec builds its model. The classifier must still run in float32.
    previous = torch.get_default_dtype()
    torch.set_default_dtype(torch.float16)
    try:
        await clf.load()
    finally:
        torch.set_default_dtype(previous)
    if not clf.funasr_available:
        # Skip only when the prerequisites are genuinely absent. With funasr
        # installed and the weights cached, a failed load (for example a
        # failed float32 cast) is the bug this test exists to catch.
        if importlib.util.find_spec("funasr") is None or not _emotion_model_cached():
            pytest.skip("funasr not installed or model not available locally")
        pytest.fail("emotion2vec+ failed to load on CPU with funasr and the weights present")
    audio = _tone_wav()
    result = await clf.classify(audio, sample_rate=16000)
    assert "inference_failed" not in result.raw
    assert result.category in CATEGORIES


def test_emotion2vec_cpu_casts_model_to_float32_after_dtype_race(monkeypatch: pytest.MonkeyPatch):
    class _FakeAutoModel:
        def __init__(
            self,
            *,
            model: str,
            device: str,
            hub: str,
            disable_update: bool,
            fp16: bool = False,
            bf16: bool = False,
        ) -> None:
            first = torch.nn.Linear(4, 4)
            torch.set_default_dtype(torch.float16)
            try:
                second = torch.nn.Linear(4, 4)
            finally:
                torch.set_default_dtype(torch.float32)
            self.model = torch.nn.Sequential(first, second)
            self.device = device

    fake_module = type("funasr", (), {"AutoModel": _FakeAutoModel})()
    monkeypatch.setitem(sys.modules, "funasr", fake_module)

    clf = Emotion2vecClassifier(device="cpu")
    asyncio.run(clf.load())
    assert clf.funasr_available is True
    tensors = list(clf._model.model.parameters()) + list(clf._model.model.buffers())
    assert tensors
    for t in tensors:
        if t.dtype.is_floating_point:
            assert t.dtype == torch.float32, f"expected float32, got {t.dtype}"


def test_emotion2vec_cpu_load_fails_when_float_cast_blocked(monkeypatch: pytest.MonkeyPatch):
    class _FakeAutoModel:
        def __init__(
            self,
            *,
            model: str,
            device: str,
            hub: str,
            disable_update: bool,
            fp16: bool = False,
            bf16: bool = False,
        ) -> None:
            first = torch.nn.Linear(4, 4)
            torch.set_default_dtype(torch.float16)
            try:
                second = torch.nn.Linear(4, 4)
            finally:
                torch.set_default_dtype(torch.float32)
            self.model = torch.nn.Sequential(first, second)
            self.device = device

    fake_module = type("funasr", (), {"AutoModel": _FakeAutoModel})()
    monkeypatch.setitem(sys.modules, "funasr", fake_module)
    monkeypatch.setattr(torch.nn.Module, "float", lambda self: self)

    clf = Emotion2vecClassifier(device="cpu")
    asyncio.run(clf.load())
    assert clf.funasr_available is False
    assert clf._model is None


def test_topos_encoder_resolves_weights_under_data_root(tmp_path: Path):
    kaine.storage.set_data_root(tmp_path)
    try:
        encoder = InternVideoNextEncoder()
        with pytest.raises(FileNotFoundError) as exc_info:
            asyncio.run(encoder.load())
        assert str(tmp_path) in str(exc_info.value)
    finally:
        kaine.storage.set_data_root(None)


def test_internvideo_next_download_cmd_uses_data_root(tmp_path: Path):
    kaine.storage.set_data_root(tmp_path)
    try:
        cmd = internvideo_next_download_cmd()
        idx = cmd.index("--local-dir")
        assert idx != -1 and idx + 1 < len(cmd)
        assert str(tmp_path) in cmd[idx + 1]
    finally:
        kaine.storage.set_data_root(None)


def test_resolve_device_logs_actual_fallback_cpu(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    monkeypatch.setattr(kaine.hardware, "_cuda_device_count", lambda: 0)
    with caplog.at_level(logging.WARNING, logger="kaine.hardware"):
        resolved = kaine.hardware.resolve_device("cuda:1")
    assert resolved == "cpu"
    assert any(record.message.endswith("falling back to cpu") for record in caplog.records)


def test_topos_encoder_follows_models_dir_set_after_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # The container sets KAINE_MODELS_DIR for the process; the encoder must read
    # it when it loads, not freeze the weights path when its module is imported.
    models = tmp_path / "models"
    monkeypatch.setenv("KAINE_MODELS_DIR", str(models))
    enc = InternVideoNextEncoder()
    with pytest.raises(FileNotFoundError) as excinfo:
        asyncio.run(enc.load())
    assert str(models) in str(excinfo.value)


def test_topos_loads_float32_on_cpu(monkeypatch: pytest.MonkeyPatch):
    import kaine.modules.topos.internvideo_next_loader as loader

    seen = {}

    def _capture(**kwargs: object) -> None:
        seen.update(kwargs)
        raise RuntimeError("captured")

    monkeypatch.setattr(loader, "load_internvideo_next", _capture)
    enc = InternVideoNextEncoder(device_preference="cpu")
    with pytest.raises(RuntimeError, match="captured"):
        asyncio.run(enc.load())
    assert seen["torch_dtype"] == torch.float32


def test_internvideo_next_download_cmd_reads_models_dir_at_call_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """KAINE_MODELS_DIR set after import (as in the container) must reach the
    setup fetch, not the import-time default."""
    target = tmp_path / "models-volume"
    monkeypatch.setenv("KAINE_MODELS_DIR", str(target))
    cmd = internvideo_next_download_cmd()
    local_dir = cmd[cmd.index("--local-dir") + 1]
    assert local_dir.startswith(str(target))


def test_internvideo_next_loader_casts_dtype_after_load(tmp_path: Path):
    class _FakeConfig:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> object:
            return object()

    class _FakeModel:
        from_pretrained_kwargs: dict[str, object] | None = None

        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> torch.nn.Module:
            cls.from_pretrained_kwargs = kwargs
            return torch.nn.Linear(2, 2)

    model = load_internvideo_next(
        weights_dir=tmp_path,
        device="cpu",
        torch_dtype=torch.float16,
        _classes=(_FakeConfig, _FakeModel),
    )
    assert _FakeModel.from_pretrained_kwargs is not None
    assert "torch_dtype" not in _FakeModel.from_pretrained_kwargs
    assert _FakeModel.from_pretrained_kwargs.get("dtype") is torch.float32
    assert model.weight.dtype == torch.float16


def test_resolve_dtype_fp16_on_cuda_and_xpu():
    assert kaine.hardware.resolve_dtype("cuda:0") == torch.float16
    assert kaine.hardware.resolve_dtype("cuda") == torch.float16
    assert kaine.hardware.resolve_dtype("xpu:0") == torch.float16
    assert kaine.hardware.resolve_dtype("xpu") == torch.float16
    assert kaine.hardware.resolve_dtype("cpu") == torch.float32


def test_topos_encoder_local_dir_uses_models_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app = tmp_path / "app"
    models = tmp_path / "models"
    env = {"KAINE_DATA_ROOT": str(app), "KAINE_MODELS_DIR": str(models)}
    section = _load_topos_section(tmp_path, env)
    captured = _capture_topos(section, monkeypatch)
    assert captured["encoder_weights_dir"] == str(models / "internvideo_next_base_p14_res224_f16")


def test_topos_encoder_local_dir_falls_back_to_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app = tmp_path / "app"
    env = {"KAINE_DATA_ROOT": str(app)}
    section = _load_topos_section(tmp_path, env)
    captured = _capture_topos(section, monkeypatch)
    assert captured["encoder_weights_dir"] == str(
        app / "state" / "models" / "internvideo_next_base_p14_res224_f16"
    )


def test_topos_encoder_local_dir_uses_models_dir_without_a_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    models = tmp_path / "models"
    section = _load_topos_section(tmp_path, {"KAINE_MODELS_DIR": str(models)})
    captured = _capture_topos(section, monkeypatch)
    assert captured["encoder_weights_dir"] == str(models / "internvideo_next_base_p14_res224_f16")


def test_no_data_root_and_no_models_dir_leaves_the_config_unchanged(tmp_path: Path):
    config = {"topos": {"encoder_local_dir": "state/models/x"}}
    assert kaine.storage.normalize_storage_paths(config, {}) is config


def test_internvideo_next_real_load_never_sets_fp16_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transformers = pytest.importorskip("transformers")
    from kaine.modules.topos import internvideo_next_loader as loader

    weights_dir = tmp_path / "weights"
    vendored_dir = tmp_path / "vendored"
    weights_dir.mkdir()
    vendored_dir.mkdir()

    cfg = transformers.BertConfig(
        vocab_size=16,
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=16,
        max_position_embeddings=16,
    )
    model = transformers.BertModel(cfg).half()
    model.save_pretrained(str(weights_dir))
    cfg.save_pretrained(str(vendored_dir))

    monkeypatch.setattr(loader, "vendored_code_dir", lambda: vendored_dir)

    calls: list[object] = []
    original_set_dtype = torch.set_default_dtype

    def _spy(dtype: object) -> None:
        calls.append(dtype)
        original_set_dtype(dtype)

    monkeypatch.setattr(torch, "set_default_dtype", _spy)

    # Control: prove the fixture triggers the float16 default-dtype flip.
    transformers.BertModel.from_pretrained(str(weights_dir))
    if torch.float16 not in calls:
        pytest.skip(
            "installed transformers does not flip the default dtype; "
            "skipping real-load race test"
        )
    torch.set_default_dtype(torch.float32)
    calls.clear()

    loaded = load_internvideo_next(
        weights_dir=weights_dir,
        device="cpu",
        torch_dtype=torch.float32,
        _classes=(transformers.BertConfig, transformers.BertModel),
        _telemetry_env={},
    )

    assert torch.float16 not in calls
    assert torch.get_default_dtype() == torch.float32
    for p in loaded.parameters():
        assert p.dtype == torch.float32
    assert loaded.training is False
    assert not any(p.requires_grad for p in loaded.parameters())


def test_dinov2_real_load_never_sets_fp16_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transformers = pytest.importorskip("transformers")
    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()

    cfg = transformers.Dinov2Config(
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=16,
        image_size=16,
        patch_size=8,
        num_channels=3,
    )
    model = transformers.Dinov2Model(cfg).half()
    model.save_pretrained(str(weights_dir))

    processor = transformers.BitImageProcessor(
        do_resize=True,
        size={"height": 16, "width": 16},
        do_center_crop=False,
        do_rescale=True,
        rescale_factor=1 / 255,
        do_normalize=True,
        image_mean=[0.5, 0.5, 0.5],
        image_std=[0.5, 0.5, 0.5],
    )
    processor.save_pretrained(str(weights_dir))

    calls: list[object] = []
    original_set_dtype = torch.set_default_dtype

    def _spy(dtype: object) -> None:
        calls.append(dtype)
        original_set_dtype(dtype)

    monkeypatch.setattr(torch, "set_default_dtype", _spy)

    # Control: prove the fixture triggers the float16 default-dtype flip.
    transformers.Dinov2Model.from_pretrained(str(weights_dir))
    if torch.float16 not in calls:
        pytest.skip(
            "installed transformers does not flip the default dtype; "
            "skipping real-load race test"
        )
    torch.set_default_dtype(torch.float32)
    calls.clear()

    enc = DINOv2Encoder(model_id=str(weights_dir), device_preference="cpu")
    asyncio.run(enc.load())
    assert enc._model is not None

    assert torch.float16 not in calls
    assert torch.get_default_dtype() == torch.float32
    for p in enc._model.parameters():
        assert p.dtype == torch.float32


def test_model_path_rejects_parent_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"KAINE_MODELS_DIR": "/some/models"}
    with pytest.raises(ValueError, match="must not contain"):
        kaine.storage._resolve_model_path(None, "state/models/../../x", env)
    resolved = kaine.storage._resolve_model_path(None, "state/models/a/b", env)
    assert resolved.startswith("/some/models")
