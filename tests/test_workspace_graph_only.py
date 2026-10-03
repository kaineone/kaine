# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that research/trajectory surfaces record the workspace graph only.

Checks the privacy filter's vector removal and the trajectory recorder's
graph-only member shape.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.ignition_log import ignition_log_sink
from kaine.evaluation.trajectory import TrajectoryRecorder
from kaine.privacy_filter import PrivacyFilter


class FakeSink:
    def __init__(self):
        self.rows = []

    async def write(self, entry):
        self.rows.append(entry)


class FakeWorkspaceBus:
    """Yields canned (entry_id, snapshot_dict) pairs via subscribe_workspace,
    then ends — mirroring the real bus's decoded output without a server."""

    def __init__(self, broadcasts):
        self._broadcasts = broadcasts

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        for entry_id, payload in self._broadcasts:
            yield entry_id, payload


async def _drain(observer, sink, n_expected, timeout=2.0):
    await observer.start()
    waited = 0.0
    while len(sink.rows) < n_expected and waited < timeout:
        await asyncio.sleep(0.01)
        waited += 0.01
    await observer.stop()


def _event(source, type_, payload):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )


def test_filter_topos_vectors_removed():
    payload = {
        "latent": [0.1] * 768,
        "peripheral": [0.2] * 768,
        "foveal": [0.3] * 768,
        "change_score": 0.4,
        "alert": False,
        "fovea": {"x": 0.5, "y": 0.5, "size": 0.2},
        "predicted_fovea": {"x": 0.4, "y": 0.6, "size": 0.2},
        "encoder_model_id": "m",
    }
    out = PrivacyFilter().filter_for_diagnostics(_event("topos", "topos.report", payload))
    for key in ("latent", "peripheral", "foveal"):
        assert key not in out.payload
    assert out.payload["change_score"] == 0.4
    assert out.payload["alert"] is False
    assert out.payload["fovea"] == {"x": 0.5, "y": 0.5, "size": 0.2}
    assert out.payload["predicted_fovea"] == {"x": 0.4, "y": 0.6, "size": 0.2}
    assert out.payload["encoder_model_id"] == "m"


def test_filter_named_vectors_removed_regardless_of_length():
    payload = {
        "latent": [1.0, 2.0, 3.0, 4.0],
        "temporal_context": [0.0] * 32,
        "feature_vector": [0.0] * 24,
    }
    out = PrivacyFilter().filter_for_diagnostics(
        _event("chronos", "chronos.report", payload)
    )
    assert out.payload == {}


def test_filter_unnamed_embedding_lists_and_tuples_removed():
    list_payload = {"embedding_x": [0.5] * 64}
    out_list = PrivacyFilter().filter_for_diagnostics(
        _event("topos", "topos.report", list_payload)
    )
    assert "embedding_x" not in out_list.payload

    tuple_payload = {"embedding_t": tuple([0.5] * 64)}
    out_tuple = PrivacyFilter().filter_for_diagnostics(
        _event("topos", "topos.report", tuple_payload)
    )
    assert "embedding_t" not in out_tuple.payload


def test_filter_drops_lists_of_vectors():
    payload = {
        "latents": [[0.1] * 768, [0.2] * 768],
        "grid": [[1, 2], [3, 4]],
    }
    out = PrivacyFilter().filter_for_diagnostics(
        _event("topos", "topos.report", payload)
    )
    assert out.payload == {"latents": [], "grid": [[1, 2], [3, 4]]}


def test_filter_backstop_boundary():
    removed = {"a": [0.1] * 16}
    out_removed = PrivacyFilter().filter_for_diagnostics(
        _event("topos", "topos.report", removed)
    )
    assert "a" not in out_removed.payload

    kept = {"b": [0.1] * 15}
    out_kept = PrivacyFilter().filter_for_diagnostics(
        _event("topos", "topos.report", kept)
    )
    assert out_kept.payload == kept


def test_filter_exempt_and_non_numeric_lists_survive():
    payload = {
        "scores": [0.1, 0.2, 0.3, 0.4, 0.5],
        "saliences": [0.5] * 40,
        "step_magnitudes": [0.1] * 20,
        "flags": [True] * 40,
        "names": ["a"] * 40,
        "position": [1.0, 2.0, 3.0],
        "short": [0.1] * 15,
    }
    out = PrivacyFilter().filter_for_diagnostics(
        _event("hypnos", "hypnos.report", payload)
    )
    assert out.payload == payload


def test_filter_removes_vectors_at_arbitrary_depth():
    payload = {
        "selected": [
            {
                "source": "topos",
                "payload": {"latent": [0.1] * 768, "change_score": 0.2},
            }
        ],
        "salience_scores": {"e1": 0.7},
    }
    out = PrivacyFilter().filter_for_diagnostics(
        _event("syneidesis", "workspace.broadcast", payload)
    )
    assert "latent" not in json.dumps(out.payload)
    assert out.payload["selected"][0]["payload"]["change_score"] == 0.2
    assert out.payload["salience_scores"] == {"e1": 0.7}


def test_filter_dev_override_keeps_content_but_still_strips_vectors():
    payload = {
        "text": "hello",
        "latent": [0.1] * 768,
        "temporal_context": [0.1, 0.2, 0.3],
    }
    event = _event("lingua", "lingua.internal_speech", payload)

    dev = PrivacyFilter(dev_content_override=True)
    dev_out = dev.filter_for_diagnostics(event)
    assert dev_out.payload.get("text") == "hello"
    assert "latent" not in dev_out.payload
    assert "temporal_context" not in dev_out.payload

    normal = PrivacyFilter()
    normal_out = normal.filter_for_diagnostics(event)
    assert "text" not in normal_out.payload
    assert "latent" not in normal_out.payload
    assert "temporal_context" not in normal_out.payload


@pytest.mark.asyncio
async def test_trajectory_member_is_graph_only_no_payload():
    snapshot = {
        "tick_index": 1,
        "is_experiential": True,
        "inhibited": False,
        "salience_scores": {"topos": 0.9},
        "selected": [
            {
                "entry_id": "1-0",
                "source": "topos",
                "type": "topos.report",
                "salience": 0.9,
                "timestamp": "2026-10-03T00:00:00+00:00",
                "causal_parent": "0-0",
                "payload": {"latent": [0.1] * 768, "text": "hidden"},
            }
        ],
        "metadata": {},
    }
    sink = FakeSink()
    rec = TrajectoryRecorder(FakeWorkspaceBus([("1-0", snapshot)]), sink)
    await _drain(rec, sink, n_expected=1)
    row = sink.rows[0]
    assert "thymos_state" not in row
    assert "payload" not in row
    selected = row["selected"]
    assert len(selected) == 1
    assert selected[0] == {
        "entry_id": "1-0",
        "source": "topos",
        "type": "topos.report",
        "salience": 0.9,
        "timestamp": "2026-10-03T00:00:00+00:00",
        "causal_parent": "0-0",
    }
    row_json = json.dumps(row)
    assert "latent" not in row_json
    assert "hidden" not in row_json


@pytest.mark.asyncio
async def test_ignition_log_sink_never_purges(tmp_path):
    old = tmp_path / "ignition-2020-01-01.jsonl"
    old.write_text('{"x": 1}\n')
    age_s = 400 * 24 * 3600
    mtime = time.time() - age_s
    os.utime(old, (mtime, mtime))
    sink = ignition_log_sink(tmp_path)
    await sink.start()
    await sink.stop()
    assert old.exists()
