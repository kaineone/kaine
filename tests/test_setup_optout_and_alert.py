# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the opt-out / alert fixes from the docs audit."""
from __future__ import annotations

import asyncio
import copy
import importlib
import pickle
import sys

import pytest

from kaine.cycle import caretaker
from kaine.cycle.individuation_runtime import IndividuationRuntime
from kaine.setup import tomlwriter
from kaine.setup.steps import OWNED_KEYS, StepContext


def _out_collector() -> tuple[list[str], object]:
    """A wizard ``out`` callable (``extra["out"]``) that records each line."""
    lines: list[str] = []

    def out(text: str) -> None:
        lines.append(text.rstrip("\n"))

    return lines, out


def test_merge_owned_remove_deletes_owned_key() -> None:
    owned = frozenset({"a.b", "a.c", "t.x", "t.y"})
    existing = {"a": {"b": 1, "c": 2}, "t": {"x": 3, "y": 4}}
    merged = tomlwriter.merge_owned(
        existing, {"a": {"b": tomlwriter.REMOVE}}, owned
    )
    assert merged == {"a": {"c": 2}, "t": {"x": 3, "y": 4}}
    assert "REMOVE" not in tomlwriter.dumps(merged)


def test_merge_owned_remove_deletes_owned_table_and_emptied_parent() -> None:
    owned = frozenset({"a.b", "a.c", "t.x", "t.y"})
    existing = {"a": {"b": 1, "c": 2}, "t": {"x": 3, "y": 4}}
    merged = tomlwriter.merge_owned(existing, {"t": tomlwriter.REMOVE}, owned)
    assert "t" not in merged
    assert merged == {"a": {"b": 1, "c": 2}}
    assert "REMOVE" not in tomlwriter.dumps(merged)


def test_merge_owned_remove_rejects_unowned_key() -> None:
    owned = frozenset({"a.b"})
    existing = {"a": {"b": 1, "c": 2}}
    with pytest.raises(ValueError):
        tomlwriter.merge_owned(
            existing, {"a": {"c": tomlwriter.REMOVE}}, owned
        )


def test_merge_owned_remove_rejects_table_with_unowned_leaf() -> None:
    owned = frozenset({"t.x"})
    existing = {"t": {"x": 3, "unowned": 5}}
    with pytest.raises(ValueError):
        tomlwriter.merge_owned(existing, {"t": tomlwriter.REMOVE}, owned)


def test_merge_owned_remove_rejects_unowned_scalar_under_owned_prefix() -> None:
    owned = frozenset({"a.b"})
    existing = {"a": 5}
    with pytest.raises(ValueError):
        tomlwriter.merge_owned(existing, {"a": tomlwriter.REMOVE}, owned)
    assert existing == {"a": 5}


def test_merge_owned_remove_deletes_owned_leaf() -> None:
    owned = frozenset({"a.b"})
    existing = {"a": {"b": 1}}
    merged = tomlwriter.merge_owned(
        existing, {"a": {"b": tomlwriter.REMOVE}}, owned
    )
    assert merged == {}


def test_merge_owned_remove_deletes_table_with_all_owned_leaves() -> None:
    owned = frozenset({"t.x", "t.y"})
    existing = {"t": {"x": 3, "y": 4}}
    merged = tomlwriter.merge_owned(existing, {"t": tomlwriter.REMOVE}, owned)
    assert "t" not in merged
    assert merged == {}


def test_remove_sentinel_survives_copy_and_pickle() -> None:
    data = {"a": tomlwriter.REMOVE}
    assert copy.copy(data)["a"] is tomlwriter.REMOVE
    assert copy.deepcopy(data)["a"] is tomlwriter.REMOVE
    assert pickle.loads(pickle.dumps(data))["a"] is tomlwriter.REMOVE


