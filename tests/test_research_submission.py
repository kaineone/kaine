# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the research submission module.

PARAMOUNT: the default (metrics) bundle must be allowlist-based and contain
NONE of the deny patterns (intent_expression, mnemos, qdrant, eidolon/self_model,
conversation, replay). These tests verify the guarantee holds even when decoy
sensitive files are present in eval_root.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_eval_root(tmp_path: Path) -> Path:
    """Populate a tmp eval root with both metric files AND decoy sensitive files."""
    eval_root = tmp_path / "evaluation"

    # --- Metric dirs (should be included) ---
    # Iterate the allowlist itself so a newly-allowlisted dir is auto-populated.
    from kaine.research.submission import METRICS_ONLY_DIRS

    for subdir in METRICS_ONLY_DIRS:
        d = eval_root / subdir
        d.mkdir(parents=True)
        (d / f"{subdir}-2026-06-07.jsonl").write_text(
            '{"value": 0.42, "ts": "2026-06-07T00:00:00Z"}\n', encoding="utf-8"
        )

    # --- Decoy sensitive files (must be EXCLUDED) ---
    # 1. intent_expression.jsonl (Lingua — embeds user speech + monologue)
    decoy_lingua = eval_root / "intent_expression.jsonl"
    decoy_lingua.write_text(
        '{"intent": "user said something private", "expression": "entity responded"}\n',
        encoding="utf-8",
    )

    # 2. A mnemos file
    decoy_mnemos = eval_root / "mnemos_short_term.jsonl"
    decoy_mnemos.write_text('{"id": "mem1", "text": "private memory"}\n', encoding="utf-8")

    # 3. An eidolon self-model file
    decoy_eidolon = eval_root / "eidolon_self_model.json"
    decoy_eidolon.write_text('{"name": "entity identity", "values": []}', encoding="utf-8")

    # 4. A conversation file
    decoy_conv = eval_root / "conversation_2026-06-07.jsonl"
    decoy_conv.write_text('{"turn": "user: hello", "response": "entity: hi"}\n', encoding="utf-8")

    # 5. A replay file
    decoy_replay = eval_root / "replay_2026-06-07.jsonl"
    decoy_replay.write_text('{"memory_text": "verbatim episodic content"}\n', encoding="utf-8")

    return eval_root


# ---------------------------------------------------------------------------
# Core: metrics-only default
# ---------------------------------------------------------------------------


def test_default_bundle_is_metrics_only(tmp_path: Path):
    """Build with default tier and assert NO deny-pattern paths appear."""
    from kaine.research.submission import build_research_bundle, DENY_PATTERNS

    eval_root = _make_eval_root(tmp_path)
    out_dir = tmp_path / "out"

    bundle = build_research_bundle(eval_root=eval_root, out_dir=out_dir)

    # Every included file must not match any deny pattern.
    for bf in bundle.files:
        lower = bf.rel_path.lower()
        for pat in DENY_PATTERNS:
            assert pat not in lower, (
                f"deny pattern {pat!r} found in included file {bf.rel_path!r}. "
                "The metrics bundle must NEVER include sensitive files."
            )

    # Must include at least some metric files.
    assert len(bundle.files) > 0, "bundle must contain at least one metric file"

    # Manifest must match.
    assert bundle.manifest_path is not None
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["tier"] == "metrics"
    assert "included_files" in manifest


def test_decoy_files_are_excluded(tmp_path: Path):
    """All decoy sensitive files must be absent from the bundle."""
    from kaine.research.submission import build_research_bundle

    eval_root = _make_eval_root(tmp_path)
    out_dir = tmp_path / "out"

    bundle = build_research_bundle(eval_root=eval_root, out_dir=out_dir)

    included_paths = {bf.rel_path for bf in bundle.files}
    for forbidden in (
        "intent_expression.jsonl",
        "mnemos_short_term.jsonl",
        "eidolon_self_model.json",
        "conversation_2026-06-07.jsonl",
        "replay_2026-06-07.jsonl",
    ):
        for p in included_paths:
            assert forbidden not in p, (
                f"decoy file {forbidden!r} leaked into metrics bundle via path {p!r}"
            )


def test_metric_dirs_are_included(tmp_path: Path):
    """All allowlisted metric directories that have files should be included."""
    from kaine.research.submission import build_research_bundle, METRICS_ONLY_DIRS

    eval_root = _make_eval_root(tmp_path)
    out_dir = tmp_path / "out"

    bundle = build_research_bundle(eval_root=eval_root, out_dir=out_dir)

    included_subdirs = {bf.rel_path.split("/")[0] for bf in bundle.files}
    for expected in METRICS_ONLY_DIRS:
        assert expected in included_subdirs, (
            f"metric dir {expected!r} not found in bundle; included: {included_subdirs}"
        )


