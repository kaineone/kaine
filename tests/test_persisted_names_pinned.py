# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Pins for names that must stay byte-identical until the persisted rename step."""

import dataclasses
import inspect
from pathlib import Path

import kaine.lifecycle.divergence as _divergence_mod
import kaine.lifecycle.maturation_ack as _maturation_ack
import kaine.lifecycle.maturation_gate as _maturation_gate
import kaine.lifecycle.preservation as _preservation
import kaine.memory_kinds as _memory_kinds
import kaine.modules.self_model.module as _self_model_module
import kaine.organ_window_state as _organ_window_state
import kaine.perception_state as _perception_state
from kaine import legacy_names
from kaine.lifecycle import stage as _stage
from kaine.lifecycle.individuation_store import IndividuationPaths
from kaine.modules.effectors.module import Effectors
from kaine.modules.episodic_memory.memory import EpisodicMemoryCore, recover_interrupted_import
from kaine.modules.episodic_memory.module import EpisodicMemory
from kaine.modules.episodic_memory.storage import SqliteVecStorage
from kaine.modules.language.module import Language
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


def test_language_intent_log_path_pinned():
    """The Language intent log path default must follow the legacy table."""
    assert (
        inspect.signature(Language.__init__).parameters["intent_log_path"].default
        == _state_path("lingua/intent_expression.jsonl")
    )


def test_effectors_audit_log_path_pinned():
    """The Effectors audit log path default must follow the legacy table."""
    assert (
        inspect.signature(Effectors.__init__).parameters["audit_log_path"].default
        == _state_path("praxis/audit.log")
    )


def test_effectors_notification_log_path_pinned():
    """The Effectors notification fallback log path default must follow the legacy table."""
    assert (
        inspect.signature(Effectors.__init__).parameters["notification_fallback_log"].default
        == _state_path("praxis/notifications.log")
    )


def test_self_model_persistence_path_pinned():
    """The self-model default persistence path must follow the legacy table."""
    assert _self_model_module.DEFAULT_PERSISTENCE_PATH == Path(
        _state_path("eidolon/self_model.json")
    )


def test_perception_state_paths_pinned():
    """The perception runtime/desired paths must follow the legacy table."""
    assert (
        _perception_state.RUNTIME_PATH == Path(_state_path("perception/runtime.json"))
        and _perception_state.DESIRED_PATH == Path(_state_path("perception/desired.json"))
    )


def test_maturation_request_and_ack_paths_pinned():
    """The maturation request/ack paths must follow the legacy table."""
    assert (
        _maturation_ack.MATURATION_REQUEST_PATH == Path(_state_path("lifecycle/birth_request.json"))
        and _maturation_ack.MATURATION_ACK_PATH == Path(_state_path("lifecycle/birth_ack.json"))
    )


def test_development_state_files_pinned():
    """The bundled/development state file names must follow the legacy table."""
    assert (
        _preservation.BUNDLED_DEVELOPMENT_FILES
        == tuple(Path(_state_path(rel)).name for rel in ("lifecycle/gestation_progress.json", "lifecycle/gestation_readout.json"))
        and _preservation.DEVELOPMENT_STATE_FILES
        == _preservation.BUNDLED_DEVELOPMENT_FILES + (Path(_state_path("lifecycle/gestation_viability.json")).name,)
    )


def test_maturation_adapter_file_name_pinned(tmp_path):
    """The maturation adapter file name must follow the legacy table."""
    assert (
        IndividuationPaths(root=tmp_path).maturation_adapter.name
        == Path(_state_path("individuation/birth_adapter.gguf")).name
    )


def test_stage_fields_and_value_pinned():
    """Stage state field names and the development constant must follow the legacy table."""
    for entry in legacy_names.STAGE_FIELDS:
        expected = entry["new"] if PERSISTED_DONE else entry["old"]
        assert expected in {f.name for f in dataclasses.fields(_stage.StageState)}
    for entry in legacy_names.STAGE_VALUES:
        if entry["old"] == "gestation":
            assert _stage.DEVELOPMENT == (entry["new"] if PERSISTED_DONE else entry["old"])


def test_maturation_pending_sentinel_pinned(tmp_path):
    """The maturation pending sentinel keeps its filename across renames."""
    assert IndividuationPaths(root=tmp_path).maturation_pending.name == Path(
        _state_path("individuation/birth_pending")
    ).name


def test_gate_action_values_pinned():
    """Maturation gate action values keep their old text in this step."""
    assert _maturation_gate.ACTION_DEVELOPING == "gestating"
    assert _maturation_gate.ACTION_MATURATION == "birth"
