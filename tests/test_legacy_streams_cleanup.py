# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import io

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.bus import legacy_streams


@pytest.fixture
def fake_client(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis()
    monkeypatch.setattr(legacy_names, "SCOPE_STATUS", {"keys": "done"})
    monkeypatch.setattr(
        legacy_names,
        "STREAM_NAMES",
        [
            {"scope": "keys", "old": "hypnos.out", "new": "sleep.out"},
            {"scope": "keys", "old": "eidolon.self_model", "new": "self_model.out"},
        ],
    )
    yield client


def test_survey_and_deletable(fake_client):
    client = fake_client
    client.xadd("hypnos.out", {"payload": b"a"})
    client.xadd("hypnos.out", {"payload": b"b"})
    client.xadd("hypnos.out", {"payload": b"c"})
    client.xadd("sleep.out", {"payload": b"d"})
    client.set("eidolon.self_model", "plain")

    entries = legacy_streams.survey(client)
    hypnos = next(e for e in entries if e.old == "hypnos.out")
    assert hypnos.present
    assert hypnos.is_stream
    assert hypnos.length == 3

    deletable = legacy_streams.deletable(entries)
    assert [e.old for e in deletable] == ["hypnos.out"]


def test_main_delete_confirmed(fake_client):
    client = fake_client
    client.xadd("hypnos.out", {"payload": b"a"})
    client.xadd("hypnos.out", {"payload": b"b"})
    client.xadd("hypnos.out", {"payload": b"c"})
    client.xadd("sleep.out", {"payload": b"d"})
    client.set("eidolon.self_model", "plain")

    out = io.StringIO()
    err = io.StringIO()
    ret = legacy_streams.main(
        ["--delete"],
        client=client,
        input_fn=lambda prompt: "DELETE 1 OLD STREAMS",
        out=out,
        err=err,
    )
    assert ret == 0
    assert not client.exists("hypnos.out")
    assert client.exists("sleep.out")
    assert client.get("eidolon.self_model") == b"plain"
    output = out.getvalue()
    assert "hypnos.out" in output
    assert "sleep.out" in output
    assert "deleted: hypnos.out" in output


def test_main_delete_wrong_confirmation(fake_client):
    client = fake_client
    client.xadd("hypnos.out", {"payload": b"a"})

    out = io.StringIO()
    ret = legacy_streams.main(
        ["--delete"],
        client=client,
        input_fn=lambda prompt: "no",
        out=out,
    )
    assert ret == 5
    assert client.exists("hypnos.out")


def test_main_no_delete(fake_client):
    client = fake_client
    client.xadd("hypnos.out", {"payload": b"a"})

    out = io.StringIO()
    ret = legacy_streams.main([], client=client, out=out)
    assert ret == 0
    assert client.exists("hypnos.out")
    assert "Run again with --delete" in out.getvalue()


def test_main_never_deletes_live_streams(fake_client, monkeypatch):
    client = fake_client
    client.xadd("hypnos.out", {"payload": b"a"})
    client.xadd("sleep.out", {"payload": b"b"})

    def fake_orphaned(live):
        return ["hypnos.out", "sleep.out"]

    monkeypatch.setattr(legacy_aliases, "orphaned_stream_names", fake_orphaned)
    entries = legacy_streams.survey(client)
    deletable = legacy_streams.deletable(entries)
    assert [e.old for e in deletable] == ["hypnos.out"]
