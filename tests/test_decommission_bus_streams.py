# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Decommission deletes the entity's bus streams by their real names."""

import pytest

from kaine import legacy_names
from kaine.bus.streams import KNOWN_STREAMS
from kaine.evaluation import stream_registry as eval_stream_registry
from kaine.lifecycle import decommission


def test_stream_list_covers_evaluation_produced_streams():
    """Every stream the evaluation registry lists as produced is deleted, although decommission cannot import that registry."""
    names = set(decommission._entity_redis_streams(None))

    for stream in eval_stream_registry.raw_archive_module_streams():
        assert stream in names, f"evaluation stream {stream!r} missing from decommission list"


def test_stream_list_covers_registry_and_both_names():
    """All bus streams are listed, including both legacy and modern names for renamed modules."""
    names = decommission._entity_redis_streams(None)

    for name in KNOWN_STREAMS:
        assert name in names, f"KNOWN_STREAMS missing {name!r}"
    assert "cycle.control" in names
    assert all("*" not in name for name in names)

    old = "thymos"
    entry = legacy_names.MODULES[old]
    new = entry["new_key"]
    assert old != new
    assert f"{old}.out" in names, f"missing legacy stream {old}.out"
    assert f"{new}.out" in names, f"missing modern stream {new}.out"

    old = "volition"
    entry = legacy_names.MODULES[old]
    new = entry["new_key"]
    assert old != new
    assert f"{old}_feedback.out" in names, f"missing legacy stream {old}_feedback.out"
    assert f"{new}_feedback.out" in names, f"missing modern stream {new}_feedback.out"


def test_decommission_clears_streams_with_fakeredis():
    """Only exact seeded streams are removed and reported; non-stream keys and neighbours stay."""
    fakeredis = pytest.importorskip("fakeredis")

    client = fakeredis.FakeRedis()
    seeded = [
        "thymos.out",
        "affect.out",
        "workspace.broadcast",
        "cycle.control",
        "lingua.external",
    ]
    for name in seeded:
        client.xadd(name, {"data": "1"})

    client.xadd("affect.out.backup", {"data": "2"})
    client.set("lingua.internal", "keep")
    client.set("operator:note", "keep")

    result = decommission.clear_entity_streams(
        client,
        decommission._entity_redis_streams(None),
        dry_run=False,
    )

    assert result.failed is None
    assert sorted(result.cleared) == sorted(seeded)

    for name in seeded:
        assert client.exists(name) == 0, f"{name!r} still exists"

    assert client.exists("affect.out.backup") == 1
    assert client.get("lingua.internal") == b"keep"
    assert client.get("operator:note") == b"keep"
    assert "lingua.internal (string)" in result.skipped_non_streams


def test_dry_run_lists_only_existing_streams():
    """Dry run reports existing streams without deleting anything."""
    fakeredis = pytest.importorskip("fakeredis")

    client = fakeredis.FakeRedis()
    existing = ["thymos.out", "affect.out"]
    for name in existing:
        client.xadd(name, {"data": "1"})

    client.set("operator:note", "keep")

    result = decommission.clear_entity_streams(
        client,
        decommission._entity_redis_streams(None),
        dry_run=True,
    )

    assert result.failed is None
    assert sorted(result.would_clear) == sorted(existing)
    assert result.cleared == []

    for name in existing:
        assert client.exists(name) == 1, f"{name!r} was deleted during dry run"

    assert client.exists("operator:note") == 1


def test_unreachable_bus_is_a_failure():
    """A bus that cannot be reached is reported as a failure with no streams cleared."""
    class UnreachableClient:
        def ping(self):
            raise ConnectionError("connection refused")

        def close(self):
            pass

    result = decommission.clear_entity_streams(
        UnreachableClient(),
        decommission._entity_redis_streams(None),
        dry_run=False,
    )

    assert result.failed is not None
    assert result.failed.startswith("cannot reach or authenticate")
    assert result.cleared == []
