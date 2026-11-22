# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import json
from pathlib import Path

import pytest

from tests.golden_diff import CI_REL_TOL, compare_dirs, first_diff
from tests.predictive_golden import build_trace

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures" / "predictive_golden"


def _load(name):
    return json.loads((FIX / f"{name}.json").read_text())


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
    # The fixture check tolerates float drift between CI's runner CPUs; the exact check is tools/maintainer/golden-compare.sh on one machine.
    diff = first_diff(actual["steps"], expected["steps"], "steps", rel_tol=CI_REL_TOL)
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


def test_first_diff_exact_mode_reports_one_ulp():
    assert first_diff({"x": 1.8988874013097554}, {"x": 1.8988874013097556}) is not None


def test_first_diff_tolerant_mode_accepts_cpu_drift():
    assert first_diff({"a": [0.7471864465484186]}, {"a": [0.7471864432325062]}, rel_tol=CI_REL_TOL) is None
    assert first_diff({"a": [1.8988874013097554]}, {"a": [1.8988874013097556]}, rel_tol=CI_REL_TOL) is None


def test_first_diff_tolerant_mode_still_catches_real_changes():
    assert first_diff({"x": 0.75}, {"x": 0.76}, rel_tol=CI_REL_TOL) is not None
    assert first_diff({"x": True}, {"x": False}, rel_tol=CI_REL_TOL) is not None
    assert first_diff({"x": 1}, {"x": 2}, rel_tol=CI_REL_TOL) is not None
    diff = first_diff({"x": [1, 2]}, {"x": [1, 2, 3]}, rel_tol=CI_REL_TOL)
    assert diff is not None and diff[0].endswith(".len")


def test_first_diff_tolerant_mode_skips_digests_but_not_missing_ones():
    assert first_diff({"state_digest": "aa"}, {"state_digest": "bb"}, rel_tol=CI_REL_TOL) is None
    assert first_diff({"state_digest": "aa"}, {"state_digest": "bb"}, rel_tol=0) is not None
    assert first_diff({}, {"state_digest": "bb"}, rel_tol=CI_REL_TOL) is not None


def test_compare_dirs_is_exact(tmp_path):
    base = tmp_path / "base"
    head = tmp_path / "head"
    base.mkdir()
    head.mkdir()

    base_data = {"steps": {"f": [1.8988874013097556]}}
    head_data = {"steps": {"f": [1.8988874013097554]}}

    (base / "vision.json").write_text(json.dumps(base_data))
    (head / "vision.json").write_text(json.dumps(head_data))

    messages = compare_dirs(base, head)
    assert len(messages) == 1
    assert "vision" in messages[0]

    (head / "vision.json").write_text(json.dumps(base_data))
    assert compare_dirs(base, head) == []


def test_compare_dirs_reports_missing_head_file(tmp_path):
    base = tmp_path / "base"
    head = tmp_path / "head"
    base.mkdir()
    head.mkdir()

    (base / "vision.json").write_text(json.dumps({"steps": {}}))
    messages = compare_dirs(base, head)
    assert len(messages) == 1
