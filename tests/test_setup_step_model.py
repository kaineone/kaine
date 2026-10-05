# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the shared declarative step model and merge-on-save."""
from __future__ import annotations

import tomllib
import types
from pathlib import Path
from typing import Callable

import pytest

from kaine.setup import tomlwriter
from kaine.setup.steps import OWNED_KEYS, assert_owned, owned_changes
from kaine.setup.wizard import ACK_PHRASE, MODULE_ORDER, run_wizard

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = REPO_ROOT / "config" / "kaine.toml"


def _shipped() -> dict:
    with SHIPPED.open("rb") as fh:
        return tomllib.load(fh)


def _host(*, cuda: int = 0) -> dict:
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


def _collect_out() -> tuple[list[str], Callable[[str], None]]:
    buf: list[str] = []
    return buf, buf.append


def test_owned_keys_are_within_allowlist():
    """Every key the wizard writes must be in the owned-key allowlist."""
    # --defaults
    result = run_wizard(
        input_fn=_Answers([]),
        out=lambda _s: None,
        host=_host(cuda=0),
        shipped_config=_shipped(),
        defaults=True,
    )
    assert result.acknowledged is True
    assert_owned(owned_changes({}, result.config))

    # full entity interactive
    full_answers = [
        ACK_PHRASE,
        "",
        "",
        "y",
        "f",
        "full-model",
        "full-voice.wav",
        "full-stt",
        "n",
        "n",
        "",
    ]
    result = run_wizard(
        input_fn=_Answers(full_answers),
        out=lambda _s: None,
        host=_host(cuda=2),
        shipped_config=_shipped(),
        probe_services=lambda: {
            "served_models": ["full-model"],
            "voices": ["full-voice.wav"],
            "stt_models": ["full-stt"],
        },
    )
    assert result.acknowledged is True
    assert_owned(owned_changes({}, result.config))

    # custom interactive with tier, metrics and encryption
    tier_rec = types.SimpleNamespace(
        profile="tier2",
        tier=2,
        residency_required=False,
        reason="test",
        memory_budget_gb=16.0,
    )
    custom_answers = [ACK_PHRASE, "", "", "y", "y", "c"]
    for m in MODULE_ORDER:
        custom_answers.append("y" if m in ("soma", "lingua", "vox", "audition") else "n")
    custom_answers.extend(
        [
            "custom-model",
            "custom-voice.wav",
            "custom-stt",
            "y",
            "alice@example.com",
            "y",
            "",
        ]
    )
    result = run_wizard(
        input_fn=_Answers(custom_answers),
        out=lambda _s: None,
        host=_host(cuda=1),
        shipped_config=_shipped(),
        recommend_tier_fn=lambda: tier_rec,
        probe_services=lambda: {
            "served_models": ["custom-model"],
            "voices": ["custom-voice.wav"],
            "stt_models": ["custom-stt"],
        },
    )
    assert result.acknowledged is True
    assert result.config["deployment"]["tier"] == "tier2"
    assert result.config["research_submission"]["enabled"] is True
    assert result.config["security"]["state_encryption"]["enabled"] is True
    assert_owned(owned_changes({}, result.config))

    # [research] and operator-presence gates are not in the allowlist.
    assert not any(k.startswith("research.") for k in OWNED_KEYS)
    assert "nexus.non_loopback_allowed" not in OWNED_KEYS


def test_merge_preserves_unowned_keys_and_tables():
    existing = {
        "nexus": {"non_loopback_allowed": True, "port": 9999},
        "unowned_table": {"a": 1, "nested": {"b": 2}},
    }
    updates = {
        "modules": {"soma": True, "lingua": True, "echo": False},
        "deployment": {"tier": "tier3"},
    }
    merged = tomlwriter.merge_owned(existing, updates, OWNED_KEYS)
    assert merged["nexus"]["port"] == 9999
    assert merged["nexus"]["non_loopback_allowed"] is True
    assert merged["unowned_table"]["a"] == 1
    assert merged["unowned_table"]["nested"]["b"] == 2
    assert merged["modules"]["soma"] is True
    assert merged["deployment"]["tier"] == "tier3"
    assert tomllib.loads(tomlwriter.dumps(merged)) == merged


