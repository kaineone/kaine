# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Ratchet: convention usage in kaine/modules/ must not grow."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_CLOCK_NAMES = {
    "time.time",
    "time.monotonic",
    "time.perf_counter",
    "datetime.now",
    "datetime.datetime.now",
}

_SERVICE = {
    "clock": "EntityClock (kaine/entity_clock.py)",
    "raw_publish": "BaseModule.publish",
    "write_open": "kaine.state_io.write_json_atomic",
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> the dotted name it stands for, from every import in the file.

    ``import time as _time`` maps ``_time`` to ``time``; ``from time import
    monotonic`` maps ``monotonic`` to ``time.monotonic``. Without this an alias
    would let a clock call past the ratchet.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _resolved(dotted: str | None, aliases: dict[str, str]) -> str | None:
    if dotted is None:
        return None
    head, _, rest = dotted.partition(".")
    if head in aliases:
        return aliases[head] + (f".{rest}" if rest else "")
    return dotted


def count_calls(source: str) -> dict[str, int]:
    """Count convention-breaking calls in *source* using the AST (not text)."""
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    counts = {"clock": 0, "raw_publish": 0, "write_open": 0}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        dotted = _resolved(_dotted(func), aliases)
        if dotted in _CLOCK_NAMES:
            counts["clock"] += 1
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "publish"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "_bus"
        ):
            counts["raw_publish"] += 1
        if isinstance(func, ast.Name) and func.id == "open":
            mode: str | None = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(
                node.args[1].value, str
            ):
                mode = node.args[1].value
            for kw in node.keywords:
                if (
                    kw.arg == "mode"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    mode = kw.value.value
            if mode is not None and any(ch in mode for ch in ("w", "a", "x", "+")):
                counts["write_open"] += 1
        if isinstance(func, ast.Attribute) and func.attr in {"write_text", "write_bytes"}:
            counts["write_open"] += 1
    return counts


def scan_tree(root: Path) -> dict[tuple[str, str], int]:
    """Scan every .py under ``root``/kaine/modules/ and return the non-zero counts."""
    result: dict[tuple[str, str], int] = {}
    for path in sorted((Path(root) / "kaine" / "modules").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        try:
            counts = count_calls(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise AssertionError(f"failed to parse {rel}: {exc}") from exc
        if rel == "kaine/modules/base.py":
            counts["raw_publish"] = 0
        for kind in ("clock", "raw_publish", "write_open"):
            if counts[kind]:
                result[(rel, kind)] = counts[kind]
    return result


BASELINE: dict[tuple[str, str], int] = {
    ("kaine/modules/audition/audio_queue.py", "clock"): 2,
    ("kaine/modules/audition/emotion.py", "clock"): 3,
    ("kaine/modules/audition/feed.py", "clock"): 3,
    ("kaine/modules/audition/sherpa_stt.py", "clock"): 2,
    ("kaine/modules/audition/stt_client.py", "clock"): 2,
    ("kaine/modules/base.py", "clock"): 4,
    ("kaine/modules/effectors/audit_log.py", "clock"): 1,
    ("kaine/modules/effectors/effectors.py", "clock"): 1,
    ("kaine/modules/effectors/effectors.py", "write_open"): 1,
    ("kaine/modules/effectors/stimulus/effector.py", "clock"): 1,
    ("kaine/modules/episodic_memory/memory.py", "clock"): 2,
    ("kaine/modules/episodic_memory/memory.py", "write_open"): 1,
    ("kaine/modules/episodic_memory/replay.py", "clock"): 1,
    ("kaine/modules/interoception/fatigue.py", "clock"): 2,
    ("kaine/modules/interoception/reader.py", "clock"): 1,
    ("kaine/modules/interoception/regulation.py", "clock"): 2,
    ("kaine/modules/language/client.py", "clock"): 4,
    ("kaine/modules/language/intent_log.py", "clock"): 2,
    ("kaine/modules/language/intent_log.py", "write_open"): 2,
    ("kaine/modules/language/module.py", "clock"): 6,
    ("kaine/modules/language/module.py", "raw_publish"): 1,
    ("kaine/modules/planning/engine.py", "clock"): 4,
    ("kaine/modules/positive_control.py", "clock"): 1,
    ("kaine/modules/self_model/module.py", "clock"): 3,
    ("kaine/modules/sleep/hot_swap.py", "write_open"): 1,
    ("kaine/modules/sleep/job_queue_trainer.py", "clock"): 2,
    ("kaine/modules/sleep/job_queue_trainer.py", "write_open"): 2,
    ("kaine/modules/sleep/module.py", "clock"): 17,
    ("kaine/modules/sleep/organ_adapter.py", "clock"): 1,
    ("kaine/modules/sleep/organ_adapter.py", "write_open"): 1,
    ("kaine/modules/sleep/phases.py", "clock"): 1,
    ("kaine/modules/sleep/subprocess_trainer.py", "clock"): 1,
    ("kaine/modules/sleep/subprocess_trainer.py", "write_open"): 1,
    ("kaine/modules/sleep/trainer_service.py", "write_open"): 2,
    ("kaine/modules/sleep/voice_alignment.py", "write_open"): 1,
    ("kaine/modules/sleep/voice_audit.py", "clock"): 1,
    ("kaine/modules/sleep/voice_audit.py", "write_open"): 1,
    ("kaine/modules/sleep/voice_measures.py", "clock"): 1,
    ("kaine/modules/sleep/voice_measures.py", "write_open"): 1,
    ("kaine/modules/social_cognition/agent.py", "clock"): 3,
    ("kaine/modules/social_cognition/module.py", "clock"): 2,
    ("kaine/modules/vocal/client.py", "clock"): 2,
    ("kaine/modules/vocal/module.py", "clock"): 1,
    ("kaine/modules/vocal/module.py", "write_open"): 1,
    ("kaine/modules/vocal/qwen3_tts.py", "clock"): 2,
    ("kaine/modules/vocal/sherpa_tts.py", "clock"): 2,
    ("kaine/modules/world_model/checkpoint.py", "write_open"): 1,
    ("kaine/modules/world_model/module.py", "clock"): 1,
}


def test_counter_ignores_comments_and_strings() -> None:
    source = """\
# time.time()
s = "time.time()"
a = time.time()

# self._bus.publish()
t = "self._bus.publish()"
b = self._bus.publish()

# open('f', 'w')
u = "open('f', 'w')"
c = open('f', 'w')
"""
    assert count_calls(source) == {"clock": 1, "raw_publish": 1, "write_open": 1}


def test_counter_sees_through_import_aliases() -> None:
    source = """\
import time as _t
from time import monotonic
from datetime import datetime as dt
a = _t.monotonic()
b = monotonic()
c = dt.now()
"""
    assert count_calls(source)["clock"] == 3


def test_conventions_do_not_grow() -> None:
    scanned = scan_tree(_ROOT)
    offenders: list[str] = []
    for key in sorted(set(scanned) | set(BASELINE)):
        rel, kind = key
        actual = scanned.get(key, 0)
        baseline = BASELINE.get(key, 0)
        if actual > baseline:
            offenders.append(
                f"{rel}: {kind} count {actual} exceeds baseline {baseline}; "
                f"use {_SERVICE[kind]}"
            )
    assert not offenders, "convention usage grew:\n  " + "\n  ".join(offenders)


def test_baseline_is_not_stale() -> None:
    scanned = scan_tree(_ROOT)
    stale: list[str] = []
    for key, baseline in BASELINE.items():
        rel, kind = key
        actual = scanned.get(key, 0)
        if actual < baseline:
            stale.append(
                f"{rel}: {kind} count {actual} is below baseline {baseline}; "
                "lower the number in BASELINE"
            )
    assert not stale, "BASELINE is stale:\n  " + "\n  ".join(stale)
