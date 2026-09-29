# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import platform
import sys
from pathlib import Path

import pytest

import kaine
from kaine.residency import ALLOWED_KEYS, MemoryDomain, ResidencyBudget, load_catalogue
from kaine.residency.fit import Rung
from kaine.setup.footprint import (
    _measure_callable_in_child,
    host_class,
    main,
)


def _fake_budget(total_bytes: int | None = 16 << 30) -> ResidencyBudget:
    return ResidencyBudget(
        topology="cpu_only",
        system=MemoryDomain(
            name="system",
            total_bytes=total_bytes,
            available_bytes=(total_bytes - (1 << 30)) if total_bytes is not None else None,
            reserve_bytes=1 << 30,
            provenance="test",
        ),
        devices=(),
        notes=("test note",),
    )


def _fake_child(
    records: dict[str, tuple[bool, int | None, str]] | None = None,
) -> tuple:
    calls: list[dict] = []

    def measure(
        info: object, config: dict, timeout: float = 600.0
    ) -> tuple[bool, int | None, str]:
        calls.append({"info": info, "config": config, "timeout": timeout})
        if records is not None:
            return records.get(getattr(info, "name"), (True, 123 << 20, ""))
        return (True, 123 << 20, "")

    return measure, calls


def _fake_service(mapping: dict[str, int | None] | None = None) -> tuple:
    calls: list[str] = []

    def measure(url: str) -> int | None:
        calls.append(url)
        if mapping is None:
            return 100 << 20
        return mapping.get(url)

    return measure, calls


def _run(
    argv: list[str],
    config: dict,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    *,
    child: object = None,
    service: object = None,
    input_fn: object = None,
    isatty: bool | None = None,
    budget: ResidencyBudget | None = None,
) -> tuple[int, str, str, Path]:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    catalogue_path = tmp_path / "footprints.json"

    full_argv = ["--config-json", str(config_path), "--catalogue", str(catalogue_path)] + argv

    kwargs: dict = {"budget_fn": budget if budget is not None else _fake_budget}
    if child is not None:
        kwargs["measure_in_child"] = child
    if service is not None:
        kwargs["measure_service"] = service
    if input_fn is not None:
        kwargs["input_fn"] = input_fn
    if isatty is not None:
        kwargs["isatty"] = lambda: isatty

    code = main(full_argv, **kwargs)
    captured = capsys.readouterr()
    return code, captured.out, captured.err, catalogue_path


def test_lingua_external(capsys, tmp_path):
    svc, svc_calls = _fake_service({"http://localhost:1234": 100 << 20})
    config = {
        "modules": {"lingua": True},
        "lingua": {
            "backend": "openai",
            "model_id": "gpt-4o-mini",
            "chat_url": "http://localhost:1234",
        },
    }
    code, out, err, cat_path = _run(
        ["--yes", "--only", "lingua"], config, tmp_path, capsys, service=svc
    )
    assert code == 0
    assert "http://localhost:1234" in svc_calls
    assert "INSPECTED" in out
    assert "100.0 MiB" in out
    catalogue = load_catalogue(cat_path)
    entry = catalogue.get("lingua", "openai", "gpt-4o-mini", host_class(_fake_budget()))
    assert entry is not None
    assert entry.peak_bytes == 100 << 20
    assert entry.source == "calibration"


def test_lingua_llama_cpp_not_measured(capsys, tmp_path):
    config = {
        "modules": {"lingua": True},
        "lingua": {"backend": "llama_cpp", "model_id": "qwen2.5-3b"},
    }
    code, out, err, cat_path = _run(
        ["--yes", "--only", "lingua"], config, tmp_path, capsys
    )
    assert code == 0
    assert "not measured: in-process llama_cpp organ calibration is not implemented yet" in out


def test_audition_transcription_disabled_no_stt(capsys, tmp_path):
    child, calls = _fake_child()
    config = {
        "modules": {"audition": True},
        "audition": {"transcription_enabled": False},
    }
    code, out, err, cat_path = _run(["--yes"], config, tmp_path, capsys, child=child)
    assert code == 0
    assert not calls
    assert "audition.stt" not in out


def test_sherpa_stt_and_tts_rungs(capsys, tmp_path):
    child, calls = _fake_child()
    config = {
        "modules": {"audition": True, "vox": True},
        "audition": {
            "transcription_enabled": True,
            "backend": "sherpa_onnx",
            "sherpa_model_id": "custom-stt",
        },
        "vox": {"backend": "sherpa_onnx", "sherpa_model_id": "custom-tts"},
    }
    code, out, err, cat_path = _run(
        ["--yes", "--only", "audition.stt", "--only", "vox.tts"],
        config,
        tmp_path,
        capsys,
        child=child,
    )
    assert code == 0
    names = [c["info"].name for c in calls]
    assert names == ["audition.stt", "vox.tts"]
    assert calls[0]["info"].rung == Rung("sherpa_onnx", "custom-stt")
    assert calls[1]["info"].rung == Rung("sherpa_onnx", "custom-tts")


def test_embedder_when_mnemos_enabled(capsys, tmp_path):
    child, calls = _fake_child()
    config = {"modules": {"mnemos": True}}
    code, out, err, cat_path = _run(
        ["--yes", "--only", "embedder"], config, tmp_path, capsys, child=child
    )
    assert code == 0
    assert calls and calls[0]["info"].name == "embedder"


def test_topos_and_emotion_not_measured(capsys, tmp_path):
    config = {
        "modules": {"topos": True, "audition": True},
        "audition": {"transcription_enabled": False},
    }
    code, out, err, cat_path = _run(["--yes"], config, tmp_path, capsys)
    assert code == 0
    assert "topos.encoder" in out
    assert "audition.emotion" in out
    assert "not measured: calibration for this component is not implemented yet (task 2.2 follow-up)" in out


