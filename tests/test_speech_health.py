# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the sherpa-onnx speech health probes and dependency specs."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest

import kaine.nexus.health.probes as probes_mod
import kaine.setup.speech_models as _speech_models_mod
from kaine.nexus.health.config import build_dependency_specs


@pytest.fixture
def _patch_speech_models(monkeypatch):
    monkeypatch.setattr(_speech_models_mod, "DEFAULT_STT", "moonshine-base-en")
    monkeypatch.setattr(_speech_models_mod, "DEFAULT_TTS", "kokoro-en")
    monkeypatch.setattr(
        _speech_models_mod, "model_dir", lambda model_id: Path(f"/fake/models/{model_id}")
    )


@pytest.fixture(autouse=True)
def _clear_sherpa_memo():
    probes_mod.clear_sherpa_probe_memo()
    yield
    probes_mod.clear_sherpa_probe_memo()


@pytest.fixture(autouse=True)
def _restore_module_constants():
    original_wait = probes_mod.SHERPA_PROBE_WAIT_S
    original_timeout = probes_mod.SHERPA_PROBE_CHILD_TIMEOUT_S
    yield
    probes_mod.set_sherpa_probe_wait(original_wait)
    probes_mod.SHERPA_PROBE_CHILD_TIMEOUT_S = original_timeout


def _specs(audition_cfg=None, vox_cfg=None):
    return build_dependency_specs(
        redis_cfg={"host": "127.0.0.1", "port": 6379},
        qdrant_cfg={},
        qdrant_secret_key=None,
        redis_password=None,
        lingua_cfg={},
        audition_cfg=audition_cfg or {},
        vox_cfg=vox_cfg or {},
        nous_cfg={},
        state_encryption_cfg=None,
    )


def _spec_named(specs, name):
    matches = [s for s in specs if s.name == name]
    assert len(matches) == 1
    return matches[0]


def _up_runner(detail: str):
    calls = []

    def _child(kind, args):
        calls.append((kind, args))
        return probes_mod.UP, detail

    return _child, calls


def _down_runner(detail: str):
    calls = []

    def _child(kind, args):
        calls.append((kind, args))
        return probes_mod.DOWN, detail

    return _child, calls


def test_probe_sherpa_stt_up_when_child_reports_up(monkeypatch):
    runner, calls = _up_runner("loaded and transcribed a test clip")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == probes_mod.UP
    assert "loaded and transcribed a test clip" in detail
    assert len(calls) == 1


def test_probe_sherpa_stt_down_when_child_reports_down(monkeypatch):
    runner, calls = _down_runner("FileNotFoundError: missing encoder_model.ort")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(
            model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2
        )
    )
    assert status == probes_mod.DOWN
    assert "FileNotFoundError" in detail
    assert "missing encoder_model.ort" in detail


def test_probe_sherpa_tts_up_when_child_reports_up(monkeypatch):
    runner, calls = _up_runner("loaded and synthesized a test word")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_tts(
            model_dir="/fake/tts",
            model_id="kokoro-en",
            speaker_id=0,
            num_threads=2,
        )
    )
    assert status == probes_mod.UP
    assert "loaded and synthesized a test word" in detail
    assert len(calls) == 1


def test_probe_sherpa_tts_down_when_child_reports_down(monkeypatch):
    runner, calls = _down_runner("FileNotFoundError: missing model.int8.onnx")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_tts(
            model_dir="/fake/tts",
            model_id="kokoro-en",
            speaker_id=0,
            num_threads=2,
        )
    )
    assert status == probes_mod.DOWN
    assert "FileNotFoundError" in detail
    assert "missing model.int8.onnx" in detail


def test_probe_sherpa_tts_down_on_empty_audio(monkeypatch):
    runner, calls = _down_runner("RuntimeError: synthesized audio was empty")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_tts(
            model_dir="/fake/tts",
            model_id="kokoro-en",
            speaker_id=0,
            num_threads=2,
        )
    )
    assert status == probes_mod.DOWN
    assert "empty" in detail.lower()


def test_probe_sherpa_stt_memo_reuses_up_result(monkeypatch):
    runner, calls = _up_runner("loaded and transcribed a test clip")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == probes_mod.UP
    first_calls = len(calls)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == probes_mod.UP
    assert len(calls) == first_calls
    assert "verified" in detail


def test_probe_sherpa_stt_memo_reuses_down_result(monkeypatch):
    runner, calls = _down_runner("FileNotFoundError: missing encoder_model.ort")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == probes_mod.DOWN
    first_calls = len(calls)
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == probes_mod.DOWN
    assert len(calls) == first_calls
    assert "retry in" in detail


def test_probe_sherpa_stt_memo_retries_after_window(monkeypatch):
    class _FakeTime:
        def __init__(self, now: float) -> None:
            self.now = now

        def monotonic(self) -> float:
            return self.now

    fake_time = _FakeTime(1000.0)
    monkeypatch.setattr(probes_mod, "time", fake_time)
    runner, calls = _down_runner("FileNotFoundError: missing encoder_model.ort")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)
    status, _ = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == probes_mod.DOWN
    first_calls = len(calls)
    fake_time.now += 61.0
    status, _ = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="moonshine-base-en", num_threads=2)
    )
    assert status == probes_mod.DOWN
    assert len(calls) == first_calls + 1