def test_missing_metric_dirs_ok(tmp_path: Path):
    """If some metric dirs don't exist, the build succeeds without error."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    # Only create one metric dir.
    (eval_root / "ab_divergence").mkdir(parents=True)
    (eval_root / "ab_divergence" / "ab-2026-06-07.jsonl").write_text(
        '{"value": 0.1}\n', encoding="utf-8"
    )

    bundle = build_research_bundle(eval_root=eval_root, out_dir=tmp_path / "out")
    assert len(bundle.files) == 1
    assert bundle.files[0].rel_path.startswith("ab_divergence/")


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def test_preview_lists_contents_and_excluded_note(tmp_path: Path):
    """preview() must list included files AND the EXCLUDED section."""
    from kaine.research.submission import build_research_bundle, preview

    eval_root = _make_eval_root(tmp_path)
    bundle = build_research_bundle(eval_root=eval_root, out_dir=tmp_path / "out")

    text = preview(bundle)

    # Must list the metrics files.
    assert "ab_divergence" in text
    assert "coherence" in text

    # Must have the EXCLUDED note.
    assert "EXCLUDED" in text
    assert "intent log" in text.lower() or "intent_expression" in text.lower()
    assert "memories" in text.lower() or "mnemos" in text.lower()
    assert "self-model" in text.lower() or "eidolon" in text.lower()
    assert "conversation" in text.lower()


def test_preview_never_sends(tmp_path: Path, monkeypatch):
    """--preview CLI flag must build and print but never call send_or_write."""
    from kaine.transfer import email_request as email_mod

    send_called = []

    def fake_send(*args, **kwargs):
        send_called.append(True)
        raise AssertionError("send_or_write must not be called in --preview mode")

    monkeypatch.setattr(email_mod, "send_or_write", fake_send)

    eval_root = _make_eval_root(tmp_path)
    out_dir = tmp_path / "out"

    from kaine.research.__main__ import main

    out_buf = StringIO()
    code = main(
        ["--preview", "--eval-root", str(eval_root), "--out-root", str(out_dir),
         "--config", str(tmp_path / "no-config.toml")],
        out=out_buf,
        err=StringIO(),
    )
    assert code == 0
    assert not send_called
    assert "EXCLUDED" in out_buf.getvalue()


# ---------------------------------------------------------------------------
# Full tier without opt-in must refuse
# ---------------------------------------------------------------------------


def test_full_tier_without_optin_raises(tmp_path: Path):
    """Requesting tier='full' without attestation must raise BundleTierError."""
    from kaine.research.submission import build_research_bundle, BundleTierError

    eval_root = _make_eval_root(tmp_path)
    with pytest.raises(BundleTierError):
        build_research_bundle(
            eval_root=eval_root,
            tier="full",
            out_dir=tmp_path / "out",
            # missing: full_tier_opted_in, bystander_consent_attested, entity_privacy_attested
        )


def test_full_tier_partial_optin_raises(tmp_path: Path):
    """Partial attestation is still refused."""
    from kaine.research.submission import build_research_bundle, BundleTierError

    eval_root = _make_eval_root(tmp_path)
    with pytest.raises(BundleTierError):
        build_research_bundle(
            eval_root=eval_root,
            tier="full",
            out_dir=tmp_path / "out",
            full_tier_opted_in=True,
            # bystander_consent_attested and entity_privacy_attested still False
        )


# ---------------------------------------------------------------------------
# Config: shipped config ships disabled + empty recipient
# ---------------------------------------------------------------------------


def test_shipped_config_research_submission_disabled():
    """Guard: config/kaine.toml must ship [research_submission].enabled = false."""
    import tomllib

    root = Path(__file__).parent.parent
    config = tomllib.loads((root / "config" / "kaine.toml").read_text())
    rs = config.get("research_submission", {})
    assert rs.get("enabled", False) is False, (
        "shipped config must ship [research_submission].enabled = false"
    )
    assert rs.get("recipient", "") == "", (
        "shipped config must ship [research_submission].recipient = '' (empty)"
    )


# ---------------------------------------------------------------------------
# Config loader honours the operator override (parity with the cycle loader)
# ---------------------------------------------------------------------------


def test_research_loader_applies_operator_override(tmp_path: Path, monkeypatch):
    """The research entrypoint must route through the canonical loader so the
    gitignored config/kaine.operator.toml deep-merges over the shipped file —
    exactly like the cognitive cycle. Previously it parsed kaine.toml with raw
    tomllib and silently ignored operator choices (a parity bug)."""
    from kaine.research.__main__ import _load_config

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "kaine.toml").write_text(
        "[research_submission]\nenabled = false\nrecipient = \"\"\n",
        encoding="utf-8",
    )
    (cfg_dir / "kaine.operator.toml").write_text(
        "[research_submission]\nenabled = true\nrecipient = \"ops@example.test\"\n",
        encoding="utf-8",
    )
    # OPERATOR_CONFIG_PATH is the working-directory-relative
    # config/kaine.operator.toml, so run from tmp_path.
    monkeypatch.chdir(tmp_path)
    cfg = _load_config("config/kaine.toml")
    rs = cfg.get("research_submission", {})
    assert rs.get("enabled") is True, "operator override must win over shipped"
    assert rs.get("recipient") == "ops@example.test"


# ---------------------------------------------------------------------------
# CLI: --send requires confirm; EOF fails safe
# ---------------------------------------------------------------------------


def test_cli_send_eof_fails_safe(tmp_path: Path):
    """EOF at the confirm prompt must abort without sending."""
    from kaine.research.__main__ import main
    from kaine.transfer import email_request as email_mod

    send_called = []

    import unittest.mock as mock

    eval_root = _make_eval_root(tmp_path)
    out_dir = tmp_path / "out"

    out_buf = StringIO()
    err_buf = StringIO()

    def eof_input(prompt):
        raise EOFError("simulated EOF")

    # Patch send_or_write to detect any accidental sends.
    original_send = email_mod.send_or_write

    def guarded_send(*args, **kwargs):
        send_called.append(True)
        return original_send(*args, **kwargs)

    with mock.patch.object(email_mod, "send_or_write", guarded_send):
        code = main(
            ["--send", "--eval-root", str(eval_root), "--out-root", str(out_dir),
             "--config", str(tmp_path / "no-config.toml")],
            input_fn=eof_input,
            out=out_buf,
            err=err_buf,
        )

    assert code == 2, f"EOF should return code 2 (no-send); got {code}"
    assert not send_called, "send_or_write must NOT be called when input is EOF"


def test_cli_send_decline_fails_safe(tmp_path: Path):
    """Answering 'n' at the recipient-confirm prompt must not send."""
    from kaine.research.__main__ import main
    from kaine.transfer import email_request as email_mod
    import unittest.mock as mock

    send_called = []
    eval_root = _make_eval_root(tmp_path)
    out_dir = tmp_path / "out"

    # In the no-recipient flow there are two prompts:
    # 1. "Enter recipient email [default]:" → type an address
    # 2. "Confirm send to <addr>? [y/N]:"   → answer "n" to decline
    answers = iter(["kaine.one@tuta.com", "n"])

    def mock_input(prompt):
        return next(answers)

    original_send = email_mod.send_or_write

    def guarded_send(*args, **kwargs):
        send_called.append(True)
        return original_send(*args, **kwargs)

    with mock.patch.object(email_mod, "send_or_write", guarded_send):
        code = main(
            ["--send", "--eval-root", str(eval_root), "--out-root", str(out_dir),
             "--config", str(tmp_path / "no-config.toml")],
            input_fn=mock_input,
            out=StringIO(),
            err=StringIO(),
        )

    assert code == 2
    assert not send_called


def test_cli_send_confirm_calls_send_or_write(tmp_path: Path):
    """Answering 'y' at both prompts should call send_or_write."""
    from kaine.research.__main__ import main
    from kaine.transfer import email_request as email_mod
    from kaine.transfer.email_request import SendResult
    import unittest.mock as mock

    send_called = []
    eval_root = _make_eval_root(tmp_path)
    out_dir = tmp_path / "out"

    # Recipient prompt: enter address, then confirm y, then final confirm y.
    answers = iter(["kaine.one@tuta.com", "y", "y"])

    def mock_input(prompt):
        return next(answers, "y")

    def fake_send(rendered, *, smtp_config, confirm, out_dir):
        send_called.append(rendered.recipient)
        return SendResult(sent=False, detail="test fallback")

    with mock.patch.object(email_mod, "send_or_write", fake_send):
        code = main(
            ["--send", "--eval-root", str(eval_root), "--out-root", str(out_dir),
             "--config", str(tmp_path / "no-config.toml")],
            input_fn=mock_input,
            out=StringIO(),
            err=StringIO(),
        )

    assert send_called, "send_or_write must be called when operator confirms"


# ---------------------------------------------------------------------------
# Admissibility integration (run-completeness-gating)
# ---------------------------------------------------------------------------


def _plant_run(eval_root: Path, run_id: str, *, complete: bool) -> None:
    """Plant cycle.tick + welfare sink records for a run under eval_root."""
    eval_root.mkdir(parents=True, exist_ok=True)
    ticks = []
    seq = 0
    indices = [0, 1, 2] if complete else [0, 2]  # gap at 1 when not complete
    for i in indices:
        ticks.append({"run_id": run_id, "seq": seq, "tick_index": i,
                      "event_type": "cycle.tick"})
        seq += 1
    (eval_root / "cycle.tick-2026-06-14.jsonl").write_text(
        "\n".join(json.dumps(r) for r in ticks) + "\n", encoding="utf-8"
    )
    (eval_root / "welfare-2026-06-14.jsonl").write_text(
        "\n".join(json.dumps({"run_id": run_id, "seq": i, "v": i}) for i in range(2))
        + "\n",
        encoding="utf-8",
    )


def _plant_out_of_range_run(eval_root: Path, run_id: str) -> None:
    """A completeness-clean run that carries one out-of-range logged value."""
    _plant_run(eval_root, run_id, complete=True)
    (eval_root / "soma.report-2026-06-14.jsonl").write_text(
        json.dumps({
            "run_id": run_id, "seq": 0, "event_type": "soma.report",
            "prediction_error": -1.0,  # NONNEG range: must be >= 0.0
        }) + "\n",
        encoding="utf-8",
    )


def _plant_restart_run(eval_root: Path, run_id: str) -> None:
    """A run whose cycle.tick stream is clean but whose welfare seq resets
    mid-way (0, 1, 2, 0, 1) — the literal "restart re-zeroed seq" signature."""
    eval_root.mkdir(parents=True, exist_ok=True)
    ticks = [
        {"run_id": run_id, "seq": i, "tick_index": i, "event_type": "cycle.tick"}
        for i in range(3)
    ]
    (eval_root / "cycle.tick-2026-06-14.jsonl").write_text(
        "\n".join(json.dumps(r) for r in ticks) + "\n", encoding="utf-8"
    )
    welfare = [
        {"run_id": run_id, "seq": s, "v": s} for s in (0, 1, 2, 0, 1)
    ]
    (eval_root / "welfare-2026-06-14.jsonl").write_text(
        "\n".join(json.dumps(r) for r in welfare) + "\n", encoding="utf-8"
    )


def test_bundle_manifest_records_admissibility_verdict(tmp_path: Path):
    """A complete, in-range run yields BOTH verdicts (completeness + range) in
    the manifest, each admissible=True — the export path enforces both checks
    from the run-admissibility / log-validation specs (paper §6.3)."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-int-ok", complete=True)
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
        admissibility_run_id="run-int-ok",
        expected_streams=["cycle.tick", "welfare"],
    )
    manifest = json.loads(bundle.manifest_path.read_text())
    assert "admissibility" in manifest
    assert manifest["admissibility"]["admissible"] is True
    assert manifest["admissibility"]["reasons"] == []
    # Task 1: the range sweep verdict is recorded alongside completeness.
    assert "range_admissibility" in manifest
    assert manifest["range_admissibility"]["admissible"] is True
    assert manifest["range_admissibility"]["violations"] == []


