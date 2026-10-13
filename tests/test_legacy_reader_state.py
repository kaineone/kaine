# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stored state written under old module names restores under the new ones once the keys step is done; each test fails if its call site loses the mapping."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.snapshot import artifacts_dir
from kaine.modules.registry import ModuleRegistry
from kaine.modules.self_model import SelfModel, SelfModelDocument
from kaine.modules.sequence.featurizer import SnapshotFeaturizer
from kaine.modules.sequence.module import Sequence
from kaine.research.ignition_study.analysis import _analyse_viewing
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


def _keys_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")


class FakeNetwork:
    """Returns a constant hidden state of the requested size."""

    def __init__(self, units: int = 8, value: float = 0.5) -> None:
        self.units = units
        self.value = value
        self.calls: list[list[float]] = []

    def tick(self, feature_vec: list[float]) -> list[float]:
        self.calls.append(list(feature_vec))
        return [self.value] * self.units


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.mark.asyncio
async def test_sequence_restores_cursor_saved_under_old_stream(monkeypatch, bus: AsyncBus):
    """A cursor stored under the old stream name moves to the new stream name."""
    _keys_done(monkeypatch)
    sequence = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=FakeNetwork(),
    )
    sequence.deserialize({"user_input_cursors": {"lingua.external": "5-0"}})
    new_key = legacy_aliases.map_stream("lingua.external")
    assert sequence._user_input_cursors[new_key] == "5-0"
    assert "lingua.external" not in sequence._user_input_cursors


@pytest.mark.asyncio
async def test_self_model_drift_episode_merges_old_source_names(
    monkeypatch, bus: AsyncBus, tmp_path: Path
):
    """A stored drift episode keyed under the old source name is extended under the new one."""
    _keys_done(monkeypatch)
    p = tmp_path / "model.json"
    p.write_text(
        SelfModelDocument(values=["honesty"]).to_json(), encoding="utf-8"
    )
    self_model = SelfModel(bus, persistence_path=p, save_interval_s=60)
    await self_model.initialize()
    self_model._episode_open = True
    self_model._model.identity_history.append(
        {
            "kind": "drift_episode",
            "onset": 0.0,
            "end": 0.0,
            "peak_score": 0.5,
            "count": 1,
            "sources": {"soma": 2},
        }
    )
    result = SimpleNamespace(score=0.3, top_drifted_sources=["interoception"])
    await self_model._record_drift(result)
    sources = self_model._model.identity_history[-1]["sources"]
    assert sources == {"interoception": 3}
    assert "soma" not in sources


@pytest.mark.asyncio
async def test_merge_maps_old_artifact_directory_names(
    monkeypatch, bus: AsyncBus, tmp_path: Path
):
    """Old artifact directory names are remapped when merging fork snapshots."""
    _keys_done(monkeypatch)
    fm = ForkManager(tmp_path / "forks")
    snap_a = fm.snapshot(ModuleRegistry())
    snap_b = fm.snapshot(ModuleRegistry())

    a_dir = artifacts_dir(fm.root, snap_a.id, "phantasia")
    b_dir = artifacts_dir(fm.root, snap_b.id, "phantasia")
    a_dir.mkdir(parents=True, exist_ok=True)
    b_dir.mkdir(parents=True, exist_ok=True)
    (a_dir / "wm.bin").write_bytes(b"a")
    (b_dir / "wm.bin").write_bytes(b"b")

    # Snapshot b is chosen explicitly: without the world-model rule the merge would
    # fall back to snapshot a, so this fails if the world-model name is not mapped.
    merged = fm.merge(snap_a.id, snap_b.id, world_model_from="b")
    new_name = legacy_aliases.map_module_key("phantasia")
    assert merged.metadata["artifact_sources"] == {new_name: "b"}
    merged_dir = artifacts_dir(fm.root, merged.id, new_name)
    assert (merged_dir / "wm.bin").read_bytes() == b"b"


def test_viewing_analysis_maps_old_member_sources(monkeypatch, tmp_path: Path):
    """Coalition member sources written under old keys are counted under the new keys."""
    _keys_done(monkeypatch)

    def _record(seq: int, members: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "tick_index": seq,
            "entry_id": f"e{seq}",
            "wall_ts": "2026-01-01T00:00:00Z",
            "mono_ts": float(seq),
            "programme": {
                "item_idx": 0,
                "order": 0,
                "title": "Film",
                "offset_s": 0.0,
                "paused": False,
            },
            "audio": None,
            "inhibited": False,
            "salience_scores": {},
            "members": members,
            "run_id": "r-old",
            "seq": seq,
        }

    def _member(source: str, salience: float) -> dict[str, Any]:
        return {
            "entry_id": f"{source}-1",
            "source": source,
            "type": f"{source}.report",
            "salience": salience,
            "timestamp": "2026-01-01T00:00:00Z",
        }

    log_dir = tmp_path / "ignition"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "ignition-2026-01-01.jsonl"
    records = [_record(1, [_member("topos", 0.6)])]
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    step = {
        "line": "branch",
        "step": 1,
        "run_id": "r-old",
        "ignition_log_dir": str(log_dir),
        "modules": ["topos"],
    }
    result = _analyse_viewing(step, [legacy_aliases.map_module_key("topos")])
    new_name = legacy_aliases.map_module_key("topos")
    assert result.measures["module_shares"][new_name] == pytest.approx(1.0)
    assert result.measures["member_salience"][new_name]["mean"] == pytest.approx(0.6)