def test_probe_sherpa_stt_slow_load_returns_degraded_and_single_flight(
    monkeypatch, tmp_path
):
    model_dir = str(tmp_path / "model")
    p = Path(model_dir)
    p.mkdir()
    (p / "model.onnx").write_text("x")

    block = threading.Event()
    calls = []

    def _child(kind, args):
        calls.append((kind, args))
        block.wait()
        return probes_mod.UP, "loaded and transcribed a test clip"

    monkeypatch.setattr(probes_mod, "_run_probe_child", _child)
    probes_mod.set_sherpa_probe_wait(0.1)

    try:
        async def _main():
            first = await asyncio.wait_for(
                probes_mod.probe_sherpa_stt(
                    model_dir=model_dir, model_id="custom", num_threads=2
                ),
                timeout=2.0,
            )
            assert first[0] == probes_mod.DEGRADED
            assert "in progress" in first[1].lower()
            assert len(calls) == 1

            second = await probes_mod.probe_sherpa_stt(
                model_dir=model_dir, model_id="custom", num_threads=2
            )
            assert second[0] == probes_mod.DEGRADED
            assert len(calls) == 1

            block.set()
            third = await probes_mod.probe_sherpa_stt(
                model_dir=model_dir, model_id="custom", num_threads=2
            )
            assert third[0] == probes_mod.UP
            assert "verified" in third[1]

        asyncio.run(_main())
    finally:
        block.set()


def test_probe_sherpa_stt_up_dropped_on_mtime_change(monkeypatch, tmp_path):
    model_dir = str(tmp_path / "model")
    p = Path(model_dir)
    p.mkdir()
    model_file = p / "model.onnx"
    model_file.write_text("x")

    runner, calls = _up_runner("loaded and transcribed a test clip")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)

    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir=model_dir, model_id="custom", num_threads=2)
    )
    assert status == probes_mod.UP
    first_calls = len(calls)

    new_mtime = time.time() + 3600
    os.utime(model_file, (new_mtime, new_mtime))

    status2, detail2 = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir=model_dir, model_id="custom", num_threads=2)
    )
    assert len(calls) == first_calls + 1
    assert status2 == probes_mod.UP
    # A changed file forces a fresh load, so this is not a remembered result.
    assert "verified" not in detail2


def test_probe_sherpa_stt_down_rechecked_early_on_new_file(
    monkeypatch, tmp_path
):
    class _FakeTime:
        def __init__(self, now: float) -> None:
            self.now = now

        def monotonic(self) -> float:
            return self.now

    fake_time = _FakeTime(1000.0)
    monkeypatch.setattr(probes_mod, "time", fake_time)

    model_dir = str(tmp_path / "model")
    p = Path(model_dir)
    p.mkdir()
    (p / "model.onnx").write_text("x")

    runner, calls = _down_runner("FileNotFoundError: missing encoder_model.ort")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)

    status, _ = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir=model_dir, model_id="custom", num_threads=2)
    )
    assert status == probes_mod.DOWN
    first_calls = len(calls)

    fake_time.now += 5.0
    (p / "new.onnx").write_text("y")

    status2, detail2 = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir=model_dir, model_id="custom", num_threads=2)
    )
    assert status2 == probes_mod.DOWN
    assert len(calls) == first_calls + 1
    assert "missing encoder_model.ort" in detail2


def test_clear_sherpa_probe_memo_resets_both_maps(monkeypatch, tmp_path):
    model_dir = str(tmp_path / "model")
    p = Path(model_dir)
    p.mkdir()
    (p / "model.onnx").write_text("x")

    runner, calls = _up_runner("loaded and transcribed a test clip")
    monkeypatch.setattr(probes_mod, "_run_probe_child", runner)

    status, _ = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir=model_dir, model_id="custom", num_threads=2)
    )
    assert status == probes_mod.UP
    assert len(calls) == 1

    key = ("stt", model_dir, "custom", None, 2)
    with probes_mod._SHERPA_PROBE_LOCK:
        assert key in probes_mod._SHERPA_PROBE_MEMO

    probes_mod.clear_sherpa_probe_memo()

    with probes_mod._SHERPA_PROBE_LOCK:
        assert key not in probes_mod._SHERPA_PROBE_MEMO
        assert not probes_mod._SHERPA_INFLIGHT

    status2, _ = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir=model_dir, model_id="custom", num_threads=2)
    )
    assert len(calls) == 2
    assert status2 == probes_mod.UP


def test_probe_child_process_exits_nonzero(monkeypatch):
    monkeypatch.setattr(probes_mod, "_CHILD_SCRIPT", "import os; os._exit(255)")
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="x", num_threads=1)
    )
    assert status == probes_mod.DOWN
    assert "255" in detail


