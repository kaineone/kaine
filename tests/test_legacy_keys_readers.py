# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The keys-scope readers prepared before the keys rename: inert while the scope is pending, correct once it is done."""

import hashlib
import json
import pathlib

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.cycle.control_state import CycleControl
from kaine.lifecycle import decommission
from kaine.lifecycle.snapshot import artifacts_dir, find_artifacts_dir
from kaine.plugins import PluginError, load_plugins
from kaine.research import submission
from kaine.research.ignition_study.plan import load_plan


class _DupSeamPlugin:
    def seams(self, config):
        return frozenset({"oldsoma.forward_model", "soma.forward_model"})

    def injections(self, module, config):
        return {}


class _FakeEntryPoint:
    name = "p"
    dist = None

    def __init__(self, plugin):
        self._plugin = plugin

    def load(self):
        return lambda: self._plugin


def _keys_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")


def _keys_pending(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "pending")


def test_normalizer_is_inert_while_pending(monkeypatch):
    """The normalizer returns the layer unchanged while the keys scope is pending."""
    _keys_pending(monkeypatch)
    layer = {"thymos": {"soma_stream": "soma.out"}}
    assert legacy_aliases.normalize_config_layer(layer, "op.toml") is layer


def test_compound_config_key_renamed(monkeypatch):
    """An old table and key move to their new names and the stream value maps too."""
    _keys_done(monkeypatch)
    result = legacy_aliases.normalize_config_layer(
        {"thymos": {"soma_stream": "soma.out"}}, "op.toml"
    )
    assert result == {"affect": {"interoception_stream": "interoception.out"}}


def test_module_key_inside_other_table(monkeypatch):
    """A module key nested in another table is renamed when the scope is done."""
    _keys_done(monkeypatch)
    result = legacy_aliases.normalize_config_layer(
        {"evaluation": {"observers": {"empatheia": True}}}, "op.toml"
    )
    assert result == {"evaluation": {"observers": {"social_cognition": True}}}


def test_stream_name_as_key(monkeypatch):
    """A stream name used as a config key is mapped to its new name."""
    _keys_done(monkeypatch)
    result = legacy_aliases.normalize_config_layer(
        {"bus": {"per_stream_maxlen": {"topos.out": 12000}}}, "op.toml"
    )
    assert result == {"bus": {"per_stream_maxlen": {"vision.out": 12000}}}


def test_stream_names_in_lists_and_tier_modules(monkeypatch):
    """Stream names in lists and module names in tier sets are mapped."""
    _keys_done(monkeypatch)
    layer = {
        "x": {"streams": ["soma.out", "other.out"]},
        "tier": {"unsupported_modules": ["topos", "audition"]},
    }
    result = legacy_aliases.normalize_config_layer(layer, "op.toml")
    expected = {
        "x": {"streams": ["interoception.out", "other.out"]},
        "tier": {"unsupported_modules": ["vision", "audition"]},
    }
    assert result == expected


def test_both_names_refused(monkeypatch):
    """Declaring both the old and new name of the same key raises a conflict."""
    _keys_done(monkeypatch)
    with pytest.raises(legacy_aliases.LegacyNameConflict):
        legacy_aliases.normalize_config_layer(
            {"thymos": {"soma_stream": "a", "interoception_stream": "b"}}, "op.toml"
        )


def test_study_plan_read_old_keys_without_rewrite(tmp_path, monkeypatch):
    """load_plan rewrites returned module names but leaves the source file untouched."""
    _keys_done(monkeypatch)
    path = tmp_path / "study.json"
    raw = json.dumps(
        {
            "study_id": "s",
            "base_modules": ["soma", "audition"],
            "order": ["mnemos", "phantasia"],
            "gestation_budget_seconds": 60,
        },
        indent=2,
    )
    path.write_text(raw)
    before_bytes = path.read_bytes()
    before_hash = hashlib.sha256(before_bytes).hexdigest()

    plan = load_plan(tmp_path)
    assert plan["base_modules"] == ["interoception", "audition"]
    assert plan["order"] == ["episodic_memory", "world_model"]
    assert plan["gestation_budget_seconds"] == 60
    assert path.read_bytes() == before_bytes
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash


def test_study_plan_pending_no_rewrite(tmp_path, monkeypatch):
    """With the keys scope pending, load_plan leaves module names unchanged."""
    _keys_pending(monkeypatch)
    path = tmp_path / "study.json"
    path.write_text(
        json.dumps(
            {
                "study_id": "s",
                "base_modules": ["soma", "audition"],
                "order": ["mnemos", "phantasia"],
                "gestation_budget_seconds": 60,
            },
            indent=2,
        )
    )
    plan = load_plan(tmp_path)
    assert plan["base_modules"] == ["soma", "audition"]
    assert plan["order"] == ["mnemos", "phantasia"]


