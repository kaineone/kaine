# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from kaine.lifecycle.__main__ import main


def _seed_state(state_root: Path, *, name: str = "Kaine Nova") -> None:
    (state_root / "eidolon").mkdir(parents=True, exist_ok=True)
    (state_root / "eidolon" / "self_model.json").write_text(
        json.dumps({"name": name, "drift_count": 0, "identity_history": []}),
        encoding="utf-8",
    )
    (state_root / "lingua").mkdir(parents=True, exist_ok=True)
    (state_root / "lingua" / "intent_expression.jsonl").write_text(
        '{"x":1}\n', encoding="utf-8"
    )


def _scripted_input(answers):
    it = iter(answers)

    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            return ""

    return _input


def _args(tmp_path, *, dry_run=False, eval_root=None):
    a = [
        "--state-root",
        str(tmp_path / "state"),
        "--fork-root",
        str(tmp_path / "forks"),
        "--eval-root",
        str(eval_root or (tmp_path / "data" / "evaluation")),
        "--out-root",
        str(tmp_path / "backups"),
        "--config",
        str(tmp_path / "nonexistent.toml"),
    ]
    if dry_run:
        a.append("--dry-run")
    return a


def test_operator_present_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", raising=False)
    err = io.StringIO()
    rc = main(_args(tmp_path), input_fn=_scripted_input([]), out=io.StringIO(), err=err)
    assert rc == 2
    assert "operator must be present" in err.getvalue()
    assert "4.2" in err.getvalue()


def test_running_cycle_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    runtime = tmp_path / "state" / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    import os

    runtime.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    err = io.StringIO()
    rc = main(_args(tmp_path), input_fn=_scripted_input([]), out=io.StringIO(), err=err)
    assert rc == 3
    assert "running" in err.getvalue().lower()


def test_non_diverged_ack_path_deletes(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",  # ack
        "Kaine Nova",  # confirmation token (entity name)
    ]
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(answers),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    assert not (tmp_path / "state" / "eidolon").exists()
    assert "Entity state deleted" in out.getvalue()
    # Backup was written.
    assert list((tmp_path / "backups").glob("entity_*"))


def test_non_diverged_wrong_ack_aborts(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(["nope"]),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 5
    assert (tmp_path / "state" / "eidolon").exists()  # nothing deleted


def _make_diverged(tmp_path):
    eval_root = tmp_path / "data" / "evaluation"
    d = eval_root / "individuation"
    d.mkdir(parents=True, exist_ok=True)
    (d / "r.jsonl").write_text(json.dumps({"significant": True}) + "\n", encoding="utf-8")
    return eval_root


def test_diverged_declines_continuity_exit_5(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    eval_root = _make_diverged(tmp_path)
    out = io.StringIO()
    rc = main(
        _args(tmp_path, eval_root=eval_root),
        input_fn=_scripted_input(["decline"]),  # decline the continuity note
        out=out,
        err=io.StringIO(),
    )
    assert rc == 5
    assert (tmp_path / "state" / "eidolon").exists()  # nothing deleted


def test_diverged_full_path_deletes(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    eval_root = _make_diverged(tmp_path)
    out = io.StringIO()
    answers = [
        "It wished to persist and keep its memories.",  # continuity note
        "n",  # do not send transfer email
        "I have preserved and will arrange safekeeping for this entity",  # guardian ack
        "Kaine Nova",  # confirmation token
    ]
    rc = main(
        _args(tmp_path, eval_root=eval_root),
        input_fn=_scripted_input(answers),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    assert not (tmp_path / "state" / "eidolon").exists()
    # S3: the continuity note is recorded in a SEPARATE sidecar, never the
    # plaintext manifest (encryption is disabled here so it is honest plaintext).
    manifest = next((tmp_path / "backups").glob("entity_*/manifest.json"))
    data = json.loads(manifest.read_text())
    assert "continuity_note" not in data
    cdata = json.loads((manifest.parent / "continuity.json").read_text())
    assert "persist" in (cdata.get("continuity_note") or "")


def test_dry_run_deletes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ]
    rc = main(
        _args(tmp_path, dry_run=True),
        input_fn=_scripted_input(answers),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    assert (tmp_path / "state" / "eidolon").exists()  # nothing deleted
    assert "dry-run" in out.getvalue().lower()