def test_auto_discovery_admits_clean_single_run_without_run_id(tmp_path: Path):
    """No run_id passed: the builder AUTO-DISCOVERS the single run in eval_root
    and records both verdicts. A clean run exports and reads admissible."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-int-x", complete=True)
    bundle = build_research_bundle(eval_root=eval_root, out_dir=tmp_path / "out")
    manifest = json.loads(bundle.manifest_path.read_text())
    # Auto-discovery now gates by default — the block is present, not absent.
    assert manifest["admissibility"]["admissible"] is True
    assert manifest["range_admissibility"]["admissible"] is True


def test_zero_run_logs_records_marker_and_does_not_pass_as_clean(tmp_path: Path):
    """An eval_root with metric files but NO run-stamped records: there is no
    run to admit. The manifest records an honest `no_run_logs_present` marker
    (admissible is None, never True) and the export is allowed."""
    from kaine.research.submission import build_research_bundle

    eval_root = _make_eval_root(tmp_path)  # metric + decoy files, no run_id
    bundle = build_research_bundle(eval_root=eval_root, out_dir=tmp_path / "out")
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["status"] == "no_run_logs_present"
    # Must NOT be reported clean.
    assert manifest["admissibility"]["admissible"] is not True
    assert manifest["admissibility"]["reasons"]
    # No range block (nothing to sweep) and no false override marker.
    assert "range_admissibility" not in manifest
    assert "admissibility_override" not in manifest


def test_bundle_manifest_annotates_inadmissible_run_when_override_disables_gate(
    tmp_path: Path,
):
    """With `require_admissible=False` explicitly set (not the default), an
    incomplete run still builds and the manifest carries admissible=False with
    reasons — the opt-out path is unchanged plumbing-wise."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-int-bad", complete=False)
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
        admissibility_run_id="run-int-bad",
        expected_streams=["cycle.tick", "welfare"],
        require_admissible=False,
    )
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["admissible"] is False
    assert manifest["admissibility"]["tick_gaps"] == [1]
    assert manifest["admissibility"]["reasons"]
    assert "admissibility_override" not in manifest


