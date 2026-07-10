# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Claude Science export adapter.

PARAMOUNT: the export is a THIN ADAPTER over the research-participation bundle
builder. Its only input is a builder-produced ``Bundle``; it reads ONLY from
``bundle.bundle_dir`` and is structurally incapable of reaching the raw bus
archive, memories, the self-model, the intent log/monologue, or conversation
content. These tests extend the decoy guarantee in test_research_submission.py
one hop downstream to the export — by construction, not by inspection.
"""

from __future__ import annotations

import inspect
import json
from io import StringIO
from pathlib import Path

import pytest

from kaine.research.claude_science_export import (
    ClaudeScienceExportError,
    DisclosureAttestation,
    export_project,
    plan_project,
    preview_project,
)
from kaine.research.submission import (
    DENY_PATTERNS,
    METRICS_ONLY_DIRS,
    Bundle,
    build_research_bundle,
)


# ---------------------------------------------------------------------------
# Fixtures — an eval root seeded with EVERY allowlisted family plus the standard
# decoy sensitive files (mirrors test_research_submission._make_eval_root).
# ---------------------------------------------------------------------------

DECOY_FILES = {
    "intent_expression.jsonl": (
        '{"intent": "user said something private", "expression": "entity replied"}\n'
    ),
    "mnemos_short_term.jsonl": '{"id": "mem1", "text": "private memory"}\n',
    "eidolon_self_model.json": '{"name": "entity identity", "values": []}',
    "conversation_2026-06-07.jsonl": '{"turn": "user: hello", "response": "hi"}\n',
    "replay_2026-06-07.jsonl": '{"memory_text": "verbatim episodic content"}\n',
}


def _make_eval_root(tmp_path: Path) -> Path:
    eval_root = tmp_path / "evaluation"
    for subdir in METRICS_ONLY_DIRS:
        d = eval_root / subdir
        d.mkdir(parents=True)
        (d / f"{subdir}-2026-06-07.jsonl").write_text(
            '{"value": 0.42, "ts": "2026-06-07T00:00:00Z"}\n', encoding="utf-8"
        )
    for name, content in DECOY_FILES.items():
        (eval_root / name).write_text(content, encoding="utf-8")
    return eval_root


def _build_bundle(tmp_path: Path) -> Bundle:
    """Build a real allowlisted metrics bundle (no run logs -> export allowed)."""
    return build_research_bundle(
        eval_root=_make_eval_root(tmp_path), out_dir=tmp_path / "bundle_out"
    )


def _all_project_files(project_dir: Path) -> list[Path]:
    return [p for p in project_dir.rglob("*") if p.is_file()]


# ---------------------------------------------------------------------------
# 6.1 — every output data file's stem is allowlisted; no denied path
# ---------------------------------------------------------------------------


def test_output_data_files_are_subset_of_allowlist(tmp_path: Path):
    bundle = _build_bundle(tmp_path)
    project = export_project(bundle=bundle, out_dir=tmp_path / "cs", plan=True)

    data_dir = project.project_dir / "data"
    data_files = sorted(data_dir.glob("*"))
    assert data_files, "expected reshaped metric files"
    for f in data_files:
        assert f.stem in METRICS_ONLY_DIRS, (
            f"output data file {f.name!r} is not an allowlisted family"
        )

    # No output path anywhere may match a deny pattern.
    for f in _all_project_files(project.project_dir):
        rel = str(f.relative_to(project.project_dir)).lower()
        for pat in DENY_PATTERNS:
            assert pat not in rel, f"deny pattern {pat!r} in output path {rel!r}"


# ---------------------------------------------------------------------------
# 6.2 — decoy filenames AND their contents never appear anywhere
# ---------------------------------------------------------------------------


def test_decoys_never_appear_in_project(tmp_path: Path):
    bundle = _build_bundle(tmp_path)
    project = export_project(bundle=bundle, out_dir=tmp_path / "cs", plan=True)

    decoy_content_substrings = [
        "user said something private",
        "private memory",
        "entity identity",
        "user: hello",
        "verbatim episodic content",
    ]
    for f in _all_project_files(project.project_dir):
        blob = f.read_text(encoding="utf-8", errors="replace")
        name = f.name
        for decoy_name in DECOY_FILES:
            assert decoy_name not in blob, (
                f"decoy filename {decoy_name!r} leaked into {name!r}"
            )
        for substr in decoy_content_substrings:
            assert substr not in blob, (
                f"decoy content {substr!r} leaked into {name!r}"
            )


# ---------------------------------------------------------------------------
# 6.3 — the public API takes no eval_root/store/bus argument; a file OUTSIDE
# bundle_dir is never read.
# ---------------------------------------------------------------------------


def test_export_signature_has_no_raw_data_input():
    sig = inspect.signature(export_project)
    forbidden = {"eval_root", "store", "bus", "event_bus", "memory", "monologue"}
    assert not (set(sig.parameters) & forbidden), (
        f"export_project must not accept a raw-data input; params={list(sig.parameters)}"
    )
    assert set(sig.parameters) <= {"bundle", "out_dir", "plan", "attestation"}


def test_export_never_reads_outside_bundle_dir(tmp_path: Path):
    bundle = _build_bundle(tmp_path)
    # Plant a sensitive file OUTSIDE the bundle dir (a sibling under bundle_out).
    outside = bundle.bundle_dir.parent / "SECRET_outside_bundle.jsonl"
    outside.write_text('{"secret": "must never be read"}\n', encoding="utf-8")

    project = export_project(bundle=bundle, out_dir=tmp_path / "cs")
    for f in _all_project_files(project.project_dir):
        blob = f.read_text(encoding="utf-8", errors="replace")
        assert "must never be read" not in blob
        assert "SECRET_outside_bundle" not in blob


# ---------------------------------------------------------------------------
# 6.4 — an encrypted bundle is refused, not leaked
# ---------------------------------------------------------------------------


def test_encrypted_bundle_is_refused(tmp_path: Path):
    out_dir = tmp_path / "cs"
    enc_bundle = Bundle(
        bundle_dir=tmp_path / "bundle_out" / "research_bundle_x",
        tier="metrics",
        generated_at="2026-06-07T00:00:00+00:00",
        encrypted=True,
    )
    with pytest.raises(ClaudeScienceExportError):
        export_project(bundle=enc_bundle, out_dir=out_dir)
    # Nothing written.
    assert not out_dir.exists() or not list(out_dir.glob("claude_science_project_*"))


def test_encrypted_bundle_refused_before_preview(tmp_path: Path):
    enc_bundle = Bundle(
        bundle_dir=tmp_path / "b",
        tier="metrics",
        generated_at="2026-06-07T00:00:00+00:00",
        encrypted=True,
    )
    with pytest.raises(ClaudeScienceExportError):
        plan_project(bundle=enc_bundle, out_dir=tmp_path / "cs")


# ---------------------------------------------------------------------------
# 6.5 — preview lists files and ends with the EXCLUDED footer
# ---------------------------------------------------------------------------


def test_preview_lists_files_and_excluded_footer(tmp_path: Path):
    bundle = _build_bundle(tmp_path)
    project = plan_project(bundle=bundle, out_dir=tmp_path / "cs", plan=True)
    text = preview_project(project)

    assert "README.md" in text
    assert "manifest.json" in text
    assert "ab_divergence" in text
    # EXCLUDED footer names every sensitive content type.
    assert "EXCLUDED" in text
    assert "intent log" in text.lower() or "intent_expression" in text.lower()
    assert "memories" in text.lower() or "mnemos" in text.lower()
    assert "self-model" in text.lower() or "eidolon" in text.lower()
    assert "conversation" in text.lower()
    assert "monologue" in text.lower()
    assert "raw bus archive" in text.lower()
    # The EXCLUDED section is a footer: it comes after the file list.
    assert text.index("Files to be written") < text.index("EXCLUDED")


# ---------------------------------------------------------------------------
# Contents: manifest copied verbatim; README carries the boundaries
# ---------------------------------------------------------------------------


def test_manifest_copied_verbatim_and_readme_states_boundaries(tmp_path: Path):
    bundle = _build_bundle(tmp_path)
    project = export_project(bundle=bundle, out_dir=tmp_path / "cs", plan=True)

    copied = (project.project_dir / "manifest.json").read_text(encoding="utf-8")
    assert copied == bundle.manifest_path.read_text(encoding="utf-8")

    readme = (project.project_dir / "README.md").read_text(encoding="utf-8")
    assert "de-identified" in readme.lower()
    assert "external disclosure" in readme.lower()
    assert "not authoritative" in readme.lower() or "exploratory" in readme.lower()
    # admissibility verdict from the manifest is surfaced.
    assert "admissib" in readme.lower()


def test_admissibility_verdict_travels_into_export(tmp_path: Path):
    """An admissible run's verdict is present in the copied manifest and the
    exploratory-not-authoritative boundary is stated in the project."""
    eval_root = tmp_path / "evaluation"
    # Plant a clean, in-range single run.
    ticks = [
        {"run_id": "run-ok", "seq": i, "tick_index": i, "event_type": "cycle.tick"}
        for i in range(3)
    ]
    (eval_root).mkdir(parents=True)
    (eval_root / "cycle.tick-2026-06-14.jsonl").write_text(
        "\n".join(json.dumps(r) for r in ticks) + "\n", encoding="utf-8"
    )
    (eval_root / "welfare-2026-06-14.jsonl").write_text(
        "\n".join(json.dumps({"run_id": "run-ok", "seq": i, "v": i}) for i in range(2))
        + "\n",
        encoding="utf-8",
    )
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "bundle_out",
        expected_streams=["cycle.tick", "welfare"],
    )
    project = export_project(bundle=bundle, out_dir=tmp_path / "cs")
    manifest = json.loads((project.project_dir / "manifest.json").read_text())
    assert manifest["admissibility"]["admissible"] is True
    readme = (project.project_dir / "README.md").read_text(encoding="utf-8")
    assert "not authoritative" in readme.lower() or "exploratory" in readme.lower()


# ---------------------------------------------------------------------------
# Attestation recorded with the project
# ---------------------------------------------------------------------------


def test_attestation_recorded_with_project(tmp_path: Path):
    bundle = _build_bundle(tmp_path)
    att = DisclosureAttestation(operator="Guardian A", reason="paper write-up")
    project = export_project(bundle=bundle, out_dir=tmp_path / "cs", attestation=att)

    disclosure = json.loads((project.project_dir / "disclosure.json").read_text())
    assert disclosure["external_disclosure"] is True
    assert disclosure["operator"] == "Guardian A"
    assert disclosure["reason"] == "paper write-up"
    readme = (project.project_dir / "README.md").read_text(encoding="utf-8")
    assert "Guardian A" in readme


# ---------------------------------------------------------------------------
# 6.6 — shipped config guard: the block ships disabled
# ---------------------------------------------------------------------------


def test_shipped_config_claude_science_disabled():
    import tomllib

    root = Path(__file__).parent.parent
    config = tomllib.loads((root / "config" / "kaine.toml").read_text())
    cs = (config.get("research_submission", {}) or {}).get("claude_science", {})
    assert cs.get("enabled", False) is False, (
        "shipped config must ship [research_submission.claude_science].enabled = false"
    )


# ---------------------------------------------------------------------------
# 6.7 — CLI fails safe: --claude-science with EOF at confirm writes nothing
# ---------------------------------------------------------------------------


def test_cli_claude_science_eof_fails_safe(tmp_path: Path):
    from kaine.research.__main__ import main

    eval_root = _make_eval_root(tmp_path)
    cs_out = tmp_path / "cs"

    def eof_input(prompt):
        raise EOFError("simulated EOF")

    out_buf, err_buf = StringIO(), StringIO()
    code = main(
        ["--claude-science", "--eval-root", str(eval_root),
         "--out-root", str(tmp_path / "bundle_out"),
         "--claude-science-out", str(cs_out),
         "--config", str(tmp_path / "no-config.toml")],
        input_fn=eof_input,
        out=out_buf,
        err=err_buf,
    )
    assert code == 2, f"EOF at confirm must return no-write code 2; got {code}"
    assert not cs_out.exists() or not list(cs_out.glob("claude_science_project_*")), (
        "no project folder may be written on a fail-safe abort"
    )
    # The preview (with EXCLUDED footer) was still shown before the abort.
    assert "EXCLUDED" in out_buf.getvalue()


def test_cli_claude_science_decline_fails_safe(tmp_path: Path):
    from kaine.research.__main__ import main

    eval_root = _make_eval_root(tmp_path)
    cs_out = tmp_path / "cs"
    answers = iter(["Guardian A", "reason", "n"])

    out_buf, err_buf = StringIO(), StringIO()
    code = main(
        ["--claude-science", "--eval-root", str(eval_root),
         "--out-root", str(tmp_path / "bundle_out"),
         "--claude-science-out", str(cs_out),
         "--config", str(tmp_path / "no-config.toml")],
        input_fn=lambda prompt: next(answers),
        out=out_buf,
        err=err_buf,
    )
    assert code == 2
    assert not cs_out.exists() or not list(cs_out.glob("claude_science_project_*"))


def test_cli_claude_science_confirm_writes_project(tmp_path: Path):
    from kaine.research.__main__ import main

    eval_root = _make_eval_root(tmp_path)
    cs_out = tmp_path / "cs"
    answers = iter(["Guardian A", "paper write-up", "y"])

    out_buf, err_buf = StringIO(), StringIO()
    code = main(
        ["--claude-science", "--plan", "--eval-root", str(eval_root),
         "--out-root", str(tmp_path / "bundle_out"),
         "--claude-science-out", str(cs_out),
         "--config", str(tmp_path / "no-config.toml")],
        input_fn=lambda prompt: next(answers),
        out=out_buf,
        err=err_buf,
    )
    assert code == 0, f"confirmed export must succeed; err={err_buf.getvalue()!r}"
    projects = list(cs_out.glob("claude_science_project_*"))
    assert len(projects) == 1
    assert (projects[0] / "README.md").is_file()
    assert (projects[0] / "manifest.json").is_file()
    assert (projects[0] / "plan.json").is_file()
    assert (projects[0] / "disclosure.json").is_file()
