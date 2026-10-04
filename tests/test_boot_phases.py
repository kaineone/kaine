# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Static and runtime tests for the cycle's boot phase runner."""

import ast
import asyncio
import dataclasses
import importlib.util
import types
from pathlib import Path

import pytest

import kaine.cycle.__main__ as cyc

EXPECTED_PHASE_ORDER = [
    "_phase_stage",
    "_phase_preconditions",
    "_phase_run_identity",
    "_phase_gates",
    "_phase_bus",
    "_phase_womb_hold",
    "_phase_registry",
    "_phase_maturation_gate",
    "_phase_workspace",
    "_phase_volition",
    "_phase_cycle",
    "_phase_supervision",
    "_phase_runtime_state",
    "_phase_sidecar",
    "_phase_ignition_log",
    "_phase_preview",
    "_phase_remote_bridge",
    "_phase_signals",
    "_phase_spot",
    "_phase_safety_net",
    "_phase_launch",
    "_phase_birth",
    "_phase_womb_watch",
    "_phase_caretaker",
    "_phase_gestation",
    "_phase_watchers",
]

# Must change only together with the exit-code table in docs/14-for-researchers.md.
EXPECTED_RETURNS = {
    "_phase_preconditions": {"3", "INDIVIDUATION_REFUSED_EXIT"},
    "_phase_gates": {"4", "ORGAN_GATE_REFUSED_EXIT"},
    "_phase_bus": {"WELFARE_PRODUCER_REFUSED_EXIT"},
    "_phase_womb_hold": {"0"},
    "_phase_registry": {"refused"},
}


def _main_ast() -> ast.AST:
    spec = importlib.util.find_spec("kaine.cycle.__main__")
    assert spec is not None, "could not find kaine.cycle.__main__"
    assert spec.origin is not None, "kaine.cycle.__main__ has no origin"
    return ast.parse(Path(spec.origin).read_text(encoding="utf-8"))


