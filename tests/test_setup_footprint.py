# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from kaine.config import SHIPPED_CONFIG_PATH
from kaine.residency.budget import Domain
from kaine.residency.catalogue import Entry, load_catalogue
from kaine.residency.fit import Need, fit_report
from kaine.setup.footprint import (
    HostClassUnknown,
    ServiceNotMeasurable,
    _child_wrapper,
    _hf_cached,
    _measure_callable_in_child,
    _measure_service,
    _needs_for,
    _select_components,
    _target_audition_emotion,
    host_class,
    main,
)


def _raise_file_not_found(*args: Any, **kwargs: Any) -> Path:
    raise FileNotFoundError()


def _hermetic_selection(monkeypatch: Any) -> None:
    """Make component selection independent of the machine's installed models."""
    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached",
        lambda model_id, *, cache_dir=None: False,
    )
    monkeypatch.setattr(
        "kaine.setup.footprint._sherpa_present",
        lambda model_id, model_dir: False,
    )
    monkeypatch.setattr(
        "kaine.setup.footprint.resolve_model_dir",
        _raise_file_not_found,
    )


def _fake_torch(cuda_available: bool = False):
    class _Cuda:
        is_available = staticmethod(lambda: cuda_available)
        if cuda_available:
            current_device = staticmethod(lambda: 0)
            max_memory_reserved = staticmethod(lambda: 2 << 30)

    class _Torch:
        cuda = _Cuda()

    return _Torch()


def _fake_budgets():
    total = 16 << 30
    reserve = 1 << 30
    return (
        Domain(
            name="system",
            kind="system",
            total_bytes=total,
            available_bytes=total - reserve,
            reserve_bytes=reserve,
            budget_bytes=total - reserve,
            derivation="test",
        ),
    )


def _fake_measure(mapping):
    calls = []

    def measure(info, config, timeout=600.0):
        calls.append({"info": info, "config": config, "timeout": timeout})
        if info.name in mapping:
            return mapping[info.name]
        return (True, 123 << 20, None, None, False, "")

    return measure, calls


def _fake_service(mapping):
    calls = []

    def measure(url):
        calls.append(url)
        return mapping.get(url)

    return measure, calls


def _run(
    argv,
    config,
    tmp_path,
    capsys,
    *,
    measure=None,
    service=None,
    config_loader=None,
    budgets_fn=None,
    input_fn=None,
    stdin_isatty=None,
    torch_module=None,
):
    catalogue_path = tmp_path / "footprints.json"
    full_argv = ["--catalogue", str(catalogue_path)] + argv
    kwargs = {}
    if config_loader is None:
        kwargs["config_loader"] = lambda: config
    else:
        kwargs["config_loader"] = config_loader
    if measure is not None:
        kwargs["measure_fn"] = measure
    if service is not None:
        kwargs["service_fn"] = service
    if budgets_fn is not None:
        kwargs["budgets_fn"] = budgets_fn
    if input_fn is not None:
        kwargs["input_fn"] = input_fn
    if stdin_isatty is not None:
        kwargs["stdin_isatty"] = stdin_isatty
    if torch_module is not None:
        kwargs["torch_module"] = torch_module

    code = main(full_argv, **kwargs)
    captured = capsys.readouterr()
    return code, captured.out, captured.err, catalogue_path


