# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the hardware-related setup steps."""
from __future__ import annotations

import pytest

from kaine.setup.hardware_steps import (
    consent_step,
    device_step,
    fit_check,
    inventory_step,
)
from kaine.setup.steps import (
    OWNED_KEYS,
    Field,
    Step,
    StepContext,
    owned_changes,
    parse_answer,
    run_step,
)
from kaine.setup.wizard import propose_device_assignments


def test_parse_answer_bool():
    f = Field("x", "?", "bool", default=True)
    assert parse_answer(f, "y") == (True, None)
    assert parse_answer(f, "Yes") == (True, None)
    assert parse_answer(f, "no") == (False, None)
    assert parse_answer(f, "FALSE") == (False, None)
    assert parse_answer(f, "maybe")[1] is not None


def test_parse_answer_int():
    f = Field("x", "?", "int", default=1)
    assert parse_answer(f, "4") == (4, None)
    assert parse_answer(f, "x")[1] == "must be an integer"
    assert parse_answer(f, "") == (1, None)


def test_parse_answer_choice():
    f = Field("x", "?", "choice", default="a", choices=("a", "b"))
    assert parse_answer(f, "a") == ("a", None)
    assert parse_answer(f, "c")[1] is not None


def test_parse_answer_multichoice():
    f = Field(
        "x", "?", "multichoice", default=("a",), choices=("a", "b", "c")
    )
    assert parse_answer(f, "a,b") == (["a", "b"], None)
    assert parse_answer(f, "b,a,b") == (["b", "a"], None)
    assert parse_answer(f, "a,d")[1] is not None
    assert parse_answer(f, "") == (("a",), None)


def test_parse_answer_text():
    f = Field("x", "?", "text", default="")
    assert parse_answer(f, " hello ") == ("hello", None)


def test_parse_answer_validate():
    f = Field("x", "?", "int", default=1, validate=lambda v: None if v <= 3 else "too big")
    assert parse_answer(f, "2") == (2, None)
    assert parse_answer(f, "5")[1] == "too big"


def test_run_step_reasks_and_falls_back():
    called: list[str] = []
    out: list[str] = []

    def bad_input(prompt: str) -> str:
        called.append(prompt)
        return "not-an-int"

    step = Step(
        id="s",
        title="Title",
        explanation=lambda _ctx: ["expl"],
        fields=lambda _ctx: (
            Field("n", "value", "int", default=7),
        ),
        applies=lambda _ctx: True,
        apply=lambda _ctx, _answers: None,
    )
    result = run_step(
        step,
        StepContext(config={}, host={}, extra={}),
        input_fn=bad_input,
        out=out.append,
        defaults=False,
    )
    assert result == {"n": 7}
    assert len(called) == 3
    assert any("using the default: 7" in line for line in out)


def test_run_step_defaults_no_input():
    called = False

    def input_fn(_prompt: str) -> str:
        nonlocal called
        called = True
        return ""

    step = Step(
        id="s",
        title="Title",
        explanation=lambda _ctx: [],
        fields=lambda _ctx: (Field("n", "value", "int", default=9),),
        applies=lambda _ctx: True,
        apply=lambda _ctx, _answers: None,
    )
    result = run_step(
        step,
        StepContext(config={}, host={}, extra={}),
        input_fn=input_fn,
        out=lambda _s: None,
        defaults=True,
    )
    assert result == {"n": 9}
    assert not called


@pytest.fixture
def patch_ram(monkeypatch):
    monkeypatch.setattr("kaine.setup.hardware_steps.total_ram_gb", lambda: 32.0)


def test_inventory_lists_rocm_not_cuda(patch_ram):
    host = {
        "backend": "rocm",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "Radeon",
                "total_vram_gb": 16.0,
                "free_vram_gb": 14.0,
            }
        ],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 8,
        "memory": {"state": "discrete"},
    }
    out: list[str] = []
    run_step(
        inventory_step,
        StepContext(config={}, host=host, extra={}),
        input_fn=lambda _p: "",
        out=out.append,
        defaults=True,
    )
    text = "".join(out)
    assert "cuda:0 (rocm)" in text
    assert "no CUDA" not in text
    assert "no accelerator found" not in text