# ---------------------------------------------------------------------------
# Scenario 4.2 (spec): an incomplete run is blocked by the default export path.
# ---------------------------------------------------------------------------


def test_incomplete_run_blocked_by_default(tmp_path: Path):
    """`require_admissible` now DEFAULTS to True: an incomplete run (tick gap)
    is blocked from export without the caller opting in to anything."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-int-bad-default", complete=False)
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(
            eval_root=eval_root,
            out_dir=out_dir,
            admissibility_run_id="run-int-bad-default",
            expected_streams=["cycle.tick", "welfare"],
            # require_admissible intentionally NOT passed — must default True.
        )
    assert "tick_index gaps" in str(excinfo.value)
    # No half-built bundle dir left behind.
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_require_admissible_refuses_inadmissible_run(tmp_path: Path):
    """Explicit require_admissible=True (now redundant with the default) still
    raises on an inadmissible run and leaves no bundle behind."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-int-strict", complete=False)
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError):
        build_research_bundle(
            eval_root=eval_root,
            out_dir=out_dir,
            admissibility_run_id="run-int-strict",
            expected_streams=["cycle.tick", "welfare"],
            require_admissible=True,
        )
    # No half-built bundle dir left behind.
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


# ---------------------------------------------------------------------------
# Scenario 4.1 (spec): an out-of-range value is blocked by the default export
# path (task 1: the range sweep now runs inside build_research_bundle).
# ---------------------------------------------------------------------------


