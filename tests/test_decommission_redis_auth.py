# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Decommission against a real redis-server that requires a password."""

import os
import shutil
import socket
import subprocess
import time

import pytest
import redis

from kaine import legacy_aliases, legacy_names
from kaine.bus.config import BusConfig
from kaine.lifecycle import decommission

# Old names come from the rename table, so the keys codemod leaves them alone.
OLD_AFFECT = f"{next(k for k, e in legacy_names.MODULES.items() if e['new_key'] == 'affect')}.out"
OLD_LANGUAGE_INTERNAL = legacy_aliases.old_stream_name("language.internal") or "language.internal"


@pytest.fixture(scope="module")
def requirepass_redis(tmp_path_factory):
    """Start a real Redis server with requirepass and appendonly enabled."""
    if shutil.which("redis-server") is None:
        if os.environ.get("KAINE_REQUIRE_REDIS_SERVER") == "1":
            pytest.fail("redis-server not found on PATH; KAINE_REQUIRE_REDIS_SERVER=1 requires it")
        pytest.skip("redis-server not found on PATH")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    tmp_dir = tmp_path_factory.mktemp("redis-auth")
    proc = subprocess.Popen(
        [
            "redis-server",
            "--port",
            str(port),
            "--bind",
            "127.0.0.1",
            "--requirepass",
            "s3cret",
            "--appendonly",
            "yes",
            "--save",
            "",
            "--dir",
            str(tmp_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    client = redis.Redis(port=port, password="s3cret")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if client.ping():
                break
        except redis.exceptions.ConnectionError:
            time.sleep(0.1)
    else:
        proc.terminate()
        proc.wait()
        pytest.fail("redis-server did not start within 5 seconds")

    yield port

    proc.terminate()
    proc.wait()


def test_authenticated_client_clears_streams_and_rewrites_aof(requirepass_redis):
    """An authenticated client clears only stream keys and triggers an AOF rewrite."""
    cfg = BusConfig(host="127.0.0.1", port=requirepass_redis, password="s3cret")
    client = redis.Redis.from_url(cfg.url)
    client.flushdb()
    client.xadd(OLD_AFFECT, {"data": "1"})
    client.xadd("affect.out", {"data": "2"})
    client.set(OLD_LANGUAGE_INTERNAL, "keep")
    client.set("operator:note", "keep")

    result = decommission.clear_entity_streams(
        client,
        decommission._entity_redis_streams(None),
        dry_run=False,
    )

    assert result.failed is None
    assert sorted(result.cleared) == sorted(["affect.out", OLD_AFFECT])
    assert client.exists(OLD_AFFECT) == 0
    assert client.exists("affect.out") == 0
    assert client.get(OLD_LANGUAGE_INTERNAL) == b"keep"
    assert client.get("operator:note") == b"keep"
    assert result.aof_rewrite in {"started", "already in progress"}


def test_wrong_password_fails_and_deletes_nothing(requirepass_redis):
    """A wrong password causes the operation to fail and leaves streams intact."""
    good = redis.Redis.from_url(
        BusConfig(host="127.0.0.1", port=requirepass_redis, password="s3cret").url
    )
    good.xadd(OLD_AFFECT, {"data": "1"})

    bad = redis.Redis.from_url(
        BusConfig(host="127.0.0.1", port=requirepass_redis, password="wrong").url
    )
    result = decommission.clear_entity_streams(
        bad,
        decommission._entity_redis_streams(None),
        dry_run=False,
    )

    assert result.failed is not None
    assert result.failed.startswith("cannot reach or authenticate")
    assert result.cleared == []
    assert good.exists(OLD_AFFECT) == 1


def test_no_password_fails_and_deletes_nothing(requirepass_redis):
    """A missing password causes the operation to fail and leaves streams intact."""
    good = redis.Redis.from_url(
        BusConfig(host="127.0.0.1", port=requirepass_redis, password="s3cret").url
    )
    good.xadd(OLD_AFFECT, {"data": "1"})

    bad = redis.Redis.from_url(
        BusConfig(host="127.0.0.1", port=requirepass_redis).url
    )
    result = decommission.clear_entity_streams(
        bad,
        decommission._entity_redis_streams(None),
        dry_run=False,
    )

    assert result.failed is not None
    assert result.failed.startswith("cannot reach or authenticate")
    assert result.cleared == []
    assert good.exists(OLD_AFFECT) == 1