def test_host_class_no_torch_importable(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert host_class() == "cpu"


def test_host_class_cuda_unavailable():
    assert host_class(torch_module=_fake_torch(False)) == "cpu"


def test_host_class_unified(monkeypatch):
    class _Cls:
        state = "unified"
        unknown_reason = None

    monkeypatch.setattr(
        "kaine.setup.footprint.classify_accelerator_memory",
        lambda index, torch=None: _Cls(),
    )
    assert host_class(torch_module=_fake_torch(True)) == "unified"


def test_host_class_discrete(monkeypatch):
    class _Cls:
        state = "discrete"
        unknown_reason = None

    monkeypatch.setattr(
        "kaine.setup.footprint.classify_accelerator_memory",
        lambda index, torch=None: _Cls(),
    )
    assert host_class(torch_module=_fake_torch(True)) == "discrete"


def test_host_class_unknown_raises(monkeypatch):
    class _Cls:
        state = "unknown"
        unknown_reason = "no telemetry"

    monkeypatch.setattr(
        "kaine.setup.footprint.classify_accelerator_memory",
        lambda index, torch=None: _Cls(),
    )
    with pytest.raises(HostClassUnknown) as excinfo:
        host_class(torch_module=_fake_torch(True))
    assert "no telemetry" in str(excinfo.value)


def test_main_host_class_unknown_returns_one_and_writes_nothing(
    capsys, tmp_path, monkeypatch
):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")

    def _broken(**kwargs):
        raise HostClassUnknown("no telemetry")

    monkeypatch.setattr("kaine.setup.footprint.host_class", _broken)

    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(
        ["--yes"],
        config,
        tmp_path,
        capsys,
        torch_module=_fake_torch(False),
    )
    assert code == 1
    assert (
        "cannot calibrate: the accelerator's memory class is unknown (no telemetry); nothing was recorded"
        in err
    )
    assert not cat.exists()


def test_disabled_modules_produce_no_components():
    config = {"modules": {"lingua": False, "mnemos": False, "topos": False}}
    assert _select_components(config) == []


def test_absent_sherpa_stt_has_fetch_command(monkeypatch):
    _hermetic_selection(monkeypatch)
    monkeypatch.setattr(
        "kaine.setup.footprint._sherpa_present", lambda model_id, model_dir: False
    )
    config = {
        "modules": {"audition": True},
        "audition": {
            "transcription_enabled": True,
            "backend": "sherpa_onnx",
            "sherpa_model_id": "custom-stt",
            "emotion_model_id": "",
        },
    }
    infos = [i for i in _select_components(config) if i.name == "audition.stt"]
    assert len(infos) == 1
    info = infos[0]
    assert info.kind == "absent"
    assert info.fetch_command == "python -m kaine.setup.speech_models --stt custom-stt"


def test_topos_internvideo_next_empty_dir_is_absent(tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    infos = [i for i in _select_components(config) if i.name == "topos.encoder"]
    assert len(infos) == 1
    assert infos[0].kind == "absent"
    assert infos[0].fetch_command == "python -m kaine.setup.internvideo_next --yes"


def test_topos_dinov2_absent_when_hf_cached_false(monkeypatch):
    _hermetic_selection(monkeypatch)
    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached", lambda model_id, *, cache_dir=None: False
    )
    config = {
        "modules": {"topos": True},
        "topos": {"encoder_backend": "dinov2"},
    }
    infos = [i for i in _select_components(config) if i.name == "topos.encoder"]
    assert infos[0].kind == "absent"
    assert infos[0].model_id == "facebook/dinov2-small"


def test_topos_dinov2_present_when_hf_cached_true(monkeypatch):
    _hermetic_selection(monkeypatch)
    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached", lambda model_id, *, cache_dir=None: True
    )
    config = {
        "modules": {"topos": True},
        "topos": {"encoder_backend": "dinov2", "encoder_model_id": "foo/bar"},
    }
    infos = [i for i in _select_components(config) if i.name == "topos.encoder"]
    assert infos[0].kind == "in_process"
    assert infos[0].model_id == "foo/bar"


def test_audition_emotion_absent_and_present_via_hf_cached(monkeypatch):
    _hermetic_selection(monkeypatch)
    config = {"modules": {"audition": True}}
    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached", lambda model_id, *, cache_dir=None: False
    )
    emotion_infos = [
        i for i in _select_components(config) if i.name == "audition.emotion"
    ]
    assert emotion_infos[0].kind == "absent"

    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached", lambda model_id, *, cache_dir=None: True
    )
    info = [
        i for i in _select_components(config) if i.name == "audition.emotion"
    ][0]
    assert info.kind == "in_process"
    assert info.backend == "emotion2vec"
    assert info.model_id == "emotion2vec/emotion2vec_plus_base"