def test_out_of_range_run_blocked_by_default(tmp_path: Path):
    """A completeness-clean run with one out-of-range logged value is blocked
    by the default export path — the range sweep is no longer CLI/test-only."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_out_of_range_run(eval_root, "run-range-bad")
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(
            eval_root=eval_root,
            out_dir=out_dir,
            admissibility_run_id="run-range-bad",
            expected_streams=["cycle.tick", "welfare"],
        )
    assert "range violation" in str(excinfo.value)
    assert "prediction_error" in str(excinfo.value)
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


# ---------------------------------------------------------------------------
# Scenario 4.3 (spec): a mid-run restart is flagged, not reported clean, and
# (per the design recommendation) blocked like any other inadmissible run.
# ---------------------------------------------------------------------------


def test_restart_seq_reset_blocked_by_default(tmp_path: Path):
    """A run whose per-sink seq resets mid-way (0,1,2,0,1) is flagged as a
    restart/multi-process condition and blocked by the default export path."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_restart_run(eval_root, "run-restart")
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(
            eval_root=eval_root,
            out_dir=out_dir,
            admissibility_run_id="run-restart",
            expected_streams=["cycle.tick", "welfare"],
        )
    assert "restart" in str(excinfo.value).lower()
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_restart_report_flags_not_clean_without_blocking(tmp_path: Path):
    """Same restart fixture, opted OUT of the clean gate: the manifest still
    flags the restart rather than reporting the run clean."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_restart_run(eval_root, "run-restart-flagged")
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
        admissibility_run_id="run-restart-flagged",
        expected_streams=["cycle.tick", "welfare"],
        require_admissible=False,
    )
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["admissible"] is False
    assert manifest["admissibility"]["restart_seq_resets"]
    assert any("restart" in r.lower() for r in manifest["admissibility"]["reasons"])


# ---------------------------------------------------------------------------
# Scenario 4.4 (spec): the explicit override exports and is recorded.
# ---------------------------------------------------------------------------


def test_admissibility_override_without_reason_raises(tmp_path: Path):
    """The override can never be triggered by a bare flag — a reason is
    mandatory, checked before anything is built."""
    from kaine.research.submission import (
        AdmissibilityOverrideError,
        build_research_bundle,
    )

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-int-override-noreason", complete=False)
    with pytest.raises(AdmissibilityOverrideError):
        build_research_bundle(
            eval_root=eval_root,
            out_dir=tmp_path / "out",
            admissibility_run_id="run-int-override-noreason",
            expected_streams=["cycle.tick", "welfare"],
            admissibility_override=True,
            # admissibility_override_reason intentionally omitted/blank.
        )


def test_explicit_override_exports_inadmissible_run_and_records_reason(
    tmp_path: Path,
):
    """The explicit override lets an inadmissible run through the default
    (blocking) export path, and the manifest records both the override and
    the operator's reason so it can never be mistaken for a clean export."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-int-override", complete=False)
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
        admissibility_run_id="run-int-override",
        expected_streams=["cycle.tick", "welfare"],
        # require_admissible left at its default (True) on purpose — the
        # override must work THROUGH the blocking default, not around it.
        admissibility_override=True,
        admissibility_override_reason="operator accepted a partial run for pilot analysis",
    )
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["admissible"] is False
    assert "admissibility_override" in manifest
    assert manifest["admissibility_override"]["overridden"] is True
    assert manifest["admissibility_override"]["reason"] == (
        "operator accepted a partial run for pilot analysis"
    )