def test_consent_no_returns_zero(capsys, tmp_path):
    child, calls = _fake_child()
    config = {"modules": {"mnemos": True}}
    code, out, err, cat_path = _run(
        [], config, tmp_path, capsys, child=child, input_fn=lambda prompt: "n", isatty=True
    )
    assert code == 0
    assert "nothing was measured" in out
    assert not calls


def test_non_terminal_without_yes_returns_two(capsys, tmp_path):
    child, calls = _fake_child()

    def must_not_call(prompt: str) -> str:
        raise AssertionError("input should not be called")

    config = {"modules": {"mnemos": True}}
    code, out, err, cat_path = _run(
        [], config, tmp_path, capsys, child=child, input_fn=must_not_call, isatty=False
    )
    assert code == 2
    assert "terminal" in err
    assert not calls


def test_yes_measures_without_terminal(capsys, tmp_path):
    child, calls = _fake_child()
    config = {"modules": {"mnemos": True}}
    code, out, err, cat_path = _run(
        ["--yes"], config, tmp_path, capsys, child=child, isatty=False
    )
    assert code == 0
    assert calls


def test_recording_writes_catalogue_entry(capsys, tmp_path):
    child, calls = _fake_child({"embedder": (True, 123 << 20, "")})
    config = {"modules": {"mnemos": True}}
    code, out, err, cat_path = _run(
        ["--yes", "--only", "embedder"], config, tmp_path, capsys, child=child
    )
    assert code == 0
    raw = json.loads(cat_path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert len(raw["entries"]) == 1
    entry = raw["entries"][0]
    assert set(entry.keys()) == set(ALLOWED_KEYS)
    assert entry["component"] == "embedder"
    assert entry["backend"] == "numpy"
    assert entry["model_id"] == "default"
    assert entry["peak_bytes"] == 123 << 20
    assert entry["source"] == "calibration"
    assert entry["host_class"] == host_class(_fake_budget())
    assert entry["kaine_version"] == kaine.__version__


def test_failure_reports_failed_and_exits_one(capsys, tmp_path):
    child, calls = _fake_child({"embedder": (False, None, "boom")})
    config = {"modules": {"mnemos": True}}
    code, out, err, cat_path = _run(
        ["--yes", "--only", "embedder"], config, tmp_path, capsys, child=child
    )
    assert code == 1
    assert "failed: boom" in out
    raw = json.loads(cat_path.read_text(encoding="utf-8"))
    assert raw["entries"] == []


def test_service_not_running_message(capsys, tmp_path):
    svc, svc_calls = _fake_service({})
    config = {
        "modules": {"lingua": True},
        "lingua": {"backend": "openai", "chat_url": "http://localhost:1234"},
    }
    code, out, err, cat_path = _run(
        ["--yes", "--only", "lingua"], config, tmp_path, capsys, service=svc
    )
    assert code == 0
    assert (
        "not measured: http://localhost:1234 is not running or not visible to this user; start it and rerun"
        in out
    )
    raw = json.loads(cat_path.read_text(encoding="utf-8"))
    assert raw["entries"] == []


def test_fit_report_unknown_for_not_measured(capsys, tmp_path):
    config = {"modules": {"topos": True}}
    code, out, err, cat_path = _run(["--yes"], config, tmp_path, capsys)
    assert code == 0
    assert "topos.encoder" in out
    assert "unknown" in out.lower()


def test_host_class_formatting():
    known = ResidencyBudget(
        topology="discrete",
        system=MemoryDomain(
            name="system",
            total_bytes=8 << 30,
            available_bytes=7 << 30,
            reserve_bytes=1 << 30,
            provenance="test",
        ),
        devices=(),
        notes=(),
    )
    assert host_class(known) == f"discrete-8g-{platform.machine()}"

    unknown = ResidencyBudget(
        topology="cpu_only",
        system=MemoryDomain(
            name="system",
            total_bytes=None,
            available_bytes=None,
            reserve_bytes=1 << 30,
            provenance="test",
        ),
        devices=(),
        notes=(),
    )
    assert host_class(unknown) == f"cpu_only-unknown-{platform.machine()}"


def _allocate_50mb() -> int:
    return len(bytearray(50 << 20))


@pytest.mark.skipif(sys.platform != "linux", reason="needs /proc/self/status")
def test_real_child_smoke():
    ok, bytes_, err = _measure_callable_in_child(_allocate_50mb)
    assert ok
    assert bytes_ >= 40 << 20
    assert err == ""


def test_container_port_forwarder_is_not_measured(capsys, tmp_path):
    from kaine.setup.footprint import ServiceNotMeasurable

    def _proxy(url):
        raise ServiceNotMeasurable(f"{url} is published by a container port forwarder")

    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"modules": {"lingua": True}, "lingua": {"chat_url": "http://127.0.0.1:11435/v1", "model_id": "m"}}))
    cat = tmp_path / "fp.json"
    rc = main(
        ["--yes", "--config-json", str(cfg), "--catalogue", str(cat)],
        measure_service=_proxy,
        budget_fn=_fake_budget,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "container port forwarder" in out
    assert json.loads(cat.read_text())["entries"] == []


def test_corrupt_catalogue_is_a_clear_error(capsys, tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"modules": {"lingua": True}, "lingua": {"chat_url": "http://127.0.0.1:1/v1", "model_id": "m"}}))
    cat = tmp_path / "fp.json"
    cat.write_text("{not json")
    rc = main(
        ["--yes", "--config-json", str(cfg), "--catalogue", str(cat)],
        measure_service=lambda url: None,
        budget_fn=_fake_budget,
    )
    assert rc == 2
    assert "invalid JSON" in capsys.readouterr().err