def test_non_terminal_without_yes_returns_two(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")
    measure, calls = _fake_measure({})

    def _must_not_call(prompt: str) -> str:
        raise AssertionError("input should not be called")

    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(
        [],
        config,
        tmp_path,
        capsys,
        measure=measure,
        input_fn=_must_not_call,
        stdin_isatty=False,
    )
    assert code == 2
    assert "refusing to load models without consent; re-run with --yes" in err
    assert not calls


def test_consent_no_returns_zero(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")
    measure, calls = _fake_measure({})
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(
        [],
        config,
        tmp_path,
        capsys,
        measure=measure,
        input_fn=lambda prompt: "n",
        stdin_isatty=True,
    )
    assert code == 0
    assert "nothing was loaded" in out
    assert not calls


def test_consent_yes_measures(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")
    measure, calls = _fake_measure({})
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(
        [],
        config,
        tmp_path,
        capsys,
        measure=measure,
        input_fn=lambda prompt: "yes",
        stdin_isatty=True,
    )
    assert code == 0
    assert calls


def test_recording_writes_catalogue_entries(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")
    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached", lambda model_id, *, cache_dir=None: True
    )
    monkeypatch.setattr(
        "kaine.setup.footprint.resolve_embedding_config",
        lambda cfg: {
            "backend": "sentence_transformers",
            "model_id": "all-MiniLM",
            "device": "cpu",
            "model_path": None,
        },
    )
    config = {
        "modules": {"mnemos": True, "topos": True},
        "embedding": {"backend": "sentence_transformers", "model_id": "all-MiniLM"},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    mapping = {
        "embedding": (True, 100 << 20, None, None, False, ""),
        "topos.encoder": (True, 200 << 20, 1 << 30, "cuda:0", True, ""),
    }
    measure, calls = _fake_measure(mapping)
    code, out, err, cat = _run(
        ["--yes", "--only", "embedding", "--only", "topos.encoder"],
        config,
        tmp_path,
        capsys,
        measure=measure,
        torch_module=_fake_torch(False),
    )
    assert code == 0
    entries = load_catalogue(cat)
    assert len(entries) == 2
    by_name = {e.component: e for e in entries}
    assert by_name["embedding"].bytes == 100 << 20
    assert by_name["embedding"].backend == "sentence_transformers"
    assert by_name["embedding"].model_id == "all-MiniLM"
    assert by_name["embedding"].host_class == "cpu"
    assert by_name["topos.encoder"].bytes == 200 << 20
    assert by_name["topos.encoder"].device == "cuda:0"
    assert by_name["topos.encoder"].device_bytes == 1 << 30
    assert by_name["topos.encoder"].mapped is True


def test_failure_exits_one_and_writes_nothing(capsys, tmp_path):
    (tmp_path / "model.safetensors").write_text("x")
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    measure, _ = _fake_measure(
        {"topos.encoder": (False, None, None, None, False, "boom")}
    )
    code, out, err, cat = _run(
        ["--yes", "--only", "topos.encoder"],
        config,
        tmp_path,
        capsys,
        measure=measure,
        torch_module=_fake_torch(False),
    )
    assert code == 1
    assert "FAILED: boom" in out
    assert not cat.exists()


def test_ok_peak_none_fails_and_writes_nothing(capsys, tmp_path):
    (tmp_path / "model.safetensors").write_text("x")
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    measure, _ = _fake_measure(
        {"topos.encoder": (True, None, None, None, False, "")}
    )
    code, out, err, cat = _run(
        ["--yes", "--only", "topos.encoder"],
        config,
        tmp_path,
        capsys,
        measure=measure,
        torch_module=_fake_torch(False),
    )
    assert code == 1
    assert "FAILED: no measurement returned" in out
    assert not cat.exists()


def test_nothing_measured_writes_no_file(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(["--yes"], config, tmp_path, capsys)
    assert code == 0
    assert not cat.exists()


def test_lingua_external_service_inspected(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    svc, svc_calls = _fake_service({"http://localhost:1234": 100 << 20})
    config = {
        "modules": {"lingua": True},
        "lingua": {
            "backend": "openai",
            "model_id": "gpt-4o-mini",
            "chat_url": "http://localhost:1234",
        },
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "lingua"],
        config,
        tmp_path,
        capsys,
        service=svc,
        torch_module=_fake_torch(False),
    )
    assert code == 0
    assert "http://localhost:1234" in svc_calls
    assert "INSPECTED" in out
    assert "100.0 MiB" in out
    entries = load_catalogue(cat)
    entry = next(
        e for e in entries if e.component == "lingua" and e.backend == "openai"
    )
    assert entry.bytes == 100 << 20
    assert entry.device is None
    assert entry.mapped is False


def test_lingua_llama_cpp_not_measured(capsys, tmp_path):
    config = {
        "modules": {"lingua": True},
        "lingua": {"backend": "llama_cpp", "model_id": "qwen2.5-3b"},
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "lingua"], config, tmp_path, capsys
    )
    assert code == 0
    assert (
        "not measured: in-process llama_cpp organ calibration is not implemented yet"
        in out
    )


def test_audition_transcription_disabled_no_stt(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    measure, calls = _fake_measure({})
    config = {
        "modules": {"audition": True},
        "audition": {
            "transcription_enabled": False,
            "emotion_model_id": "",
        },
    }
    code, out, err, cat = _run(["--yes"], config, tmp_path, capsys, measure=measure)
    assert code == 0
    assert not calls
    assert "audition.stt" not in out


def test_sherpa_stt_and_tts_selected(monkeypatch, capsys, tmp_path):
    _hermetic_selection(monkeypatch)
    monkeypatch.setattr(
        "kaine.setup.footprint._sherpa_present", lambda model_id, model_dir: True
    )
    measure, calls = _fake_measure({})
    config = {
        "modules": {"audition": True, "vox": True},
        "audition": {
            "transcription_enabled": True,
            "backend": "sherpa_onnx",
            "sherpa_model_id": "custom-stt",
            "emotion_model_id": "",
        },
        "vox": {"backend": "sherpa_onnx", "sherpa_model_id": "custom-tts"},
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "audition.stt", "--only", "vox.tts"],
        config,
        tmp_path,
        capsys,
        measure=measure,
        torch_module=_fake_torch(False),
    )
    assert code == 0
    names = [c["info"].name for c in calls]
    assert names == ["audition.stt", "vox.tts"]
    assert calls[0]["info"].backend == "sherpa_onnx"
    assert calls[0]["info"].model_id == "custom-stt"
    assert calls[1]["info"].backend == "sherpa_onnx"
    assert calls[1]["info"].model_id == "custom-tts"


def test_service_not_running_message(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    svc, svc_calls = _fake_service({})
    config = {
        "modules": {"lingua": True},
        "lingua": {
            "backend": "openai",
            "model_id": "m",
            "chat_url": "http://localhost:1234",
        },
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "lingua"],
        config,
        tmp_path,
        capsys,
        service=svc,
        torch_module=_fake_torch(False),
    )
    assert code == 0
    assert (
        "not measured: http://localhost:1234 is not running or not visible to this user; start it and rerun"
        in out
    )
    assert not cat.exists()


def test_container_port_forwarder_not_measured(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    config = {
        "modules": {"lingua": True},
        "lingua": {
            "backend": "openai",
            "model_id": "m",
            "chat_url": "http://127.0.0.1:11435/v1",
        },
    }

    def _proxy(url: str) -> int:
        raise ServiceNotMeasurable(
            "the service runs behind a container port forwarder; measure it from inside the container"
        )

    code, out, err, cat = _run(
        ["--yes"],
        config,
        tmp_path,
        capsys,
        service=_proxy,
        torch_module=_fake_torch(False),
    )
    assert code == 0
    assert "container port forwarder" in out
    assert not cat.exists()


def _allocate_20mb() -> dict[str, Any]:
    _ = bytearray(20 << 20)
    return {}


@pytest.mark.skipif(sys.platform != "linux", reason="needs /proc/self/status")
def test_real_child_smoke():
    ok, peak, device_bytes, device, mapped, err = _measure_callable_in_child(
        _allocate_20mb
    )
    assert ok
    assert peak is not None
    assert 0 < peak < 1 << 30
    assert device_bytes is None
    assert device is None
    assert mapped is False
    assert err == ""


def _returns_then_sleeps() -> dict[str, Any]:
    threading.Thread(target=time.sleep, args=(60,), daemon=False).start()
    return {}


def test_measure_callable_in_child_uses_result_before_join_timeout():
    ok, peak, device_bytes, device, mapped, err = _measure_callable_in_child(
        _returns_then_sleeps, timeout=2.0
    )
    assert ok is True
    assert peak is not None
    # A deliberate stop after a valid report is named, never silent and never a crash.
    assert "stopped after reporting" in err


def test_emotion_degraded_load_raises():
    class FakeClf:
        def __init__(self, model_id: str, device: str) -> None:
            pass

        async def ensure_loaded(self) -> None:
            pass

        @property
        def loaded(self) -> bool:
            return False

    task = type(
        "_Task", (), {"model_id": "emotion2vec/base", "emotion_device": "cpu"}
    )()
    with pytest.raises(RuntimeError, match="loaded=False"):
        _target_audition_emotion(task, classifier_cls=FakeClf)


def test_target_audition_emotion_resolves_real_class(monkeypatch):
    calls = {}

    class FakeClf:
        def __init__(self, model_id: str, device: str) -> None:
            calls["init"] = (model_id, device)

        async def ensure_loaded(self) -> None:
            calls["ensure_loaded"] = True

        @property
        def loaded(self) -> bool:
            return True

        async def classify(self, wav: bytes, sample_rate: int) -> None:
            calls["classify"] = (wav, sample_rate)

    monkeypatch.setattr(
        "kaine.modules.audition.emotion.Emotion2vecClassifier", FakeClf
    )
    task = type(
        "_Task", (), {"model_id": "emotion2vec/base", "emotion_device": "cpu"}
    )()
    _target_audition_emotion(task, classifier_cls=None)
    assert calls["init"] == ("emotion2vec/base", "cpu")
    assert calls.get("ensure_loaded") is True
    assert calls.get("classify") is not None


def test_real_config_path_loads_and_stops_at_consent(capsys, tmp_path):
    # The real loader, with an empty operator overlay so the host's own operator
    # config cannot leak in. Without --yes on a non-TTY nothing may load.
    operator = tmp_path / "operator.toml"
    operator.write_text("")

    def _must_not_measure(*_a, **_k):
        raise AssertionError("nothing may be loaded without consent")

    code = main(
        [
            "--config", str(SHIPPED_CONFIG_PATH),
            "--operator-config", str(operator),
            "--profile", "thesis_test",
            "--catalogue", str(tmp_path / "c.json"),
        ],
        config_loader=None,
        measure_fn=_must_not_measure,
        service_fn=_must_not_measure,
        stdin_isatty=False,
    )
    out, err = capsys.readouterr()
    assert code == 2
    assert "refusing to load models without consent" in err
    # The plan was printed, so the config really loaded: thesis_test enables Lingua.
    assert "lingua (" in out
    assert not (tmp_path / "c.json").exists()


def test_embedding_import_error_not_measured(monkeypatch):
    monkeypatch.setattr(
        "kaine.setup.footprint.resolve_embedding_config",
        lambda cfg: {
            "backend": "numpy",
            "model_id": "my-emb",
            "device": "cpu",
            "model_path": None,
        },
    )

    def _raise(*args: Any, **kwargs: Any) -> Path:
        raise ImportError("no numpy backend")

    monkeypatch.setattr("kaine.setup.footprint.resolve_model_dir", _raise)
    config = {"modules": {"mnemos": True}}
    infos = _select_components(config)
    emb = next(i for i in infos if i.name == "embedding")
    assert emb.kind == "not_measured"
    assert emb.model_id == "my-emb"
    assert "not measured: ImportError: no numpy backend" in emb.message


def test_needs_for_ignores_other_model_ids():
    entries = [
        Entry(
            component="topos.encoder",
            backend="internvideo_next",
            model_id="old-model",
            bytes=50 << 20,
            device=None,
            device_bytes=None,
            mapped=False,
            host_class="cpu",
        ),
        Entry(
            component="topos.encoder",
            backend="internvideo_next",
            model_id="current-model",
            bytes=200 << 20,
            device="cuda:0",
            device_bytes=1 << 30,
            mapped=False,
            host_class="cpu",
        ),
        Entry(
            component="topos.encoder",
            backend="internvideo_next",
            model_id="current-model",
            bytes=150 << 20,
            device="cuda:0",
            device_bytes=2 << 30,
            mapped=False,
            host_class="cpu",
        ),
    ]
    info = type(
        "ComponentInfo",
        (),
        {
            "name": "topos.encoder",
            "kind": "in_process",
            "backend": "internvideo_next",
            "model_id": "current-model",
        },
    )
    needs = _needs_for(entries, [info], "cpu")
    assert len(needs) == 2
    sys_need = next(n for n in needs if n.domain == "system")
    assert sys_need.footprint_bytes == 200 << 20
    dev_need = next(n for n in needs if n.domain == "cuda:0")
    assert dev_need.footprint_bytes == 2 << 30


def test_fit_report_printed(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")
    monkeypatch.setattr(
        "kaine.setup.footprint._hf_cached", lambda model_id, *, cache_dir=None: True
    )
    monkeypatch.setattr(
        "kaine.setup.footprint.resolve_embedding_config",
        lambda cfg: {
            "backend": "sentence_transformers",
            "model_id": "all-MiniLM",
            "device": "cpu",
            "model_path": None,
        },
    )
    config = {
        "modules": {"mnemos": True, "topos": True},
        "embedding": {"backend": "sentence_transformers", "model_id": "all-MiniLM"},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    mapping = {
        "embedding": (True, 100 << 20, None, None, False, ""),
        "topos.encoder": (True, 200 << 20, None, None, False, ""),
    }
    measure, _ = _fake_measure(mapping)
    budgets = _fake_budgets()
    code, out, err, cat = _run(
        ["--yes"],
        config,
        tmp_path,
        capsys,
        measure=measure,
        budgets_fn=lambda: budgets,
        torch_module=_fake_torch(False),
    )
    assert code == 0
    expected_needs = [
        Need(
            component="embedding",
            domain="system",
            footprint_bytes=100 << 20,
            interactive=False,
            rung="sentence_transformers:all-MiniLM",
        ),
        Need(
            component="topos.encoder",
            domain="system",
            footprint_bytes=200 << 20,
            interactive=False,
            rung="internvideo_next:internvideo_next",
        ),
    ]
    first_line = fit_report(budgets, expected_needs, pin="lingua").lines()[0]
    assert first_line in out


def test_embedding_target_reads_weights_residency_as_a_property(monkeypatch):
    # The NumPy embedder exposes weights_residency as a property; calling it
    # would raise "'dict' object is not callable" on every real run.
    from kaine.setup import footprint

    class _Embedder:
        def __init__(self):
            self.encoded = []

        async def ensure_loaded(self):
            pass

        async def encode(self, text):
            self.encoded.append(text)
            return [0.0]

        @property
        def weights_residency(self):
            return {"mapped_bytes": 4096, "private_bytes": 0}

    made = _Embedder()
    monkeypatch.setattr("kaine.text_embedding.make_text_embedder", lambda cfg: made)
    task = footprint._ChildTask(component="embedding", backend="numpy", model_id="m")
    result = footprint._target_embedding(task)
    assert result == {"mapped": True}
    assert made.encoded == ["calibration"]


def _fake_conn():
    class Conn:
        def __init__(self):
            self.sent = None

        def send(self, obj):
            self.sent = obj

        def close(self):
            pass

    return Conn()


def test_child_wrapper_invalid_peak_equal_baseline(monkeypatch):
    conn = _fake_conn()
    monkeypatch.setattr(
        "kaine.setup.footprint._read_baseline_bytes", lambda: 100
    )
    monkeypatch.setattr(
        "kaine.setup.footprint._read_peak_bytes", lambda: 100
    )
    _child_wrapper(conn, lambda: {})
    assert conn.sent["ok"] is False
    assert conn.sent["error"] == "invalid measurement: peak <= baseline"
    assert conn.sent["peak_bytes"] is None
    assert conn.sent["device"] is None
    assert conn.sent["device_bytes"] is None


def test_main_corrupt_catalogue_is_named_then_replaced(capsys, tmp_path, monkeypatch):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")
    (tmp_path / "footprints.json").write_text("not json {")
    measure, calls = _fake_measure(
        {"topos.encoder": (True, 100 << 20, None, None, False, "")}
    )
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "topos.encoder"],
        config,
        tmp_path,
        capsys,
        measure=measure,
        torch_module=_fake_torch(False),
    )
    assert code == 0
    assert "could not be read; it will be replaced" in err
    assert calls
    [entry] = load_catalogue(cat)
    assert entry.component == "topos.encoder"


def test_main_unwritable_catalogue_says_nothing_recorded(
    capsys, tmp_path, monkeypatch
):
    _hermetic_selection(monkeypatch)
    (tmp_path / "model.safetensors").write_text("x")

    def _raise(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("kaine.setup.footprint.write_catalogue", _raise)
    measure, _ = _fake_measure(
        {"topos.encoder": (True, 100 << 20, None, None, False, "")}
    )
    config = {
        "modules": {"topos": True},
        "topos": {
            "encoder_backend": "internvideo_next",
            "encoder_local_dir": str(tmp_path),
        },
    }
    code, out, err, cat = _run(
        ["--yes", "--only", "topos.encoder"],
        config,
        tmp_path,
        capsys,
        measure=measure,
        torch_module=_fake_torch(False),
    )
    assert code == 1
    assert "error: cannot write the footprint catalogue:" in err
    assert "nothing was recorded" in err


def _make_fake_conn(port, pid):
    from types import SimpleNamespace

    return SimpleNamespace(
        status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=port), pid=pid
    )


class _FakeProcess:
    def __init__(self, pid, name, children=None, rss=0):
        self.pid = pid
        self._name = name
        self._children = children or []
        self._rss = rss

    def name(self):
        return self._name

    def children(self, recursive=False):
        return self._children

    def memory_info(self):
        return type("Mem", (), {"rss": self._rss})()


def test_service_unknown_listener_name_not_measured(monkeypatch):
    conn = _make_fake_conn(1234, 42)

    def _net_connections(*args, **kwargs):
        return [conn]

    def _process_factory(pid):
        return _FakeProcess(pid, "socat", rss=10 << 20)

    monkeypatch.setattr(
        "kaine.setup.footprint.psutil.net_connections", _net_connections
    )
    monkeypatch.setattr("kaine.setup.footprint.psutil.Process", _process_factory)

    with pytest.raises(
        ServiceNotMeasurable,
        match=r"the listener on port 1234 is 'socat', not a known model server",
    ):
        _measure_service("http://127.0.0.1:1234")


def test_service_known_listener_is_measured(monkeypatch):
    conn = _make_fake_conn(1234, 42)

    def _net_connections(*args, **kwargs):
        return [conn]

    def _process_factory(pid):
        return _FakeProcess(pid, "llama-server", rss=100 << 20)

    monkeypatch.setattr(
        "kaine.setup.footprint.psutil.net_connections", _net_connections
    )
    monkeypatch.setattr("kaine.setup.footprint.psutil.Process", _process_factory)
    # Never read a real /proc/<pid>/status for a fake pid.
    monkeypatch.setattr(
        "kaine.setup.footprint._process_peak_bytes", lambda p: p.memory_info().rss
    )

    result = _measure_service("http://127.0.0.1:1234")
    assert result == 100 << 20


def test_service_unrelated_listeners_not_measured(monkeypatch):
    def _net_connections(*args, **kwargs):
        return [_make_fake_conn(1234, 42), _make_fake_conn(1234, 99)]

    def _process_factory(pid):
        return _FakeProcess(pid, "llama-server", rss=100 << 20)

    monkeypatch.setattr(
        "kaine.setup.footprint.psutil.net_connections", _net_connections
    )
    monkeypatch.setattr("kaine.setup.footprint.psutil.Process", _process_factory)

    with pytest.raises(
        ServiceNotMeasurable,
        match=r"several unrelated processes listen on port 1234",
    ):
        _measure_service("http://127.0.0.1:1234")


def test_child_wrapper_zero_cuda_memory_records_no_device(monkeypatch):
    conn = _fake_conn()
    fake_cuda = type(
        "_Cuda",
        (),
        {
            "is_available": staticmethod(lambda: True),
            "current_device": staticmethod(lambda: 0),
            "max_memory_reserved": staticmethod(lambda: 0),
        },
    )()
    fake_torch = type("_Torch", (), {"cuda": fake_cuda})()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr("kaine.setup.footprint._read_baseline_bytes", lambda: 0)
    monkeypatch.setattr("kaine.setup.footprint._read_peak_bytes", lambda: 100)
    _child_wrapper(conn, lambda: {})
    assert conn.sent["ok"] is True
    assert conn.sent["peak_bytes"] == 100
    assert conn.sent["device"] is None
    assert conn.sent["device_bytes"] is None


def test_hf_cached_detects_present_layout(tmp_path):
    cache = tmp_path / "cache"
    snap = cache / "models--org--name" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    assert _hf_cached("org/name", cache_dir=cache) is True


def test_hf_cached_absent(tmp_path):
    assert _hf_cached("org/name", cache_dir=tmp_path) is False


def test_hf_cached_empty_snapshots_dir(tmp_path):
    cache = tmp_path / "cache"
    (cache / "models--org--name" / "snapshots").mkdir(parents=True)
    assert _hf_cached("org/name", cache_dir=cache) is False


def test_main_default_measure_path_is_wired(capsys, tmp_path, monkeypatch):
    # main() without an injected measure_fn must reach the real child path:
    # _measure_component -> _measure_callable_in_child(partial(_run_component_target, task)).
    from kaine.setup import footprint

    calls = []

    def fake_child(target, timeout=600.0):
        calls.append((target, timeout))
        return (True, 123 << 20, None, None, True, "")

    monkeypatch.setattr(footprint, "_measure_callable_in_child", fake_child)
    monkeypatch.setattr(footprint, "resolve_model_dir", lambda *a, **k: tmp_path)
    catalogue = tmp_path / "c.json"
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=16 << 30,
        available_bytes=8 << 30,
        reserve_bytes=1 << 30,
        budget_bytes=7 << 30,
        derivation="test",
    )
    code = main(
        ["--yes", "--only", "embedding", "--catalogue", str(catalogue)],
        config_loader=lambda: {"modules": {"chronos": True}},
        budgets_fn=lambda: (budget,),
        torch_module=_fake_torch(cuda_available=False),
    )
    assert code == 0
    assert len(calls) == 1
    target, timeout = calls[0]
    assert target.func is footprint._run_component_target
    assert target.args[0].component == "embedding"
    assert timeout == 600.0
    [entry] = load_catalogue(catalogue)
    assert entry.component == "embedding"
    assert entry.bytes == 123 << 20
    assert entry.mapped is True