def test_inventory_cpu_only_shows_no_accelerator(patch_ram):
    host = {
        "backend": "cpu",
        "cuda_devices": [],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 4,
        "memory": {"state": "discrete"},
    }
    out: list[str] = []
    run_step(
        inventory_step,
        StepContext(config={}, host=host, extra={}),
        input_fn=lambda _p: "",
        out=out.append,
        defaults=True,
    )
    text = "".join(out)
    assert "no accelerator found — KAINE will run on the CPU" in text


def test_inventory_shows_consumers(patch_ram):
    host = {
        "backend": "cuda",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "GPU",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            }
        ],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 4,
        "memory": {"state": "discrete"},
    }
    consumers = [
        {
            "device": "cuda:0",
            "processes": [{"pid": 123, "name": "python", "used_mib": 1024}],
            "note": "busy",
        }
    ]
    out: list[str] = []
    run_step(
        inventory_step,
        StepContext(config={}, host=host, extra={"consumers": consumers}),
        input_fn=lambda _p: "",
        out=out.append,
        defaults=True,
    )
    text = "".join(out)
    assert "pid 123 python — 1024 MiB" in text
    assert "busy" in text


def test_consent_defaults_allow_every_accelerator_and_cpu(patch_ram):
    host = {
        "backend": "cuda",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "A",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            },
            {
                "device": "cuda:1",
                "name": "B",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            },
        ],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 8,
        "memory": {"state": "discrete"},
    }
    ctx = StepContext(config={}, host=host, extra={})
    run_step(
        consent_step,
        ctx,
        input_fn=lambda _p: "",
        out=lambda _s: None,
        defaults=True,
    )
    assert ctx.config["hardware"]["allowed_devices"] == ["cuda:0", "cuda:1", "cpu"]
    assert ctx.config["hardware"]["cpu_threads"] == 4


def test_consent_records_selected_devices(patch_ram):
    host = {
        "backend": "cuda",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "A",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            },
            {
                "device": "cuda:1",
                "name": "B",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            },
        ],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 8,
        "memory": {"state": "discrete"},
    }
    answers = ["cuda:1,cpu", ""]
    idx = 0

    def input_fn(_p: str) -> str:
        nonlocal idx
        ans = answers[idx]
        idx += 1
        return ans

    ctx = StepContext(config={}, host=host, extra={})
    run_step(
        consent_step,
        ctx,
        input_fn=input_fn,
        out=lambda _s: None,
        defaults=False,
    )
    assert ctx.config["hardware"]["allowed_devices"] == ["cuda:1", "cpu"]
    assert ctx.config["hardware"]["cpu_threads"] == 4


def test_consent_cpu_threads_out_of_range_falls_back(patch_ram):
    host = {
        "backend": "cpu",
        "cuda_devices": [],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 4,
        "memory": {"state": "discrete"},
    }

    def input_fn(_p: str) -> str:
        return "99"

    ctx = StepContext(config={}, host=host, extra={})
    out: list[str] = []
    run_step(
        consent_step,
        ctx,
        input_fn=input_fn,
        out=out.append,
        defaults=False,
    )
    assert ctx.config["hardware"]["cpu_threads"] == 2
    assert any("using the default: 2" in line for line in out)


def _host_two_gpus() -> dict[str, object]:
    return {
        "backend": "cuda",
        "device": "cuda",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "A",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            },
            {
                "device": "cuda:1",
                "name": "B",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            },
        ],
        "xpu_devices": [],
        "mps_available": False,
        "gpu_count": 2,
        "cpu_count": 16,
    }


def test_propose_allowed_only_cuda1():
    host = _host_two_gpus()
    p = propose_device_assignments(host, ["cuda:1"])
    assert p["hypnos.voice_alignment.training_device"] == "cuda:1"
    assert p["topos.device"] == "cuda:1"
    assert "cuda:0" not in p.values()


def test_propose_allowed_cpu():
    host = _host_two_gpus()
    p = propose_device_assignments(host, ["cpu"])
    assert all(v == "cpu" for v in p.values())


def test_propose_allowed_none_matches_old_behaviour():
    host = _host_two_gpus()
    old = propose_device_assignments(host)
    assert propose_device_assignments(host, None) == old
    assert old["hypnos.voice_alignment.training_device"] == "cuda:0"
    assert old["topos.device"] == "cuda:1"