def _collect_returns(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return-values of *func_node*, ignoring nested function defs and lambdas."""
    returns: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return
        if isinstance(node, ast.Return) and node.value is not None:
            # ``return None`` is the explicit "continue the boot".
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                return
            returns.add(ast.unparse(node.value))
        for child in ast.iter_child_nodes(node):
            visit(child)

    for child in ast.iter_child_nodes(func_node):
        visit(child)
    return returns


def test_phase_order() -> None:
    """_BOOT_PHASES contains the expected phase functions in order."""
    assert [f.__name__ for f in cyc._BOOT_PHASES] == EXPECTED_PHASE_ORDER


def test_phase_exit_codes() -> None:
    """Only the documented phases return non-None values."""
    module_ast = _main_ast()
    functions = {
        node.name: node
        for node in ast.walk(module_ast)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    actual: dict[str, set[str]] = {}
    for name in EXPECTED_PHASE_ORDER:
        node = functions.get(name)
        assert node is not None, f"{name} not found in kaine/cycle/__main__.py AST"
        returns = _collect_returns(node)
        if returns:
            actual[name] = returns

    assert actual == EXPECTED_RETURNS


def test_every_ctx_attribute_is_boot_context_field() -> None:
    """Every ``ctx.X`` in a function that takes a BootContext names a field.

    Only functions whose ``ctx`` parameter is annotated ``BootContext`` count;
    other helpers in the module use ``ctx`` for the run context.
    """
    module_ast = _main_ast()
    ctx_attrs: set[str] = set()
    boot_fns = [
        fn
        for fn in ast.walk(module_ast)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            a.arg == "ctx" and a.annotation is not None and ast.unparse(a.annotation) == "BootContext"
            for a in fn.args.args + fn.args.kwonlyargs
        )
    ]
    assert len(boot_fns) == len(EXPECTED_PHASE_ORDER) + 2  # the phases, run loop and shutdown
    for fn in boot_fns:
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ctx":
                ctx_attrs.add(node.attr)

    field_names = {f.name for f in dataclasses.fields(cyc.BootContext)}
    missing = ctx_attrs - field_names
    assert not missing, f"ctx attributes not declared on BootContext: {sorted(missing)}"


def test_boot_context_rejects_unknown_fields() -> None:
    """BootContext is slotted: setting an undeclared field raises AttributeError."""
    ctx = cyc.BootContext()
    with pytest.raises(AttributeError):
        ctx.not_a_field = 1  # type: ignore[attr-defined]


def test_runner_stops_at_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A phase returning a non-None exit code halts the runner immediately."""
    calls: list[tuple[str, object]] = []

    async def phase_one(ctx: cyc.BootContext) -> None:
        calls.append(("phase_one", ctx))
        return None

    async def phase_two(ctx: cyc.BootContext) -> int:
        calls.append(("phase_two", ctx))
        return 7

    async def fake_run(ctx: cyc.BootContext) -> None:
        calls.append(("run", ctx))

    async def fake_shutdown(ctx: cyc.BootContext) -> None:
        calls.append(("shutdown", ctx))

    monkeypatch.setattr(cyc, "_BOOT_PHASES", (phase_one, phase_two))
    monkeypatch.setattr(cyc, "_run_until_stopped", fake_run)
    monkeypatch.setattr(cyc, "_shutdown", fake_shutdown)

    result = asyncio.run(cyc._boot_and_run(kaine_config={}))
    assert result == 7
    assert [name for name, _ in calls] == ["phase_one", "phase_two"]
    assert calls[0][1] is calls[1][1], "both phases must operate on the same BootContext"
    assert not any(name == "run" for name, _ in calls), "run loop must not execute"
    assert not any(name == "shutdown" for name, _ in calls), "shutdown must not execute"


def test_shutdown_always_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shutdown runs even when the run loop raises."""
    shutdown_calls: list[cyc.BootContext] = []

    async def noop_phase(_ctx: cyc.BootContext) -> None:
        return None

    async def boom(_ctx: cyc.BootContext) -> None:
        raise RuntimeError("boom")

    async def recording_shutdown(ctx: cyc.BootContext) -> None:
        shutdown_calls.append(ctx)

    monkeypatch.setattr(cyc, "_BOOT_PHASES", (noop_phase,))
    monkeypatch.setattr(cyc, "_run_until_stopped", boom)
    monkeypatch.setattr(cyc, "_shutdown", recording_shutdown)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(cyc._boot_and_run(kaine_config={}))

    assert len(shutdown_calls) == 1


@pytest.mark.parametrize("escalated, expected", [(True, 70), (False, 0)])
def test_escalation_exit_code(
    monkeypatch: pytest.MonkeyPatch, escalated: bool, expected: int
) -> None:
    """Escalated spot returns 70; otherwise the runner returns 0."""
    shutdown_calls: list[cyc.BootContext] = []

    async def set_spot(ctx: cyc.BootContext) -> None:
        ctx.spot = types.SimpleNamespace(escalated=escalated)
        return None

    async def noop(_ctx: cyc.BootContext) -> None:
        return None

    async def recording_shutdown(ctx: cyc.BootContext) -> None:
        shutdown_calls.append(ctx)

    monkeypatch.setattr(cyc, "_BOOT_PHASES", (set_spot,))
    monkeypatch.setattr(cyc, "_run_until_stopped", noop)
    monkeypatch.setattr(cyc, "_shutdown", recording_shutdown)

    result = asyncio.run(cyc._boot_and_run(kaine_config={}))
    assert result == expected
    assert len(shutdown_calls) == 1
    assert shutdown_calls[0].spot is not None
    assert shutdown_calls[0].spot.escalated is escalated


def test_phase_exception_skips_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """A phase that raises ends the boot without the run loop or shutdown."""
    calls: list[str] = []

    async def boom(ctx: cyc.BootContext) -> None:
        raise RuntimeError("phase failed")

    async def run(ctx: cyc.BootContext) -> None:
        calls.append("run")

    async def shutdown(ctx: cyc.BootContext) -> None:
        calls.append("shutdown")

    monkeypatch.setattr(cyc, "_BOOT_PHASES", (boom,))
    monkeypatch.setattr(cyc, "_run_until_stopped", run)
    monkeypatch.setattr(cyc, "_shutdown", shutdown)
    with pytest.raises(RuntimeError, match="phase failed"):
        asyncio.run(cyc._boot_and_run(kaine_config={}))
    assert calls == []


def test_boot_context_repr_hides_the_intent_secret() -> None:
    """The context holds the Praxis intent secret, so its repr shows no field."""
    ctx = cyc.BootContext(kaine_config={})
    ctx.intent_secret = b"\x01secret-bytes\x02"
    assert "secret-bytes" not in repr(ctx)
    assert "intent_secret" not in repr(ctx)