def test_probe_child_process_times_out(monkeypatch):
    monkeypatch.setattr(probes_mod, "SHERPA_PROBE_CHILD_TIMEOUT_S", 1.0)
    monkeypatch.setattr(
        probes_mod,
        "_CHILD_SCRIPT",
        "import time; time.sleep(5)",
    )
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="x", num_threads=1)
    )
    assert status == probes_mod.DOWN
    assert "exceeded" in detail.lower()


def test_probe_child_process_prints_json_up(monkeypatch):
    monkeypatch.setattr(
        probes_mod,
        "_CHILD_SCRIPT",
        'import json; print(json.dumps({"status": "up", "detail": "child ok"}))',
    )
    status, detail = asyncio.run(
        probes_mod.probe_sherpa_stt(model_dir="/fake/stt", model_id="x", num_threads=1)
    )
    assert status == probes_mod.UP
    assert detail == "child ok"


def test_model_fingerprint_ignores_subtree_files(tmp_path):
    model_dir = str(tmp_path / "model")
    p = Path(model_dir)
    p.mkdir()
    (p / "top.txt").write_text("x")

    fp1 = probes_mod._model_fingerprint(model_dir, model_id="unknown")

    sub = p / "sub"
    sub.mkdir()
    for i in range(10):
        (sub / f"{i}.txt").write_text("noise")

    fp2 = probes_mod._model_fingerprint(model_dir, model_id="unknown")
    assert fp1 == fp2


def test_set_sherpa_probe_wait_round_trip():
    original = probes_mod.get_sherpa_probe_wait()
    probes_mod.set_sherpa_probe_wait(99.5)
    assert probes_mod.get_sherpa_probe_wait() == 99.5
    probes_mod.set_sherpa_probe_wait(original)


def test_dependency_specs_sherpa_onnx_audition_row(_patch_speech_models):
    specs = _specs(
        audition_cfg={"backend": "sherpa_onnx", "transcription_enabled": True}
    )
    names = {s.name for s in specs}
    assert "sherpa-onnx (Moonshine)" in names
    assert "Speaches (STT)" not in names


def test_dependency_specs_normalised_sherpa_onnx_audition_row(_patch_speech_models):
    specs = _specs(
        audition_cfg={"backend": " Sherpa_ONNX ", "transcription_enabled": True}
    )
    names = {s.name for s in specs}
    assert "sherpa-onnx (Moonshine)" in names
    assert "Speaches (STT)" not in names


def test_dependency_specs_empty_audition_backend_default(_patch_speech_models):
    specs = _specs(audition_cfg={"backend": "", "transcription_enabled": True})
    names = {s.name for s in specs}
    assert "Speaches (STT)" in names
    assert "sherpa-onnx (Moonshine)" not in names


def test_dependency_specs_default_audition_row(_patch_speech_models):
    specs = _specs()
    names = {s.name for s in specs}
    assert "Speaches (STT)" in names
    assert "sherpa-onnx (Moonshine)" not in names


def test_dependency_specs_sherpa_onnx_vox_row(_patch_speech_models):
    specs = _specs(vox_cfg={"backend": "sherpa_onnx"})
    names = {s.name for s in specs}
    assert "sherpa-onnx (Kokoro)" in names
    assert "Chatterbox (TTS)" not in names


def test_dependency_specs_empty_vox_backend_default(_patch_speech_models):
    specs = _specs(vox_cfg={"backend": ""})
    names = {s.name for s in specs}
    assert "Chatterbox (TTS)" in names
    assert "sherpa-onnx (Kokoro)" not in names


def test_dependency_specs_default_vox_row(_patch_speech_models):
    specs = _specs()
    names = {s.name for s in specs}
    assert "Chatterbox (TTS)" in names
    assert "sherpa-onnx (Kokoro)" not in names


def test_dependency_specs_unknown_audition_backend(_patch_speech_models):
    specs = _specs(audition_cfg={"backend": "whisper"})
    row = _spec_named(specs, "Audition backend 'whisper'")
    status, detail = asyncio.run(row.probe())
    assert status == probes_mod.DEGRADED
    assert "unknown [audition].backend" in detail


def test_dependency_specs_unknown_vox_backend(_patch_speech_models):
    specs = _specs(vox_cfg={"backend": "whisper"})
    row = _spec_named(specs, "Vox backend 'whisper'")
    status, detail = asyncio.run(row.probe())
    assert status == probes_mod.DEGRADED
    assert "unknown [vox].backend" in detail


def test_tier1_profile_uses_sherpa_onnx_speech():
    import tomllib

    profile = Path("config/profiles/tier1.toml").read_text(encoding="utf-8")
    data = tomllib.loads(profile)
    assert data["tier"]["unsupported_modules"] == []
    assert data["audition"]["backend"] == "sherpa_onnx"
    assert data["vox"]["backend"] == "sherpa_onnx"
    assert not any(".wav" in str(v) for v in _all_string_values(data))


def _all_string_values(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_string_values(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _all_string_values(item)