def test_merge_owned_writes_plain_remove_string_as_value() -> None:
    owned = frozenset({"a.b"})
    existing = {}
    merged = tomlwriter.merge_owned(
        existing, {"a": {"b": "__kaine_remove__"}}, owned
    )
    assert merged == {"a": {"b": "__kaine_remove__"}}
    assert "__kaine_remove__" in tomlwriter.dumps(merged)


def test_web_app_has_no_decode_remove_markers() -> None:
    from kaine.setup.web import app

    assert not hasattr(app, "_decode_remove_markers")


def test_merge_owned_remove_absent_key_is_no_op() -> None:
    owned = frozenset({"z"})
    existing = {"a": {"b": 1}}
    merged = tomlwriter.merge_owned(existing, {"z": tomlwriter.REMOVE}, owned)
    assert "z" not in merged
    assert merged == existing


def test_merge_owned_result_dumps_never_contains_remove() -> None:
    owned = frozenset(
        {
            "a.b",
            "a.c",
            "t.x",
            "t.y",
            "plugins.cl1.substrate.target",
            "plugins.cl1.substrate.accelerated_time",
            "plugins.enabled",
            "plugins.cl1.backends.chronos",
        }
    )
    existing = {
        "a": {"b": 1, "c": 2},
        "t": {"x": 3, "y": 4},
        "plugins": {
            "enabled": ["cl1"],
            "cl1": {
                "substrate": {"target": "sim", "accelerated_time": True},
                "backends": {"chronos": "cl1"},
            },
        },
    }
    updates = {
        "a": {"b": tomlwriter.REMOVE},
        "t": tomlwriter.REMOVE,
        "plugins": {"cl1": tomlwriter.REMOVE, "enabled": []},
    }
    merged = tomlwriter.merge_owned(existing, updates, owned)
    assert "REMOVE" not in tomlwriter.dumps(merged)
    assert "a" not in merged.get("a", {})  # a.b removed
    assert "t" not in merged
    assert "cl1" not in merged.get("plugins", {})
    assert merged["plugins"]["enabled"] == []


def test_research_step_opt_out_turns_enabled_off() -> None:
    from kaine.setup.wizard_steps import research_opt_in_step

    existing = {"research_submission": {"enabled": True}}
    ctx = StepContext(config={}, host={}, extra={"existing_config": existing})
    research_opt_in_step().apply(ctx, {"opt_in": False})
    merged = tomlwriter.merge_owned(existing, ctx.config, OWNED_KEYS)
    assert merged["research_submission"]["enabled"] is False


_CL1_CONFIG = {
    "substrate": {
        "target": "simulator",
        "accelerated_time": True,
        "data_source": "reference_culture",
        "territories": {"chronos": 12, "soma": 12},
    },
    "backends": {"chronos": "cl1", "soma": "cl1"},
}


def _run_cl1_step(existing: dict, answer: str = "n") -> tuple[dict, list[str]]:
    from kaine.setup.wizard_steps import cl1_substrate_step

    lines, out = _out_collector()
    ctx = StepContext(
        config={"modules": {"chronos": True, "soma": True}},
        host={},
        extra={"existing_config": existing, "input_fn": lambda _: answer, "out": out},
    )
    cl1_substrate_step().apply(ctx, {})
    return ctx.config, lines


def test_cl1_step_decline_removes_existing_cl1_config() -> None:
    existing = {
        "modules": {"chronos": True, "soma": True},
        "plugins": {"enabled": ["cl1"], "cl1": copy.deepcopy(_CL1_CONFIG)},
    }
    config, _out = _run_cl1_step(existing)
    merged = tomlwriter.merge_owned(existing, config, OWNED_KEYS)
    assert "cl1" not in merged.get("plugins", {})
    assert merged["plugins"]["enabled"] == []


def test_cl1_step_decline_keeps_other_enabled_plugins() -> None:
    existing = {
        "modules": {"chronos": True, "soma": True},
        "plugins": {"enabled": ["other", "cl1"], "cl1": copy.deepcopy(_CL1_CONFIG)},
    }
    config, _out = _run_cl1_step(existing)
    merged = tomlwriter.merge_owned(existing, config, OWNED_KEYS)
    assert merged["plugins"]["enabled"] == ["other"]
    assert "cl1" not in merged["plugins"]