# ---------------------------------------------------------------------------
# Auto-discovery: the gate fires with NO admissibility_run_id passed — this is
# the real operator/CLI path (build_research_bundle called with just
# eval_root/tier/out_dir), which is what closes the paper's §6.3 guarantee.
# ---------------------------------------------------------------------------


def test_auto_discovered_incomplete_run_blocked_by_default(tmp_path: Path):
    """A single inadmissible (incomplete) run is discovered from eval_root and
    blocked — no run_id, no require_admissible, nothing passed by the caller."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-auto-bad", complete=False)
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError):
        build_research_bundle(eval_root=eval_root, out_dir=out_dir)
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_auto_discovered_out_of_range_run_blocked_by_default(tmp_path: Path):
    """A single completeness-clean-but-out-of-range run discovered from
    eval_root is blocked by the default export path with no run_id passed."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_out_of_range_run(eval_root, "run-auto-range")
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(eval_root=eval_root, out_dir=out_dir)
    assert "range violation" in str(excinfo.value)
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_auto_discovered_multiple_run_ids_blocked_as_restart(tmp_path: Path):
    """Two distinct run_ids in one eval_root IS the restart/multi-process
    condition: discovered automatically and blocked by default."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-auto-a", complete=True)
    # A second, distinct run in the same logs (e.g. a crash/resume that minted
    # a fresh run_id) — each run is individually clean, but their coexistence
    # is the multi-process signal.
    (eval_root / "cycle.tick-2026-06-15.jsonl").write_text(
        "\n".join(
            json.dumps({"run_id": "run-auto-b", "seq": i, "tick_index": i,
                        "event_type": "cycle.tick"})
            for i in range(3)
        ) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(eval_root=eval_root, out_dir=out_dir)
    assert "restart" in str(excinfo.value).lower()
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_auto_discovered_clean_run_exports(tmp_path: Path):
    """A single clean run discovered from eval_root exports successfully."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-auto-ok", complete=True)
    bundle = build_research_bundle(eval_root=eval_root, out_dir=tmp_path / "out")
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["admissible"] is True
    assert manifest["range_admissibility"]["admissible"] is True