def test_fit_check_uses_floor_when_catalogue_missing():
    assignments = {"hypnos.voice_alignment.training_device": "cuda:0"}
    inventory = [{"device": "cuda:0", "free_gb": 1.0}]
    issues = fit_check(assignments, inventory, {}, 2.0)
    assert len(issues) == 1
    assert issues[0]["basis"] == "pre-flight floor (no measured footprint)"
    assert issues[0]["need_gb"] == 2.0


def test_fit_check_uses_measured_when_all_catalogued():
    assignments = {"hypnos.voice_alignment.training_device": "cuda:0"}
    inventory = [{"device": "cuda:0", "free_gb": 5.0}]
    catalogue = {"voice_alignment": 4 * 1024**3}
    issues = fit_check(assignments, inventory, catalogue, 2.0)
    assert issues == []


def test_device_step_choice_excludes_failing_device():
    host = {
        "backend": "cuda",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "A",
                "total_vram_gb": 8.0,
                "free_vram_gb": 1.0,
            },
            {
                "device": "cuda:1",
                "name": "B",
                "total_vram_gb": 8.0,
                "free_vram_gb": 8.0,
            },
        ],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 4,
        "memory": {"state": "discrete"},
    }
    cfg = {"hardware": {"allowed_devices": ["cuda:0", "cuda:1", "cpu"]}}
    ctx = StepContext(
        config=cfg,
        host=host,
        extra={
            "catalogue": {"voice_alignment": 4 * 1024**3, "topos": 4 * 1024**3},
            "floor_gb": 2.0,
            "consumers": None,
        },
    )
    step = device_step(propose_device_assignments)
    fields = step.fields(ctx)
    hypnos_field = next(
        f for f in fields if f.name == "hypnos.voice_alignment.training_device"
    )
    assert "cuda:0" not in hypnos_field.choices
    assert "cuda:1" in hypnos_field.choices
    assert "cpu" in hypnos_field.choices

    # Empty answer selects the "cpu" default for the failing address.
    run_step(
        step,
        ctx,
        input_fn=lambda _p: "",
        out=lambda _s: None,
        defaults=False,
    )
    assert (
        ctx.config["hypnos"]["voice_alignment"]["training_device"] == "cpu"
    )
    assert ctx.config["topos"]["device"] == "cuda:1"


def test_device_step_defaults_writes_cpu_for_failing_address():
    host = {
        "backend": "cuda",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "A",
                "total_vram_gb": 8.0,
                "free_vram_gb": 1.0,
            },
        ],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 4,
        "memory": {"state": "discrete"},
    }
    cfg = {"hardware": {"allowed_devices": ["cuda:0", "cpu"]}}
    ctx = StepContext(
        config=cfg,
        host=host,
        extra={
            "catalogue": {"voice_alignment": 4 * 1024**3},
            "floor_gb": 2.0,
            "consumers": None,
        },
    )
    step = device_step(propose_device_assignments)
    run_step(
        step,
        ctx,
        input_fn=lambda _p: "",
        out=lambda _s: None,
        defaults=True,
    )
    assert (
        ctx.config["hypnos"]["voice_alignment"]["training_device"] == "cpu"
    )


def test_owned_changes_within_allowlist():
    host = {
        "backend": "cuda",
        "cuda_devices": [
            {
                "device": "cuda:0",
                "name": "A",
                "total_vram_gb": 24.0,
                "free_vram_gb": 20.0,
            }
        ],
        "xpu_devices": [],
        "mps_available": False,
        "cpu_count": 4,
        "memory": {"state": "discrete"},
    }
    ctx = StepContext(
        config={},
        host=host,
        extra={
            "consumers": None,
            "catalogue": {},
            "floor_gb": 2.0,
        },
    )
    for step in (
        inventory_step,
        consent_step,
        device_step(propose_device_assignments),
    ):
        run_step(
            step,
            ctx,
            input_fn=lambda _p: "",
            out=lambda _s: None,
            defaults=True,
        )
    changes = owned_changes({}, ctx.config)
    assert changes.issubset(OWNED_KEYS)
    assert "hardware.allowed_devices" in changes
    assert "hardware.cpu_threads" in changes
    assert "hypnos.voice_alignment.training_device" in changes
    assert "embedding.device" in changes