def test_merge_replaces_owned_key():
    existing = {"modules": {"soma": False, "lingua": False}}
    updates = {"modules": {"soma": True, "lingua": True}}
    merged = tomlwriter.merge_owned(existing, updates, OWNED_KEYS)
    assert merged["modules"]["soma"] is True
    assert merged["modules"]["lingua"] is True


def test_merge_rejects_unowned_update():
    with pytest.raises(ValueError):
        tomlwriter.merge_owned(
            {}, {"nexus": {"port": 9999}}, OWNED_KEYS
        )


def test_merge_rejects_unemittable_existing_value():
    with pytest.raises(ValueError):
        tomlwriter.merge_owned(
            {"bad": None}, {"modules": {"soma": True}}, OWNED_KEYS
        )
    with pytest.raises(ValueError):
        tomlwriter.merge_owned(
            {"bad": [{"a": 1}]}, {"modules": {"soma": True}}, OWNED_KEYS
        )


def test_idempotence_with_existing_config(tmp_path: Path):
    """A scripted run, merge+save, then a re-run with empty answers and the
    parsed file as existing_config must produce an identical operator file."""
    first_answers = [ACK_PHRASE, "", "", "y", "c"]
    for m in MODULE_ORDER:
        first_answers.append("y" if m in ("soma", "lingua", "vox", "audition") else "n")
    first_answers.extend(
        [
            "first-model",
            "first-voice.wav",
            "first-stt",
            "n",
            "n",
            "",
        ]
    )

    out1, sink1 = _collect_out()
    result1 = run_wizard(
        input_fn=_Answers(first_answers),
        out=sink1,
        host=_host(cuda=0),
        shipped_config=_shipped(),
        probe_services=lambda: {
            "served_models": ["first-model"],
            "voices": ["first-voice.wav"],
            "stt_models": ["first-stt"],
        },
    )
    assert result1.acknowledged is True

    first_path = tmp_path / "first.toml"
    first_path.write_text(
        tomlwriter.dumps(tomlwriter.merge_owned({}, result1.config, OWNED_KEYS))
    )

    with first_path.open("rb") as fh:
        existing = tomllib.load(fh)

    # Re-run with the ack plus otherwise-empty answers; defaults come from the
    # existing operator file.
    re_answers = [ACK_PHRASE] + [""] * 100
    out2, sink2 = _collect_out()
    result2 = run_wizard(
        input_fn=_Answers(re_answers),
        out=sink2,
        host=_host(cuda=0),
        shipped_config=_shipped(),
        existing_config=existing,
        probe_services=lambda: {
            "served_models": ["first-model"],
            "voices": ["first-voice.wav"],
            "stt_models": ["first-stt"],
        },
    )
    assert result2.acknowledged is True

    second_path = tmp_path / "second.toml"
    second_path.write_text(
        tomlwriter.dumps(tomlwriter.merge_owned(existing, result2.config, OWNED_KEYS))
    )

    assert second_path.read_text() == first_path.read_text()


def test_acknowledgement_refusal_writes_nothing():
    result = run_wizard(
        input_fn=_Answers(["no thanks"]),
        out=lambda _s: None,
        host=_host(cuda=0),
        shipped_config=_shipped(),
    )
    assert result.acknowledged is False
    assert result.config == {}


def test_assert_owned_raises_on_unowned_keys():
    with pytest.raises(ValueError):
        assert_owned({"research.enabled"})


def test_merge_owned_refuses_to_replace_a_value_with_a_table():
    existing = {"lingua": "hand-written scalar"}
    with pytest.raises(ValueError):
        tomlwriter.merge_owned(existing, {"lingua": {"model_id": "m"}}, frozenset({"lingua.model_id"}))
    assert existing == {"lingua": "hand-written scalar"}


def test_nothing_is_probed_before_the_acknowledgement():
    probed: list[str] = []
    result = run_wizard(
        input_fn=_Answers(["no"]),
        out=lambda _t: None,
        host=_host(),
        shipped_config=_shipped(),
        probe_services=lambda: probed.append("services") or {},
        device_consumers_fn=lambda: probed.append("consumers") or [],
        services_up_fn=lambda: probed.append("services_up") or {},
        recommend_tier_fn=lambda: probed.append("tier"),
    )
    assert result.acknowledged is False
    assert probed == []
