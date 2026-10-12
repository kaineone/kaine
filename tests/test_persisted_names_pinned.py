# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Pins for names that must stay byte-identical until the persisted rename step."""

import inspect
from pathlib import Path

import kaine.lifecycle.divergence as _divergence_mod
import kaine.memory_kinds as _memory_kinds
import kaine.organ_window_state as _organ_window_state
from kaine import legacy_names
from kaine.modules.episodic_memory.memory import EpisodicMemoryCore, recover_interrupted_import
from kaine.modules.episodic_memory.module import EpisodicMemory
from kaine.modules.episodic_memory.storage import SqliteVecStorage
from kaine.modules.social_cognition.module import SocialCognition
from kaine.modules.world_model.module import WorldModel

PERSISTED_DONE = legacy_names.SCOPE_STATUS.get("persisted") == "done"


def _state_path(old_rel: str) -> str:
    """Return 'state/' plus the table entry for *old_rel*, using the old or new name."""
    for entry in legacy_names.STATE_PATHS + legacy_names.LIVED_ARTIFACTS:
        if entry["old"] == old_rel:
            return "state/" + (entry["new"] if PERSISTED_DONE else entry["old"])
    raise AssertionError(f"no table entry for {old_rel}")


def _collection(old: str) -> str:
    """Return the collection name for *old*, using the old or new name."""
    for entry in legacy_names.COLLECTIONS:
        if entry["old"] == old:
            return entry["new"] if PERSISTED_DONE else entry["old"]
    raise AssertionError(old)


def _state_dir(module_key: str) -> str:
    """Return the module directory for *module_key*, using the old or new key."""
    return legacy_names.MODULES[module_key]["new_key"] if PERSISTED_DONE else module_key


def _find_state_entry(predicate):
    """Return the first STATE_PATHS or LIVED_ARTIFACTS entry matching *predicate*."""
    for entry in legacy_names.STATE_PATHS + legacy_names.LIVED_ARTIFACTS:
        if predicate(entry):
            return entry
    raise AssertionError("no matching state entry")


def _find_collection_entry(predicate):
    """Return the first COLLECTIONS entry matching *predicate*."""
    for entry in legacy_names.COLLECTIONS:
        if predicate(entry):
            return entry
    raise AssertionError("no matching collection entry")


# Old table keys are selected by stable file/name patterns, not by literal module names.
_STORE_HEALTH_ENTRY = _find_state_entry(
    lambda e: e["old"].endswith("/store_health.json")
)
_DB_ENTRY = _find_state_entry(lambda e: e["new"].endswith(".db"))
_ORGAN_WINDOW_ENTRY = _find_state_entry(
    lambda e: e["old"].endswith("/organ_window.json")
)
_DIVERGENCE_ENTRY = _find_state_entry(
    lambda e: e["old"].endswith("/consolidation_divergence.json")
)
_CHECKPOINT_ENTRY = _find_state_entry(lambda e: e["old"].endswith(".ckpt"))
_PREFIX_ENTRY = _find_collection_entry(lambda e: e["old"].endswith("_"))
_SOCIAL_ENTRY = _find_collection_entry(lambda e: not e["old"].endswith("_"))


def test_episodic_memory_store_health_path_pinned():
    """The store health constant must follow the legacy table."""
    expected = _state_path(_STORE_HEALTH_ENTRY["old"])
    assert _memory_kinds.EPISODIC_MEMORY_STORE_HEALTH_PATH == expected


def test_sqlite_vec_db_path_default_pinned():
    """The sqlite-vec default path must follow the legacy table."""
    expected = _state_path(_DB_ENTRY["old"])
    default = inspect.signature(SqliteVecStorage.__init__).parameters["db_path"].default
    assert default == expected


def test_episodic_memory_collection_prefix_pinned():
    """All episodic-memory collection prefixes must follow the legacy table."""
    expected_prefix = _collection(_PREFIX_ENTRY["old"])
    defaults = [
        inspect.signature(EpisodicMemoryCore.__init__).parameters["collection_prefix"].default,
        inspect.signature(EpisodicMemory.__init__).parameters["collection_prefix"].default,
        inspect.signature(recover_interrupted_import).parameters["collection_prefix"].default,
    ]
    for value in defaults:
        assert value == expected_prefix
    for kind in ("episodic", "semantic", "procedural"):
        assert f"{defaults[0]}{kind}" == f"{expected_prefix}{kind}"


def test_social_cognition_collection_pinned():
    """The social-cognition collection name must follow the legacy table."""
    expected = _collection(_SOCIAL_ENTRY["old"])
    default = inspect.signature(SocialCognition.__init__).parameters["collection"].default
    assert default == expected


def test_organ_window_state_path_pinned():
    """The organ-window state path must follow the legacy table."""
    expected = Path(_state_path(_ORGAN_WINDOW_ENTRY["old"]))
    assert _organ_window_state.ORGAN_WINDOW_STATE == expected


def test_world_model_checkpoint_path_pinned():
    """The world-model checkpoint default path must follow the legacy table."""
    expected = _state_path(_CHECKPOINT_ENTRY["old"])
    default = inspect.signature(WorldModel.__init__).parameters["checkpoint_path"].default
    assert default == expected


def test_adapter_dir_uses_organ_window_state_dir():
    """The divergence adapter directory must use the organ-window state directory."""
    organ_dir_key = _ORGAN_WINDOW_ENTRY["old"].split("/")[0]
    result = _divergence_mod.adapter_dir_for(None, Path("/r"))
    assert result == Path("/r") / _state_dir(organ_dir_key) / "adapters"


def test_divergence_source_uses_divergence_state_dir():
    """The divergence source must build its path from the legacy table."""
    divergence_dir_key = _DIVERGENCE_ENTRY["old"].split("/")[0]
    source = Path(_divergence_mod.__file__).read_text(encoding="utf-8")
    expected = f'state_root / "{_state_dir(divergence_dir_key)}" / "consolidation_divergence.json"'
    assert expected in source
