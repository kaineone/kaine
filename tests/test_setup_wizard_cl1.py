# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for the optional CL1 substrate plugin step in the setup wizard and for
list support in the operator-config writer.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from kaine.setup import tomlwriter
from kaine.setup.wizard import (
    ACK_PHRASE,
    MODULE_ORDER,
    _cl1_substrate_step,
    run_wizard,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = REPO_ROOT / "config" / "kaine.toml"


def _shipped() -> dict:
    with SHIPPED.open("rb") as fh:
        return tomllib.load(fh)


def _host(*, cuda: int) -> dict:
    cuda_devices = [
        {
            "index": i,
            "device": f"cuda:{i}",
            "name": f"GPU{i}",
            "total_vram_gb": 24.0,
            "free_vram_gb": 20.0,
        }
        for i in range(cuda)
    ]
    return {
        "backend": "cuda" if cuda else "cpu",
        "device": "cuda" if cuda else "cpu",
        "cuda_devices": cuda_devices,
        "gpu_count": cuda,
        "cpu_count": 16,
    }


class _Answers:
    """Scripted input_fn: pops answers in order; empty string if exhausted."""

    def __init__(self, answers: list[str]):
        self._answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._answers:
            return self._answers.pop(0)
        return ""


def _collect_out() -> tuple[list[str], callable]:
    buf: list[str] = []
    return buf, buf.append


# ----------------------------------------------------------------------------
# CL1 substrate step
# ----------------------------------------------------------------------------


def test_cl1_step_declined_by_default_writes_nothing():
    cfg = {"modules": {"chronos": True, "soma": True}}
    out, sink = _collect_out()
    _cl1_substrate_step(cfg, input_fn=lambda _p: "", line=lambda text="": sink(text))
    assert "plugins" not in cfg
    assert any("left off (the default)" in line for line in out)


def test_cl1_step_accepted_converts_enabled_modules():
    cfg = {"modules": {"chronos": True, "soma": True}}
    out, sink = _collect_out()
    _cl1_substrate_step(cfg, input_fn=lambda _p: "y", line=lambda text="": sink(text))
    assert cfg["plugins"]["enabled"] == ["cl1"]
    assert cfg["plugins"]["cl1"]["backends"] == {"chronos": "cl1", "soma": "cl1"}
    substrate = cfg["plugins"]["cl1"]["substrate"]
    assert substrate["target"] == "simulator"
    assert substrate["accelerated_time"] is True
    assert substrate["data_source"] == "reference_culture"
    assert substrate["territories"] == {"chronos": 12, "soma": 12}
    joined = "\n".join(out)
    assert "pip install ./plugins/kaine-cl1" in joined
    assert "pip install cl-sdk" in joined


def test_cl1_step_converts_only_enabled_modules():
    cfg = {"modules": {"chronos": False, "soma": True}}
    out, sink = _collect_out()
    _cl1_substrate_step(cfg, input_fn=lambda _p: "y", line=lambda text="": sink(text))
    assert cfg["plugins"]["cl1"]["backends"] == {"soma": "cl1"}
    assert cfg["plugins"]["cl1"]["substrate"]["territories"] == {"soma": 12}


def test_cl1_step_with_neither_module_writes_nothing():
    cfg = {"modules": {"chronos": False}}
    out, sink = _collect_out()
    _cl1_substrate_step(cfg, input_fn=lambda _p: "y", line=lambda text="": sink(text))
    assert "plugins" not in cfg
    assert any("nothing for the plugin to convert" in line for line in out)


def test_cl1_step_states_requirements():
    out, sink = _collect_out()
    _cl1_substrate_step(
        {"modules": {"chronos": True, "soma": True}},
        input_fn=lambda _p: "n",
        line=lambda text="": sink(text),
    )
    joined = "\n".join(out)
    for phrase in ("cl-sdk", "CC BY-NC 4.0", "non-learning", "Cortical Cloud", "docs/cl1.md"):
        assert phrase in joined


def test_cl1_step_runs_nothing(monkeypatch):
    def _no_run(*args, **kwargs):
        raise AssertionError("must not run commands")

    monkeypatch.setattr(subprocess, "run", _no_run)
    monkeypatch.setattr(subprocess, "Popen", _no_run)
    monkeypatch.setattr(subprocess, "call", _no_run)
    monkeypatch.setattr(subprocess, "check_call", _no_run)

    cfg = {"modules": {"chronos": True, "soma": True}}
    out, sink = _collect_out()
    _cl1_substrate_step(cfg, input_fn=lambda _p: "y", line=lambda text="": sink(text))
    assert cfg["plugins"]["enabled"] == ["cl1"]
    assert out


# ----------------------------------------------------------------------------
# Full wizard runs with CL1 question
# ----------------------------------------------------------------------------


def _full_run_answers(cl1_answer: str) -> list[str]:
    return [
        ACK_PHRASE,
        "y",
        *(("y" if m in {"chronos", "soma"} else "n") for m in MODULE_ORDER),
        "n",
        "n",
        cl1_answer,
    ]


def test_defaults_mode_skips_cl1_step():
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=lambda _p: "",
        out=sink,
        host=_host(cuda=0),
        shipped_config=_shipped(),
        defaults=True,
    )
    assert "plugins" not in result.config
    assert not any("Biological substrate plugin" in line for line in out)


def test_full_run_declined_leaves_no_plugins_key():
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=_Answers(_full_run_answers("")),
        out=sink,
        host=_host(cuda=1),
        shipped_config=_shipped(),
    )
    assert result.acknowledged
    assert "plugins" not in result.config
    assert tomllib.loads(tomlwriter.dumps(result.config)) == result.config


def test_full_run_accepting_cl1_round_trips():
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=_Answers(_full_run_answers("y")),
        out=sink,
        host=_host(cuda=1),
        shipped_config=_shipped(),
    )
    assert result.acknowledged
    assert result.config["plugins"]["enabled"] == ["cl1"]
    assert tomllib.loads(tomlwriter.dumps(result.config)) == result.config


# ----------------------------------------------------------------------------
# TOML writer list support
# ----------------------------------------------------------------------------


def test_tomlwriter_lists_round_trip():
    data = {
        "t": {
            "empty": [],
            "strs": ["cl1", 'quote " and backslash \\ here', "tab\there"],
            "nums": [1, 2.5],
            "flags": [True, False],
            "mixed": ["a", 1, True],
        }
    }
    assert tomllib.loads(tomlwriter.dumps(data)) == data


def test_tomlwriter_rejects_nested_lists_and_dicts_in_lists():
    with pytest.raises(TypeError):
        tomlwriter.dumps({"t": {"x": [[1]]}})
    with pytest.raises(TypeError):
        tomlwriter.dumps({"t": {"x": [{"a": 1}]}})
    with pytest.raises(TypeError):
        tomlwriter.dumps({"t": {"x": [None]}})

