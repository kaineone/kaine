# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Decommission deletes the entity's bus streams by their real names."""

import pytest

from kaine import legacy_names
from kaine.bus.streams import KNOWN_STREAMS
from kaine.lifecycle import decommission


def test_stream_list_covers_registry_and_both_names():
    names = decommission._entity_redis_streams(None)

    for name in KNOWN_STREAMS:
        assert name in names, f"KNOWN_STREAMS missing {name!r}"
    assert "cycle.control" in names
    assert all("*" not in name for name in names)

    old = "thymos"
    entry = legacy_names.MODULES[old]
    new = entry["new_key"]
    assert f"{old}.out" in names, f"missing legacy stream {old}.out"
    assert f"{new}.out" in names, f"missing modern stream {new}.out"

    old = "volition"
    entry = legacy_names.MODULES[old]
    new = entry["new_key"]
    assert f"{old}_feedback.out" in names, f"missing legacy stream {old}_feedback.out"
    assert f"{new}_feedback.out" in names, f"missing modern stream {new}_feedback.out"


def test_decommission_clears_streams_with_fakeredis(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")

    server = fakeredis.FakeServer()

    def _fake_redis(**kwargs):
        return fakeredis.FakeRedis(server=server)

    monkeypatch.setattr("redis.Redis", _fake_redis)

    client = fakeredis.FakeRedis(server=server)
    seeded = [
        "thymos.out",
        "affect.out",
        "workspace.broadcast",
        "cycle.control",
        "lingua.external",
    ]
    for name in seeded:
        client.xadd(name, {"data": "1"})

    client.set("operator:note", "keep")

    cleared, errors = decommission._clear_redis_streams(
        {"host": "x", "port": 1, "db": 0},
        decommission._entity_redis_streams(None),
    )

    assert errors == []
    for name in seeded:
        assert name in cleared, f"{name!r} not reported as cleared"
        assert client.exists(name) == 0, f"{name!r} still exists"

    assert client.get("operator:note") == b"keep"