def test_auto_discovered_inadmissible_run_exportable_via_override(tmp_path: Path):
    """The explicit override still works on an AUTO-DISCOVERED inadmissible run
    (no run_id passed) and records the reason in the manifest."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-auto-override", complete=False)
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
        admissibility_override=True,
        admissibility_override_reason="operator accepted a partial pilot run",
    )
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["admissible"] is False
    assert manifest["admissibility_override"]["overridden"] is True
    assert manifest["admissibility_override"]["reason"] == (
        "operator accepted a partial pilot run"
    )


def test_cli_preview_blocks_on_inadmissible_eval_root(tmp_path: Path):
    """The REAL entry point: `python -m kaine.research --preview` against an
    eval_root holding an inadmissible run must fail (non-zero) and NOT print a
    clean preview — proving the gate fires at the operator CLI, not just in the
    library."""
    from io import StringIO

    from kaine.research.__main__ import main

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-cli-bad", complete=False)
    out_dir = tmp_path / "out"

    out_buf = StringIO()
    err_buf = StringIO()
    code = main(
        ["--preview", "--eval-root", str(eval_root), "--out-root", str(out_dir),
         "--config", str(tmp_path / "no-config.toml")],
        out=out_buf,
        err=err_buf,
    )
    assert code == 1, f"CLI must fail on an inadmissible run; got {code}"
    assert "inadmissible" in err_buf.getvalue().lower()
    # No bundle preview was emitted as if clean.
    assert "EXCLUDED" not in out_buf.getvalue()


# ---------------------------------------------------------------------------
# P1 bypass regressions: scan-scope must == copy-scope. The copy step is
# unscoped, so the gate MUST see every run present, reject a zero-match pin,
# and fail closed on unreadable logs — else inadmissible records ship under an
# `admissible: true` manifest.
# ---------------------------------------------------------------------------


def _plant_soma_out_of_range(eval_root: Path, run_id: str) -> None:
    """Append one out-of-range soma.report record for run_id (its own file)."""
    eval_root.mkdir(parents=True, exist_ok=True)
    with (eval_root / f"soma.report-{run_id}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "run_id": run_id, "seq": 0, "event_type": "soma.report",
            "prediction_error": -99.0,
        }) + "\n")


def test_pinned_run_still_detects_other_runs_present(tmp_path: Path):
    """P1-a: pinning a clean run must NOT hide a SECOND (bad) run in the same
    eval_root — the copy would ship its records. The gate blocks by default."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-A", complete=True)           # clean primary
    _plant_soma_out_of_range(eval_root, "run-B")            # unaccounted bad run
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(
            eval_root=eval_root,
            out_dir=out_dir,
            admissibility_run_id="run-A",  # pin the clean one
        )
    msg = str(excinfo.value).lower()
    # It is caught as the multi-process condition AND/OR the range violation.
    assert "restart" in msg or "range violation" in msg
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_pinned_nonexistent_run_id_does_not_vouch(tmp_path: Path):
    """P1-b: pinning a run_id that matches ZERO records must not vacuously pass
    while the copy ships the real (bad) data."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_soma_out_of_range(eval_root, "run-REAL-BAD")
    _plant_run(eval_root, "run-REAL-BAD", complete=True)
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(
            eval_root=eval_root,
            out_dir=out_dir,
            admissibility_run_id="typo-run-id",  # matches nothing
        )
    assert "zero records" in str(excinfo.value).lower()
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_pinned_zero_match_recorded_in_manifest_when_gate_off(tmp_path: Path):
    """The zero-match-pin condition is recorded honestly even with the clean
    gate opted out (require_admissible=False)."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-real", complete=True)
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
        admissibility_run_id="typo",
        require_admissible=False,
    )
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["admissible"] is False
    assert manifest["admissibility"]["pinned_zero_match"] is True
    assert any("zero records" in r.lower()
               for r in manifest["admissibility"]["reasons"])


def test_unreadable_logs_fail_closed(tmp_path: Path):
    """P1-c(ii): logs that can't be decrypted/parsed (no readable run) must NOT
    masquerade as `no_run_logs_present` — they fail closed."""
    from kaine.research.submission import AdmissibilityError, build_research_bundle

    eval_root = tmp_path / "evaluation"
    eval_root.mkdir(parents=True)
    # A ciphertext-looking line the (disabled/no-op) encryptor can't parse.
    (eval_root / "welfare-2026-06-14.jsonl").write_text(
        "not-json-not-decryptable-ciphertext\n", encoding="utf-8"
    )
    out_dir = tmp_path / "out"
    with pytest.raises(AdmissibilityError) as excinfo:
        build_research_bundle(eval_root=eval_root, out_dir=out_dir)
    assert "could not" in str(excinfo.value).lower()
    assert not list(out_dir.glob("research_bundle_*")) if out_dir.exists() else True


def test_unreadable_logs_exportable_via_override(tmp_path: Path):
    """The unreadable-logs fail-closed is overridable via the explicit override,
    and the manifest records the unreadable marker."""
    from kaine.research.submission import build_research_bundle

    eval_root = tmp_path / "evaluation"
    eval_root.mkdir(parents=True)
    (eval_root / "welfare-2026-06-14.jsonl").write_text(
        "unparseable\n", encoding="utf-8"
    )
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
        admissibility_override=True,
        admissibility_override_reason="known plaintext debris; verified out of band",
    )
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["admissibility"]["status"] == "unreadable_logs"
    assert manifest["admissibility"]["admissible"] is False
    assert manifest["admissibility_override"]["overridden"] is True


