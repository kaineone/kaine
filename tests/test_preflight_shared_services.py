# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for GPU gate shared-service handling in preflight."""


from kaine.cycle.preflight import GpuPreflightConfig, run_preflight
from kaine.hardware import set_allowed_devices


def _roomy_cuda1():
    return {
        "device": "cuda:1",
        "total_mib": 12288,
        "used_mib": 2048,
        "processes_visible": True,
        "processes": [],
        "unattributed_mib": 0,
        "note": "",
    }


def _run_preflight(
    monkeypatch, tmp_path, per_device, services_config=None, allowed=None
):
    monkeypatch.setattr(
        "kaine.cycle.preflight._device_free_vram",
        lambda *_a, **_k: [
            {
                "device": "cuda:0",
                "name": "GPU0",
                "total_vram_gb": 12,
                "free_vram_gb": 0.5,
            },
            {
                "device": "cuda:1",
                "name": "GPU1",
                "total_vram_gb": 12,
                "free_vram_gb": 10.0,
            },
        ],
    )
    monkeypatch.setattr(
        "kaine.cycle.preflight._probe_memory_state",
        lambda *_a, **_k: {"state": "known-discrete"},
    )
    monkeypatch.setattr("kaine.cycle.preflight._gpu_consumers", lambda _timeout: [])
    monkeypatch.setattr(
        "kaine.cycle.preflight._device_consumers",
        lambda _timeout: per_device,
    )
    monkeypatch.setattr("kaine.cycle.preflight._kaine_services_up", lambda: {})
    monkeypatch.setattr(
        "kaine.cycle.preflight._server_resident_models",
        lambda _url, _timeout: [],
    )
    monkeypatch.setattr(
        "kaine.hardware.allowed_devices",
        lambda: allowed if allowed is not None else ["cuda:0", "cuda:1"],
    )
    config = GpuPreflightConfig.from_section(
        {"enabled": True, "min_free_vram_gb": 1.0}
    )
    return run_preflight(
        config,
        keep_models=None,
        state_path=tmp_path / "pf.json",
        services_config=services_config,
    )


def test_preflight_names_shared_service_and_suggests_placement(monkeypatch, tmp_path):
    per_device = [
        {
            "device": "cuda:0",
            "total_mib": 12288,
            "used_mib": 11700,
            "processes_visible": True,
            "processes": [{"pid": 123, "name": "chatterbox", "used_mib": 2000}],
            "unattributed_mib": 0,
            "note": "",
        },
        _roomy_cuda1(),
    ]
    result = _run_preflight(
        monkeypatch,
        tmp_path,
        per_device,
        services_config={"chatterbox": {"shared": True}},
    )
    assert result.status == "blocked"
    msg = result.message
    assert "shared service 'chatterbox'" in msg
    assert "Suggested placement" in msg
    assert "cuda:1" in msg
    assert "Please close other GPU programs" not in msg
    config = GpuPreflightConfig.from_section({"enabled": True, "min_free_vram_gb": 1.0})
    assert config.override_env in msg


def test_preflight_non_shared_process_keeps_close_message(monkeypatch, tmp_path):
    per_device = [
        {
            "device": "cuda:0",
            "total_mib": 12288,
            "used_mib": 11700,
            "processes_visible": True,
            "processes": [{"pid": 456, "name": "chrome", "used_mib": 2000}],
            "unattributed_mib": 0,
            "note": "",
        },
        _roomy_cuda1(),
    ]
    result = _run_preflight(monkeypatch, tmp_path, per_device, services_config=None)
    assert "Please close other GPU programs" in result.message


def test_preflight_container_limited_visibility_note(monkeypatch, tmp_path):
    per_device = [
        {
            "device": "cuda:0",
            "total_mib": 12288,
            "used_mib": 11700,
            "processes_visible": False,
            "processes": [],
            "note": "consumer list is limited to the container",
            "unattributed_mib": 0,
        },
        _roomy_cuda1(),
    ]
    result = _run_preflight(monkeypatch, tmp_path, per_device, services_config=None)
    msg = result.message
    assert "consumer list is limited to the container" in msg
    assert "11700 MiB used of 12288 MiB" in msg
    assert "pid " not in msg


def test_preflight_suggestion_honors_allowed_devices(monkeypatch, tmp_path):
    set_allowed_devices(["cuda:0"])
    try:
        per_device = [
            {
                "device": "cuda:0",
                "total_mib": 12288,
                "used_mib": 11700,
                "processes_visible": True,
                "processes": [{"pid": 123, "name": "chatterbox", "used_mib": 2000}],
                "unattributed_mib": 0,
                "note": "",
            },
            _roomy_cuda1(),
        ]
        result = _run_preflight(
            monkeypatch,
            tmp_path,
            per_device,
            services_config={"chatterbox": {"shared": True}},
            allowed=["cuda:0"],
        )
        msg = result.message
        assert "Suggested placement" in msg
        assert "cuda:1" not in msg
    finally:
        set_allowed_devices(None)


def test_preflight_suggestion_skips_cpu_and_short_devices_in_allowed(monkeypatch, tmp_path):
    per_device = [
        {
            "device": "cuda:0",
            "total_mib": 12288,
            "used_mib": 11700,
            "processes_visible": True,
            "processes": [{"pid": 123, "name": "chatterbox", "used_mib": 2000}],
            "unattributed_mib": 0,
            "note": "",
        },
        _roomy_cuda1(),
    ]
    result = _run_preflight(
        monkeypatch,
        tmp_path,
        per_device,
        services_config={"chatterbox": {"shared": True}},
        allowed=["cpu", "cuda:0"],
    )
    msg = result.message
    assert result.status == "blocked"
    assert "Suggested placement" in msg
    assert "a lighter backend rung" in msg
    assert "to cpu, " not in msg
    assert "to cuda:0, " not in msg
    assert "cuda:1" not in msg
    config = GpuPreflightConfig.from_section({"enabled": True, "min_free_vram_gb": 1.0})
    assert config.override_env in msg
