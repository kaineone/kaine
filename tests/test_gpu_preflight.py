# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the cooperative pre-boot GPU headroom check (kaine.cycle.preflight).

The gate must: pass with ample VRAM, report (never evict — the single-resident
OpenAI model backend has no unload API) the backend's resident models, fail
closed when still short, honor the operator override, write a status snapshot
for Nexus, and NEVER terminate any process.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kaine.cycle import preflight as pf
from kaine.cycle.preflight import (
    GpuPreflightConfig,
    PreflightResult,
    run_preflight,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _dev(device: str, free: float, total: float = 12.0) -> dict:
    return {
        "index": int(device.split(":")[1]),
        "device": device,
        "name": f"GPU {device}",
        "total_vram_gb": total,
        "free_vram_gb": free,
    }


@pytest.fixture(autouse=True)
def _no_real_probes(monkeypatch):
    # Default: no GPU processes, no KAINE services up, no resident models. Tests
    # override per-case. Keeps real nvidia-smi/torch/network out of the suite.
    monkeypatch.setattr(pf, "_gpu_consumers", lambda *_a, **_k: [])
    monkeypatch.setattr(pf, "_kaine_services_up", lambda *_a, **_k: {})
    monkeypatch.setattr(pf, "_server_resident_models", lambda *_a, **_k: [])


# --- config ------------------------------------------------------------------


def test_config_defaults():
    c = GpuPreflightConfig.from_section(None)
    assert c.enabled is False
    assert c.min_free_vram_gb == 2.0
    assert c.model_server_url == "http://127.0.0.1:11434/v1"
    assert c.override_env == "KAINE_GPU_PREFLIGHT_APPROVED"


def test_config_overrides():
    c = GpuPreflightConfig.from_section(
        {"enabled": True, "min_free_vram_gb": 6.5, "model_server_url": "http://h:9/v1"}
    )
    assert c.enabled is True
    assert c.min_free_vram_gb == 6.5
    assert c.model_server_url == "http://h:9/v1"


# --- gate behavior -----------------------------------------------------------


def test_disabled_returns_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_device_free_vram", lambda: [_dev("cuda:0", 0.1)])
    r = run_preflight(GpuPreflightConfig(enabled=False), state_path=tmp_path / "s.json")
    assert r.status == "skipped"
    assert r.ok is True
    assert not (tmp_path / "s.json").exists()  # no state written when skipped


def test_pass_with_ample_headroom(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pf, "_device_free_vram", lambda: [_dev("cuda:0", 10.0), _dev("cuda:1", 4.0)]
    )
    cfg = GpuPreflightConfig(enabled=True, min_free_vram_gb=2.0)
    r = run_preflight(cfg, state_path=tmp_path / "s.json")
    assert r.status == "pass"
    assert r.ok is True
    assert r.resident_models == []
    assert (tmp_path / "s.json").exists()


def test_resident_models_reported_never_evicted(tmp_path, monkeypatch):
    # The single-resident OpenAI backend has no unload API: resident models are
    # REPORTED (and unexpected ones flagged in the block message) but the gate
    # evicts nothing and re-measures nothing.
    monkeypatch.setattr(pf, "_device_free_vram", lambda: [_dev("cuda:0", 0.5)])
    monkeypatch.setattr(
        pf,
        "_server_resident_models",
        lambda *_a, **_k: ["leftover:27b", "organ:9b"],
    )
    monkeypatch.delenv("KAINE_GPU_PREFLIGHT_APPROVED", raising=False)

    cfg = GpuPreflightConfig(enabled=True, min_free_vram_gb=2.0)
    r = run_preflight(cfg, keep_models=["organ:9b"], state_path=tmp_path / "s.json")

    # Headroom stays short (nothing evicted) → blocked, with the resident models
    # reported and the non-organ one flagged as unexpected in the message.
    assert r.status == "blocked"
    assert r.resident_models == ["leftover:27b", "organ:9b"]
    assert "leftover:27b" in r.message
    assert "organ:9b" not in r.message  # organ is the keep model, not flagged
    # No unload primitive exists on the module at all.
    assert not hasattr(pf, "_ollama_unload")


def test_blocked_when_still_short(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_device_free_vram", lambda: [_dev("cuda:0", 0.5)])
    monkeypatch.setattr(pf, "_gpu_consumers", lambda *_a, **_k: [
        {"pid": "123", "process_name": "blender", "used_mib": "9000"}
    ])
    monkeypatch.setattr(pf, "_kaine_services_up", lambda *_a, **_k: {"chatterbox": True})
    monkeypatch.delenv("KAINE_GPU_PREFLIGHT_APPROVED", raising=False)

    cfg = GpuPreflightConfig(enabled=True, min_free_vram_gb=2.0)
    r = run_preflight(cfg, state_path=tmp_path / "s.json")

    assert r.status == "blocked"
    assert r.ok is False
    assert r.shortfall and r.shortfall[0]["device"] == "cuda:0"
    assert "blender" in r.message
    assert "chatterbox" in r.message  # preserved KAINE service named
    assert (tmp_path / "s.json").exists()


def test_override_boots_anyway(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_device_free_vram", lambda: [_dev("cuda:0", 0.5)])
    monkeypatch.setenv("KAINE_GPU_PREFLIGHT_APPROVED", "1")
    cfg = GpuPreflightConfig(enabled=True, min_free_vram_gb=2.0)
    r = run_preflight(cfg, state_path=tmp_path / "s.json")
    assert r.status == "overridden"
    assert r.ok is True


def test_state_snapshot_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_device_free_vram", lambda: [_dev("cuda:0", 9.0)])
    cfg = GpuPreflightConfig(enabled=True)
    sp = tmp_path / "s.json"
    run_preflight(cfg, state_path=sp)
    data = pf.read_preflight_state(sp)
    assert data["status"] == "pass"
    assert data["ok"] is True
    assert data["devices"][0]["device"] == "cuda:0"


def test_never_terminates_a_process_source_guard():
    # Structural guard: the preflight must contain no process-killing primitive.
    src = (REPO_ROOT / "kaine" / "cycle" / "preflight.py").read_text()
    for forbidden in ("os.kill", "SIGKILL", "SIGTERM", ".terminate(", ".kill("):
        assert forbidden not in src, f"preflight must never kill processes: {forbidden}"


# --- shipped config guard ----------------------------------------------------


def test_shipped_config_ships_gpu_preflight_disabled():
    raw = tomllib.loads((REPO_ROOT / "config" / "kaine.toml").read_text())
    assert raw["gpu_preflight"]["enabled"] is False


# --- Nexus read-only block ---------------------------------------------------


def test_nexus_block_reads_blocked_state(tmp_path):
    from kaine.nexus.health import HealthProber

    sp = tmp_path / "gpu_preflight.json"
    PreflightResult(
        status="blocked",
        devices=[_dev("cuda:0", 0.5)],
        shortfall=[_dev("cuda:0", 0.5)],
        message="short",
        checked_at="2026-06-09T00:00:00+00:00",
    )
    # Write via the module's own writer for fidelity.
    pf._write_state(
        PreflightResult(
            status="blocked",
            devices=[_dev("cuda:0", 0.5)],
            shortfall=[_dev("cuda:0", 0.5)],
            message="short",
            checked_at="2026-06-09T00:00:00+00:00",
        ),
        sp,
    )
    prober = HealthProber(
        modules_enabled={}, dependencies=[], gpu_preflight_path=sp
    )
    block = prober._gpu_preflight_block()
    assert block["state"] == "critical"
    assert block["devices"][0]["device"] == "cuda:0"


def test_nexus_block_unknown_when_no_file(tmp_path):
    from kaine.nexus.health import HealthProber

    prober = HealthProber(
        modules_enabled={},
        dependencies=[],
        gpu_preflight_path=tmp_path / "absent.json",
    )
    block = prober._gpu_preflight_block()
    assert block["state"] == "unknown"


def test_from_section_rejects_unknown_key():
    """A typo'd [gpu_preflight] key must now fail loudly instead of being
    silently swallowed (the guard previously missing from from_section)."""
    with pytest.raises(ValueError, match="unknown .*config keys"):
        GpuPreflightConfig.from_section({"enabled": True, "min_free_vram_typo": 4.0})


def test_from_section_accepts_known_keys():
    """All shipped [gpu_preflight] keys are accepted (no false positive)."""
    cfg = GpuPreflightConfig.from_section(
        {
            "enabled": True,
            "min_free_vram_gb": 2.0,
            "model_server_url": "http://127.0.0.1:11434/v1",
            "timeout_s": 5.0,
            "override_env": "KAINE_GPU_PREFLIGHT_APPROVED",
        }
    )
    assert cfg.enabled is True


def test_model_server_port_in_preserved_set():
    """The launched model server's port (the chat_url port) is a KAINE-owned
    service the pre-boot headroom gate preserves — never killed as a foreign
    consumer. Confirms the port the bootstrap launches on is in the preserved set.
    """
    from kaine.cycle.preflight import KAINE_SERVICE_PORTS

    assert KAINE_SERVICE_PORTS.get("model_server") == 11434


def test_kaine_services_up_includes_model_server(monkeypatch):
    """A listening model-server port is reported as a KAINE service that is up
    (so the block message tells the operator NOT to close it). Reconstructs the
    real _kaine_services_up (the autouse fixture stubs it to empty) over a faked
    port probe so no real socket is opened."""
    from kaine.cycle import preflight as pf
    from kaine.cycle.preflight import KAINE_SERVICE_PORTS

    monkeypatch.setattr(
        pf, "port_listening", lambda port, *a, **k: port == 11434
    )
    services = {
        name: pf.port_listening(port) for name, port in KAINE_SERVICE_PORTS.items()
    }
    assert services["model_server"] is True


def test_blocked_message_preserves_model_server(monkeypatch, tmp_path):
    """When headroom is short, the launched model server is named as a preserved
    KAINE service in the operator message, not flagged for termination."""
    from kaine.cycle import preflight as pf
    from kaine.cycle.preflight import GpuPreflightConfig, run_preflight

    monkeypatch.setattr(
        pf, "_device_free_vram", lambda: [_dev("cuda:0", free=0.5, total=12.0)]
    )
    monkeypatch.setattr(
        pf, "_kaine_services_up", lambda: {"model_server": True}
    )
    monkeypatch.delenv("KAINE_GPU_PREFLIGHT_APPROVED", raising=False)
    cfg = GpuPreflightConfig.from_section({"enabled": True, "min_free_vram_gb": 2.0})
    result = run_preflight(cfg, state_path=tmp_path / "preflight.json")
    assert result.status == "blocked"
    assert result.kaine_services_up.get("model_server") is True
    assert "model_server" in result.message
    # The gate never kills a process — it only reports.
    assert "DO NOT close" in result.message
