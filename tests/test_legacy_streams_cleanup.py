# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import io
import time

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.bus import legacy_streams
from kaine.bus.legacy_streams import _render_status, deletable, main, survey

# Old streams seeded by these tests were last written well outside the
# recently-written window, so the cleanup treats them as settled.
_AGED_MS = int(time.time() * 1000) - 60 * 60 * 1000
_seq = iter(range(1, 1_000_000))


def _aged_id():
    return f"{_AGED_MS}-{next(_seq)}"


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
    client.xadd("hypnos.out", {"payload": b"a"}, id=_aged_id())
    client.xadd("hypnos.out", {"payload": b"b"}, id=_aged_id())
    client.xadd("hypnos.out", {"payload": b"c"}, id=_aged_id())
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
    client.xadd("hypnos.out", {"payload": b"a"}, id=_aged_id())
    client.xadd("hypnos.out", {"payload": b"b"}, id=_aged_id())
    client.xadd("hypnos.out", {"payload": b"c"}, id=_aged_id())
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
    client.xadd("hypnos.out", {"payload": b"a"}, id=_aged_id())

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
    client.xadd("hypnos.out", {"payload": b"a"}, id=_aged_id())

    out = io.StringIO()
    ret = legacy_streams.main([], client=client, out=out)
    assert ret == 0
    assert client.exists("hypnos.out")
    assert "Run again with --delete" in out.getvalue()


def test_main_never_deletes_live_streams(fake_client, monkeypatch):
    client = fake_client
    client.xadd("hypnos.out", {"payload": b"a"}, id=_aged_id())
    client.xadd("sleep.out", {"payload": b"b"})

    def fake_orphaned(live):
        return ["hypnos.out", "sleep.out"]

    monkeypatch.setattr(legacy_aliases, "orphaned_stream_names", fake_orphaned)
    entries = legacy_streams.survey(client)
    deletable = legacy_streams.deletable(entries)
    assert [e.old for e in deletable] == ["hypnos.out"]





class _FakeClient:
    def __init__(self):
        self._streams = {}

    def xadd(self, key, fields, id="*"):
        if id == "*":
            id = f"{int(time.time() * 1000)}-0"
        self._streams.setdefault(key, {})[id] = fields
        return id

    def exists(self, key):
        return key in self._streams

    def type(self, key):
        return b"stream" if key in self._streams else b"none"

    def xlen(self, key):
        return len(self._streams.get(key, {}))

    def xrevrange(self, key, count=1):
        items = sorted(self._streams.get(key, {}).items(), reverse=True)
        return [[entry_id.encode("utf-8"), fields] for entry_id, fields in items[:count]]

    def memory_usage(self, key):
        return 1024

    def unlink(self, key):
        self._streams.pop(key, None)


def test_recent_old_stream_is_kept_and_aged_old_stream_is_deletable():
    now_ms = int(time.time() * 1000)
    old_now = legacy_aliases.old_stream_name("sleep.out")
    old_aged = legacy_aliases.old_stream_name("language.external")
    client = _FakeClient()
    client.xadd(old_now, {"x": "1"})
    client.xadd(old_aged, {"x": "2"}, id=f"{now_ms - 20 * 60 * 1000}-0")

    entries = survey(client, now_ms=now_ms)
    by_old = {entry.old: entry for entry in entries}
    now_entry = by_old[old_now]
    aged_entry = by_old[old_aged]

    assert not deletable([now_entry], now_ms=now_ms)
    assert deletable([aged_entry], now_ms=now_ms)
    assert "recently written (kept)" in _render_status(now_entry, now_ms)
    assert f"{aged_entry.length} entries" in _render_status(aged_entry, now_ms)


class _Recorder:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)


def test_main_warns_before_deleting_sleep_or_external_history(monkeypatch):
    now_ms = int(time.time() * 1000)
    old = legacy_aliases.old_stream_name("sleep.out")
    client = _FakeClient()
    client.xadd(old, {"x": "1"}, id=f"{now_ms - 20 * 60 * 1000}-0")

    monkeypatch.setattr(
        "kaine.bus.legacy_streams.legacy_aliases.scope_done", lambda _scope: True
    )

    out = _Recorder()
    answers = ["DELETE 1 OLD STREAMS"]

    def input_fn(prompt):
        out.write(prompt)
        return answers.pop(0)

    main(["--delete"], client=client, input_fn=input_fn, out=out)
    warning = (
        "Deleting these also removes, from the dashboard's conversation history, "
        "what the entity said before the rename, and the old sleep events the "
        "language module reads when it first looks for the last sleep index. "
        "Research logs on disk are not affected.\n"
    )
    confirm = "Type DELETE 1 OLD STREAMS to delete them"
    warn_idx = next(i for i, line in enumerate(out.lines) if line == warning)
    conf_idx = next(i for i, line in enumerate(out.lines) if confirm in line)
    assert warn_idx < conf_idx
    assert old not in client._streams


def test_main_keeps_a_recently_written_old_stream_without_asking(monkeypatch):
    old = legacy_aliases.old_stream_name("sleep.out")
    client = _FakeClient()
    client.xadd(old, {"x": "1"})
    monkeypatch.setattr(
        "kaine.bus.legacy_streams.legacy_aliases.scope_done", lambda _scope: True
    )

    out = _Recorder()

    def input_fn(prompt):
        raise AssertionError("no confirmation expected")

    assert main(["--delete"], client=client, input_fn=input_fn, out=out) == 0
    text = "".join(out.lines)
    assert "recently written (kept)" in text
    assert "Nothing to delete." in text
    assert old in client._streams
