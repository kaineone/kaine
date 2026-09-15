# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-host regression tests for KAINE.

Replays the golden fixtures in tests/fixtures/cross_host/hosts.json through
the wheel-index resolver and the GPU preflight gate so that resolver and
preflight decisions stay identical no matter which host runs the suite.
"""

import json
from pathlib import Path

import pytest

from kaine.wheel_index import Probes, resolve_index
from kaine.cycle import preflight as pf
from kaine.cycle.preflight import GpuPreflightConfig, run_preflight

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "cross_host" / "hosts.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
HOST_IDS = [f["name"] for f in FIXTURES]


@pytest.mark.parametrize("fixture", FIXTURES, ids=HOST_IDS)
def test_resolver_decision(fixture):
    """The wheel-index resolver matches the golden decision for each host."""
    probes = fixture["probes"]
    driver_cuda = probes["driver_cuda"]
    probes_obj = Probes(
        arch=probes["arch"],
        driver_cuda=tuple(driver_cuda) if driver_cuda is not None else None,
        compute_caps=tuple(tuple(cc) for cc in probes["compute_caps"]),
        memory_state=probes["memory_state"],
        notes=probes.get("notes", {}),
    )

    result = resolve_index(probes_obj)

    assert result["index_url"] == fixture["expected_resolver"]["index_url"]
    assert bool(result["warnings"]) == fixture["expected_resolver"]["warning"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=HOST_IDS)
def test_preflight_memory_state(fixture):
    """describe_host memory states map onto the preflight state taxonomy."""
    mapping = {
        "discrete": "known-discrete",
        "unified": "known-unified",
        "unknown": "unknown",
    }
    state = fixture["describe_host"]["memory"]["state"]

    assert mapping[state] == fixture["expected_preflight_state"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=HOST_IDS)
def test_preflight_gate_decision(fixture, monkeypatch, tmp_path):
    """The preflight gate pass/fail decision matches the golden expectation."""
    memory = fixture["describe_host"]["memory"]
    pools = memory.get("pools", [])
    state = memory["state"]

    if state == "discrete":
        memory_state = {
            "state": "known-discrete",
            "provenance": memory.get("evidence", ""),
            "annotation": "",
        }
    elif state == "unified":
        memory_state = {
            "state": "known-unified",
            "figure_gb": pools[0]["free_gb"] if pools else 0.0,
            "total_gb": pools[0]["total_gb"] if pools else 0.0,
            "provenance": pools[0].get("provenance", "") if pools else "",
            "annotation": "",
        }
    else:
        memory_state = {
            "state": "unknown",
            "annotation": memory.get("unknown_reason", ""),
            "provenance": "",
        }

    cuda_devices = fixture["describe_host"]["cuda_devices"]
    monkeypatch.setattr(pf, "_probe_memory_state", lambda *args, **kwargs: memory_state)
    monkeypatch.setattr(pf, "_device_free_vram", lambda *args, **kwargs: cuda_devices)
    monkeypatch.setattr(pf, "_gpu_consumers", lambda *args, **kwargs: [])
    monkeypatch.setattr(pf, "_kaine_services_up", lambda *args, **kwargs: {})
    monkeypatch.setattr(pf, "_server_resident_models", lambda *args, **kwargs: [])

    config = GpuPreflightConfig(enabled=True, min_free_vram_gb=2.0)
    result = run_preflight(config, state_path=tmp_path / "s.json")

    assert result.ok == fixture["expected_preflight_passes"]
    assert result.memory_state == fixture["expected_preflight_state"]