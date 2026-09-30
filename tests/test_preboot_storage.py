# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the pre-boot storage row."""
from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from kaine.preboot import (
    FAIL,
    GROUP_RESOURCES,
    PASS,
    SKIP,
    CheckResult,
    check_storage,
    durable_paths,
)
from kaine.storage import DATA_ROOT_ENV

GIB = 1024 ** 3
Usage = namedtuple("Usage", ["total", "used", "free"])


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv(DATA_ROOT_ENV, raising=False)


def test_check_storage_skips_when_no_root():
    results = check_storage({})
    assert results == [
        CheckResult(
            GROUP_RESOURCES,
            "Storage",
            SKIP,
            "no [storage].data_root; growing data is written under the working directory",
        )
    ]


def test_check_storage_passes_with_enough_free(tmp_path):
    def fake_usage(path):
        return Usage(total=100 * GIB, used=50 * GIB, free=50 * GIB)

    config = {"storage": {"data_root": str(tmp_path)}}
    results = check_storage(config, disk_usage=fake_usage)
    assert len(results) == 1
    r = results[0]
    assert r.status == PASS
    assert "50.00 GiB free" in r.detail or "50 GiB free" in r.detail
    assert "minimum 20 GiB" in r.detail


def test_check_storage_fails_with_too_little_free(tmp_path):
    def fake_usage(path):
        return Usage(total=100 * GIB, used=95 * GIB, free=5 * GIB)

    config = {"storage": {"data_root": str(tmp_path)}}
    results = check_storage(config, disk_usage=fake_usage)
    assert len(results) == 1
    r = results[0]
    assert r.status == FAIL
    assert "minimum 20 GiB" in r.detail
    assert "free space or choose another data root" in r.detail


def test_check_storage_fails_on_disk_usage_error(tmp_path):
    def fake_usage(path):
        raise OSError("no such device")

    config = {"storage": {"data_root": str(tmp_path)}}
    results = check_storage(config, disk_usage=fake_usage)
    assert len(results) == 1
    r = results[0]
    assert r.status == FAIL
    assert str(tmp_path) in r.detail
    assert "could not read disk usage" in r.detail
    assert "OSError" in r.detail


def test_durable_paths_lists_data_root_first(tmp_path):
    config = {"storage": {"data_root": str(tmp_path)}}
    paths = durable_paths(config)
    assert paths[0] == ("[storage].data_root", Path(str(tmp_path)).resolve())
