# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import json
from pathlib import Path

import pytest

from tests.predictive_golden import build_trace

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures" / "predictive_golden"


def _load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def _first_diff(actual, expected, path=""):
    if type(actual) is not type(expected):
        return path or "<root>", actual, expected
    if isinstance(actual, dict):
        for k in sorted(set(actual) | set(expected)):
            if k not in actual:
                return f"{path}.{k}" if path else k, "<missing>", expected[k]
            if k not in expected:
                return f"{path}.{k}" if path else k, actual[k], "<missing>"
            r = _first_diff(actual[k], expected[k], f"{path}.{k}" if path else k)
            if r:
                return r
        return None
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}.len", len(actual), len(expected)
        for i, (a, e) in enumerate(zip(actual, expected)):
            r = _first_diff(a, e, f"{path}[{i}]")
            if r:
                return r
        return None
    if actual != expected:
        return path or "<root>", actual, expected
    return None


def _assert_matches(name):
    expected = _load(name)
    # audition skip
    if name == "audition":
        import torch
        if torch.__version__ != expected.get("torch"):
            pytest.skip(f"torch version mismatch: running {torch.__version__} vs fixture {expected.get('torch')}")
    actual = build_trace(name)
    # The header records the library versions for information; only the
    # recorded steps are the golden behaviour.
    diff = _first_diff(actual["steps"], expected["steps"], "steps")
    assert diff is None, f"first differing {diff[0]}: actual={diff[1]!r} expected={diff[2]!r}"


def test_vision_trace_matches_golden():
    _assert_matches("vision")


def test_audition_trace_matches_golden():
    _assert_matches("audition")


def test_interoception_trace_matches_golden():
    _assert_matches("interoception")


def test_traces_cover_the_edge_steps():
    for name in ("vision", "audition", "interoception"):
        data = _load(name)
        fw = data["steps"]["forward"]
        assert any(r.get("last_error_defined") is True for r in fw), name
        assert any(r.get("last_error_defined") is False for r in fw), name
        assert any(r.get("last_reading_skipped") is True for r in fw), name


def test_trace_is_deterministic():
    for name in ("vision", "audition", "interoception"):
        a = build_trace(name)
        b = build_trace(name)
        assert a == b
