# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The heard-trace scan reports counts and ids only and changes nothing it reads."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "scan_heard_traces", REPO_ROOT / "tools" / "maintainer" / "scan_heard_traces.py"
)
scan = importlib.util.module_from_spec(_spec)
sys.modules["scan_heard_traces"] = scan  # dataclasses look the module up by name
_spec.loader.exec_module(scan)

from kaine.lifecycle.snapshot import ForkSnapshot, save_snapshot  # noqa: E402
from kaine.modules.episodic_memory.storage import SqliteVecStorage  # noqa: E402

SECRET = "PURPLE-HERON-4471 hello there"

LEGACY_CHAT = f"active | embodiment:embodiment.chat={{'message': '{SECRET}', 'sender': 'Avatar Two'}}"
LEGACY_IM = f"active | embodiment:embodiment.im={{'message': '{SECRET}'}}"
LEGACY_NESTED = (
    "active | vision:vision.report={'change_score': 0.4} | "
    f"social_cognition:social_cognition.update={{'partner': {{'heard_text': '{SECRET}'}}}}"
)
CLEAN = (
    "active | audition:audition.transcription=<heard omitted> | "
    "audition:audition.transcription=<raw-perceptual omitted> | "
    "embodiment:embodiment.im=<unclassified omitted> | "
    "episodic_memory:episodic_memory.replay=<replay of abc123> | "
    "language:external_speech={'text': 'the light keeps changing', 'mode': 'external'} | "
    "affect:affect.state={'state': {'valence': nan, 'arousal': 0.2}, 'label': 'calm'}"
)


@pytest.fixture(autouse=True)
def _restore_state_encryptor():
    from kaine.security import crypto

    saved = crypto._active
    yield
    crypto._active = saved


def _sha(paths) -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.is_file()}


# --- classification -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (LEGACY_CHAT, [("external_input", "embodiment:embodiment.chat")]),
        (LEGACY_IM, [("undeclared_text", "embodiment:<undeclared type>")]),
        (LEGACY_NESTED, [("heard_field", "social_cognition:<undeclared type>")]),
        (CLEAN, []),
        ("active | vision:vision.report={'change_score': 0.25}", []),
        ("active", []),
        # A payload that cannot be read back is counted on the safe side.
        (f"active | planning:planning.belief={{'x': object at 0x1, 'y': '{SECRET}'}}", [
            ("unparsed", "planning:planning.belief")
        ]),
        ("active | affect:affect.state={'x': <object>, 'label': 'calm'}", []),
        (
            f"active | affect:affect.state={{'x': <object>, 'heard_text': '{SECRET}'}}",
            [("unparsed", "affect:affect.state")],
        ),
    ],
)
def test_classify_trace(text, expected):
    assert scan.classify_trace(text) == expected


def _old_module_key(new_key: str) -> str:
    """The pre-rename module name, read from the rename table (never spelled here)."""
    from kaine import legacy_names

    (old,) = [k for k, e in legacy_names.MODULES.items() if e["new_key"] == new_key]
    return old


def test_legacy_module_names_are_mapped():
    # The language module's own speech under the pre-rename module name is own speech.
    text = f"active | {_old_module_key('language')}:external_speech={{'text': 'my own words'}}"
    assert scan.classify_trace(text) == []


def test_default_collection_prefixes_come_from_the_rename_table():
    from kaine import legacy_names

    prefixes = scan.default_collection_prefixes()
    assert prefixes[0] == "episodic_memory_"
    assert len(prefixes) >= 2
    for old in prefixes[1:]:
        assert legacy_names.PERSISTED_EXACT[old] == "episodic_memory_"


# --- the readers report no content and change nothing -----------------------------


def _check_output(capsys, *, flagged_ids):
    out = capsys.readouterr().out
    assert "PURPLE-HERON" not in out
    assert "hello there" not in out
    assert "Avatar Two" not in out
    for trace_id in flagged_ids:
        assert trace_id in out
    return out


@pytest.mark.asyncio
async def test_sqlite_store_scan(tmp_path: Path, capsys):
    pytest.importorskip("sqlite_vec")
    db_path = tmp_path / "episodic_memory.db"
    storage = SqliteVecStorage(latent_dim=4, db_path=str(db_path))
    await storage.initialize()
    ids = {}
    try:
        await storage.ensure_collection("episodic_memory_episodic")
        for name, text in [("chat", LEGACY_CHAT), ("im", LEGACY_IM), ("clean", CLEAN)]:
            ids[name] = await storage.upsert(
                "episodic_memory_episodic",
                vector=[1.0, 0.0, 0.0, 0.0],
                text=text,
                payload={},
                affect=None,
            )
    finally:
        await storage.shutdown()
    before = _sha(tmp_path.iterdir())

    assert scan.main(["--sqlite", str(db_path)]) == 1
    out = _check_output(
        capsys,
        flagged_ids=[f"episodic_memory_episodic:{ids['chat']}", f"episodic_memory_episodic:{ids['im']}"],
    )
    assert f"episodic_memory_episodic:{ids['clean']}" not in out
    assert "3 traces, 2 flagged" in out
    assert _sha(tmp_path.iterdir()) == before


