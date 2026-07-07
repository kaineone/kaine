# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 1 tests for the InternVideo-Next encoder foundation.

Covers the vendoring/provenance, the security-critical no-remote-code loader, the
``encoder_backend`` selector, and the setup-time weights fetch — all with fakes.
NOTHING here loads the real 182 MB model, imports the heavy vendored stack, or
touches the network / GPU (CI stays hermetic; the live load is a shakedown step).
"""
from __future__ import annotations

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

    # Both config and model loaded from the LOCAL dir with the security kwargs.
    for rec in (fake_config.calls[0], fake_model.calls[0]):
        assert rec["path"] == str(wdir)
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


def test_default_backend_is_dinov2_real_encoder():
    # Phase 1: the shipped default stays a real working encoder (no pretend default).
    assert DEFAULT_ENCODER_BACKEND == "dinov2"
    assert isinstance(make_encoder(), DINOv2Encoder)
    assert isinstance(make_encoder(None), DINOv2Encoder)


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


@pytest.mark.asyncio
async def test_internvideo_next_encoder_fails_loudly_not_fakely():
    enc = InternVideoNextEncoder()
    with pytest.raises(NotImplementedError, match="Phase 2"):
        await enc.load()
    with pytest.raises(NotImplementedError, match="Phase 2"):
        await enc.encode(object())
    with pytest.raises(RuntimeError, match="not loaded"):
        _ = enc.latent_dim


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
async def test_topos_defaults_to_dinov2(bus):
    from kaine.modules.topos import Topos

    topos = Topos(bus)
    assert isinstance(topos._encoder, DINOv2Encoder)


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