def test_cl1_step_decline_without_cl1_writes_nothing() -> None:
    existing = {"modules": {"chronos": True, "soma": True}}
    config, _out = _run_cl1_step(existing)
    assert "plugins" not in config
    assert tomlwriter.merge_owned(existing, config, OWNED_KEYS) == existing


def test_encryption_step_decline_keeps_existing_enabled_true() -> None:
    from kaine.setup.wizard_steps import encryption_step

    existing = {"security": {"state_encryption": {"enabled": True}}}
    out, out_fn = _out_collector()
    ctx = StepContext(config={}, host={}, extra={"existing_config": existing, "out": out_fn})
    encryption_step().apply(ctx, {"enabled": False})
    merged = tomlwriter.merge_owned(existing, ctx.config, OWNED_KEYS)
    assert merged["security"]["state_encryption"]["enabled"] is True
    assert any("State encryption stays on" in ln for ln in out)
    assert any("docs/13-security-and-privacy.md" in ln for ln in out)


def test_setup_main_imports_without_web_extras(monkeypatch) -> None:
    # A None entry in sys.modules makes the import raise ImportError, as on an
    # install without the nexus extra. monkeypatch restores every entry after
    # the test, so nothing leaks into later tests on the same worker.
    for name in ("fastapi", "uvicorn"):
        monkeypatch.setitem(sys.modules, name, None)
    for key in list(sys.modules):
        if key == "kaine.setup.__main__" or key.startswith("kaine.setup.web"):
            monkeypatch.delitem(sys.modules, key, raising=False)

    mod = importlib.import_module("kaine.setup.__main__")
    assert hasattr(mod, "main")


def _make_runtime(events: list, notify_kinds: list):
    runtime = IndividuationRuntime.__new__(IndividuationRuntime)
    class _Bus:
        async def publish(self, event) -> None:
            events.append(event)

    runtime.bus = _Bus()
    async def notify(kind: str) -> None:
        notify_kinds.append(kind)

    runtime.notify = notify
    return runtime


def test_individuation_alert_conditions_changed() -> None:
    events: list = []
    kinds: list = []
    runtime = _make_runtime(events, kinds)

    asyncio.run(
        runtime.alert({"kind": "individuation_conditions_changed", "reference_id": "r1"})
    )

    assert len(events) == 1
    payload = events[0].payload
    assert payload["kind"] == "individuation_conditions_changed"
    assert payload["reference_id"] == "r1"
    assert payload.get("inconclusive_since") is None
    assert payload.get("days") is None
    assert payload.get("last_reason") is None
    assert kinds == ["individuation_conditions_changed"]


def test_individuation_alert_inconclusive_carries_last_reason() -> None:
    events: list = []
    kinds: list = []
    runtime = _make_runtime(events, kinds)

    asyncio.run(
        runtime.alert(
            {
                "kind": "individuation_inconclusive",
                "inconclusive_since": "2024-01-01T00:00:00",
                "days": 3.5,
                "last_reason": "low coherence",
            }
        )
    )

    assert len(events) == 1
    payload = events[0].payload
    assert payload["kind"] == "individuation_inconclusive"
    assert payload["last_reason"] == "low coherence"
    assert payload["days"] == 3.5
    assert payload["inconclusive_since"] == "2024-01-01T00:00:00"
    assert kinds == ["individuation_inconclusive"]


def test_caretaker_has_conditions_changed_title() -> None:
    assert "individuation_conditions_changed" in caretaker.EVENT_KINDS
    assert (
        caretaker._EVENT_TITLE["individuation_conditions_changed"]
        == "individuation conditions changed (looks refused)"
    )
    notice = caretaker.build_notice(
        "individuation_conditions_changed", caretaker.CaretakerConfig()
    )
    assert notice["event"] == "individuation_conditions_changed"