# ---------------------------------------------------------------------------
# P2: whitespace-only override reason is rejected.
# ---------------------------------------------------------------------------


def test_admissibility_override_whitespace_only_reason_raises(tmp_path: Path):
    from kaine.research.submission import (
        AdmissibilityOverrideError,
        build_research_bundle,
    )

    eval_root = tmp_path / "evaluation"
    _plant_run(eval_root, "run-ws", complete=False)
    with pytest.raises(AdmissibilityOverrideError):
        build_research_bundle(
            eval_root=eval_root,
            out_dir=tmp_path / "out",
            admissibility_override=True,
            admissibility_override_reason="  \t\n ",
        )


# ---------------------------------------------------------------------------
# P1-c(i): the CLI installs the configured state encryptor BEFORE scanning, so
# encrypted logs are actually read (else the gate fails open on ciphertext).
# ---------------------------------------------------------------------------


def test_cli_installs_encryptor_before_scan(tmp_path: Path, monkeypatch):
    """With [security.state_encryption].enabled=true and encrypted logs holding
    an inadmissible run, the CLI must install the encryptor, READ the run, and
    BLOCK. Without the install it would see ciphertext → 0 runs → export."""
    import os
    from io import StringIO

    from kaine.research.__main__ import main
    from kaine.security.crypto import (
        CryptoConfig,
        StateEncryptor,
        set_state_encryptor,
    )

    key = os.urandom(32).hex()
    monkeypatch.setenv("KAINE_STATE_KEY", key)

    # Write an ENCRYPTED, out-of-range run.
    enc = StateEncryptor(CryptoConfig(enabled=True))
    eval_root = tmp_path / "evaluation"
    eval_root.mkdir(parents=True)
    with (eval_root / "soma.report-2026-06-14.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(enc.encrypt_text(json.dumps({
            "run_id": "run-enc-bad", "seq": 0, "event_type": "soma.report",
            "prediction_error": -5.0,
        })) + "\n")

    # Isolate from the repo's operator config (chdir so the relative
    # OPERATOR_CONFIG_PATH resolves under tmp and finds nothing).
    monkeypatch.chdir(tmp_path)

    # Simulate a fresh process: NOTHING has installed the real encryptor yet.
    set_state_encryptor(StateEncryptor(CryptoConfig()))
    try:
        cfg_path = tmp_path / "kaine.toml"
        cfg_path.write_text(
            "[security.state_encryption]\nenabled = true\n"
            "[research_submission]\nenabled = false\nrecipient = \"\"\n",
            encoding="utf-8",
        )
        out_buf, err_buf = StringIO(), StringIO()
        code = main(
            ["--preview", "--eval-root", str(eval_root),
             "--out-root", str(tmp_path / "out"), "--config", str(cfg_path)],
            out=out_buf, err=err_buf,
        )
        assert code == 1, (
            "CLI must install the encryptor, read the encrypted inadmissible "
            f"run, and block; got {code}. err={err_buf.getvalue()!r}"
        )
        assert "inadmissible" in err_buf.getvalue().lower()
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig()))


def test_cli_expected_stream_flag_triggers_missing_stream_block(tmp_path: Path):
    """P2 wiring: --expected-stream reaches scan_run so the missing-stream half
    of the completeness gate can fire at the real entry point."""
    from io import StringIO

    from kaine.research.__main__ import main

    eval_root = tmp_path / "evaluation"
    # A run that produced cycle.tick but NOT welfare.
    eval_root.mkdir(parents=True)
    (eval_root / "cycle.tick-2026-06-14.jsonl").write_text(
        "\n".join(
            json.dumps({"run_id": "run-missing", "seq": i, "tick_index": i,
                        "event_type": "cycle.tick"})
            for i in range(3)
        ) + "\n",
        encoding="utf-8",
    )
    out_buf, err_buf = StringIO(), StringIO()
    code = main(
        ["--preview", "--eval-root", str(eval_root),
         "--out-root", str(tmp_path / "out"),
         "--config", str(tmp_path / "no-config.toml"),
         "--expected-stream", "cycle.tick", "--expected-stream", "welfare"],
        out=out_buf, err=err_buf,
    )
    assert code == 1
    assert "welfare" in err_buf.getvalue().lower()