def _memory_state(texts):
    return {
        "collection_prefix": "episodic_memory_",
        "short_term": [{"text": texts[0], "payload": {}, "affect": None}],
        "persisted": {
            "episodic_memory_episodic": [
                {"id": f"p{i}", "vector": [0.0], "text": t, "payload": {}, "affect": None}
                for i, t in enumerate(texts[1:])
            ]
        },
    }


def test_fork_root_scan(tmp_path: Path, capsys):
    root = tmp_path / "forks"
    snap = ForkSnapshot(
        modules={"episodic_memory": {"memory_state": _memory_state([LEGACY_NESTED, CLEAN, LEGACY_CHAT])}}
    )
    path = save_snapshot(root, snap)
    before = _sha([path])

    assert scan.main(["--fork-root", str(root), "--json"]) == 1
    out = _check_output(
        capsys,
        flagged_ids=[
            "episodic_memory/short_term[0]",
            "episodic_memory/episodic_memory_episodic:p1",
        ],
    )
    (report,) = json.loads(out)["reports"]
    assert report["traces"] == 3
    assert report["flagged"] == 2
    assert report["by_category"]["heard_field"] == 1
    assert report["by_category"]["external_input"] == 1
    assert _sha([path]) == before


def test_bundle_scan(tmp_path: Path, capsys):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    snapshot_json = json.dumps(
        ForkSnapshot(modules={"episodic_memory": {"memory_state": _memory_state([CLEAN, LEGACY_IM])}}).to_dict()
    ).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("snapshot.json")
        info.size = len(snapshot_json)
        tf.addfile(info, io.BytesIO(snapshot_json))
    (bundle / "bundle.tar").write_bytes(buf.getvalue())
    before = _sha(bundle.iterdir())

    assert scan.main(["--bundle", str(bundle)]) == 1
    _check_output(capsys, flagged_ids=["episodic_memory/episodic_memory_episodic:p0"])
    assert _sha(bundle.iterdir()) == before


def test_clean_source_exits_zero(tmp_path: Path, capsys):
    root = tmp_path / "forks"
    save_snapshot(root, ForkSnapshot(modules={"episodic_memory": {"memory_state": _memory_state([CLEAN, CLEAN])}}))
    assert scan.main(["--fork-root", str(root)]) == 0
    assert "2 traces, 0 flagged" in capsys.readouterr().out


def test_unreadable_source_exits_two_without_content(tmp_path: Path, capsys):
    assert scan.main(["--sqlite", str(tmp_path / "missing.db")]) == 2
    assert "ERROR" in capsys.readouterr().out


# Header-like strings planted inside heard text (second review, R3).
PLANTED = [
    "active | embodiment:embodiment.chat={'message': "
    + "'meet me | Alice_Smith:lives.at_12_Elm_Street=yes', 'sender': 'Bob'}",
    # A planted header that names a real module, with a made-up type.
    "active | embodiment:embodiment.im={'message': "
    + "'x | embodiment:embodiment.Elm_Street_flat_4={1: 2}'}",
    # A planted header with an unknown source and a declared-looking type.
    "active | mystery:mystery.thing={'note': 'y | Carol_Jones:affect.state={3: 4}'}",
]
PLANTED_WORDS = ("Alice_Smith", "lives", "Elm_Street", "Bob", "meet me", "Carol_Jones", "flat_4")


def test_planted_headers_are_never_named():
    for text in PLANTED:
        for _category, label in scan.classify_trace(text):
            for word in PLANTED_WORDS:
                assert word not in label
    labels = {label for text in PLANTED for _c, label in scan.classify_trace(text)}
    assert scan.UNRECOGNISED_MEMBER in labels
    assert "embodiment:embodiment.chat" in labels
    assert "embodiment:<undeclared type>" in labels


@pytest.mark.parametrize("as_json", [False, True])
def test_planted_headers_are_not_echoed_in_the_report(tmp_path: Path, capsys, as_json):
    root = tmp_path / "forks"
    save_snapshot(
        root,
        ForkSnapshot(modules={"episodic_memory": {"memory_state": _memory_state(PLANTED)}}),
    )
    argv = ["--fork-root", str(root)] + (["--json"] if as_json else [])
    assert scan.main(argv) == 1
    out = capsys.readouterr().out
    for word in PLANTED_WORDS:
        assert word not in out
    assert scan.UNRECOGNISED_MEMBER in out
    if as_json:
        (report,) = json.loads(out)["reports"]
        assert report["flagged"] == 3
        for label in report["by_member_type"]:
            for word in PLANTED_WORDS:
                assert word not in label


@pytest.mark.parametrize("as_json", [False, True])
def test_error_holds_the_exception_type_and_source_only(tmp_path: Path, capsys, monkeypatch, as_json):
    path = tmp_path / "snapshot.json"
    path.write_text("{}")

    def _raise(_path):
        raise ValueError(f"could not decode {SECRET}")
        yield  # pragma: no cover

    monkeypatch.setattr(scan, "snapshot_file_traces", _raise)
    argv = ["--snapshot", str(path)] + (["--json"] if as_json else [])
    assert scan.main(argv) == 2
    out = capsys.readouterr().out
    assert "PURPLE-HERON" not in out
    assert "could not decode" not in out
    if as_json:
        (report,) = json.loads(out)["reports"]
        assert report["error"] == f"ValueError reading snapshot:{path}"
    else:
        assert f"ERROR ValueError reading snapshot:{path}" in out