def test_freeze_source_maps_only_when_done(monkeypatch):
    """CycleControl maps legacy source names only after the keys scope is done."""
    _keys_pending(monkeypatch)
    data = {"stack": [{"source": "spot", "reason": "r", "frozen_at": "t"}]}
    assert CycleControl.from_dict(data).stack[0]["source"] == "spot"
    _keys_done(monkeypatch)
    assert CycleControl.from_dict(data).stack[0]["source"] == "supervisor"

    legacy = {"frozen": True, "source": "spot"}
    mapped = CycleControl.from_dict(legacy)
    assert mapped.source == "supervisor"


def test_stream_keys_prefer_new(monkeypatch):
    """map_stream_keys prefers a new stream name when both old and new are present."""
    _keys_done(monkeypatch)
    merged = legacy_aliases.map_stream_keys(
        {"lingua.external": "5-0", "language.external": "7-0", "other.out": "1-0"}
    )
    assert merged == {"language.external": "7-0", "other.out": "1-0"}
    only_old = legacy_aliases.map_stream_keys({"lingua.external": "5-0"})
    assert only_old == {"language.external": "5-0"}


def test_decommission_deletes_every_form(monkeypatch):
    """decommission recognizes both old and new forms of state subtrees."""
    _keys_done(monkeypatch)
    subtrees = decommission._STATE_SUBTREES
    assert "eidolon" in subtrees
    assert "self_model" in subtrees
    assert "lingua" in subtrees
    assert "language" in subtrees
    assert "phantasia" in subtrees
    assert "world_model" in subtrees
    assert "perception" in subtrees
    assert "perceptual_locus" in subtrees
    assert pathlib.Path("hypnos") / "adapters" in subtrees
    assert pathlib.Path("sleep") / "adapters" in subtrees


def test_public_bundle_denies_every_form(monkeypatch):
    """The public submission deny list includes both old and new module names."""
    _keys_done(monkeypatch)
    for name in ("mnemos", "episodic_memory", "eidolon", "self_model"):
        assert name in submission.DENY_PATTERNS


def test_artifacts_found_under_old_name(tmp_path):
    """Snapshot artifact directories are discoverable by either old or new module names."""
    old = artifacts_dir(tmp_path, "s1", "phantasia")
    old.mkdir(parents=True)
    assert find_artifacts_dir(tmp_path, "s1", "world_model") == old

    new = artifacts_dir(tmp_path, "s1", "world_model")
    new.mkdir(parents=True)
    assert find_artifacts_dir(tmp_path, "s1", "world_model") == new


def test_plugin_cannot_declare_one_seam_twice(monkeypatch):
    """A plugin declaring the same resolved seam under two names is rejected."""
    _keys_done(monkeypatch)
    monkeypatch.setattr(
        legacy_names,
        "PLUGIN_SEAMS",
        ({"old": "oldsoma.forward_model", "new": "soma.forward_model", "scope": "keys"},),
    )
    plugin = _DupSeamPlugin()
    ep = _FakeEntryPoint(plugin)
    with pytest.raises(PluginError, match="declares seam .* under two names"):
        load_plugins(
            {"plugins": {"enabled": ["p"]}},
            known_modules=["soma"],
            entry_points=lambda group="kaine.plugins": [ep],
        )


def test_cursor_from_old_stream_neither_replays_nor_skips(monkeypatch):
    """Redis stream ids are time-ordered.

    A cursor recorded against the old stream and used on the new stream
    after the rename—which requires a restart—reads exactly the entries
    written after it. The new stream starts after the last old entry.
    """
    _keys_done(monkeypatch)
    fakeredis = pytest.importorskip("fakeredis")
    r = fakeredis.FakeRedis()
    old_ids = [
        r.xadd("hypnos.out", {"k": str(i)}, id=f"1000-{i}")
        for i in range(3)
    ]
    cursor = old_ids[-1]
    new_ids = [r.xadd("sleep.out", {"k": str(i)}) for i in range(3, 6)]

    messages = r.xread({"sleep.out": cursor})
    assert len(messages) == 1
    stream_key, entries = messages[0]
    assert stream_key in {"sleep.out", b"sleep.out"}
    assert len(entries) == 3
    returned_ids = [entry_id for entry_id, _ in entries]
    assert returned_ids == new_ids
    assert not any(old_id in returned_ids for old_id in old_ids)
