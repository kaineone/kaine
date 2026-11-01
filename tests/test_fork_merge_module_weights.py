# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Weight-bearing module state merges only by an explicit choice.

The parents' states come from the real module classes (vision, audition,
interoception, sequence), so these tests exercise the shapes the modules
actually serialize, not hand-written stand-ins.
"""

from __future__ import annotations

import base64
import copy
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from kaine.bus.client import AsyncBus
from kaine.lifecycle.manager import (
    ForkManager,
    ModuleMergeStrategyError,
    ModuleWeightsChoiceRequiredError,
)
from kaine.lifecycle.strategies import (
    MODULE_WEIGHT_GROUPS,
    UnionMergeStrategy,
    default_strategies,
)
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.interoception.module import Interoception
from kaine.modules.sequence.module import Sequence
from kaine.modules.sequence.network import CfCNetwork, ForwardPredictionHead
from kaine.modules.vision.forward import LatentForwardModel
from kaine.modules.vision.module import Vision

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Real modules, built entity-free
# ---------------------------------------------------------------------------


class _Encoder:
    model_id = "test/encoder"
    latent_dim = 4
    clip_len = 1

    async def load(self) -> None:
        return None


class _Reader:
    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def read(self) -> dict[str, Any]:
        return {}

    @property
    def cycle_latency_window(self) -> int:
        return 4


def _bus() -> AsyncBus:
    return MagicMock(spec=AsyncBus)


def _vision(seed: int) -> Vision:
    vision = Vision(_bus(), encoder=_Encoder(), forward_prediction=True, forward_model_units=3)
    vision._forward_model = LatentForwardModel(
        latent_dim=_Encoder.latent_dim, units=3, seed=seed, context_dim=CONTEXT_DIM
    )
    return vision


def _interoception(seed: int, *, expected: float = 0.1) -> Interoception:
    module = Interoception(_bus(), reader=_Reader(), reservoir_seed=seed, forward_model_units=4)
    module._expected_error.load_state_dict({"expected": [expected] * 8, "spread": [expected] * 8})
    return module


def _sequence(seed: int) -> Sequence:
    module = Sequence(_bus(), reservoir_seed=seed, cfc_units=4, forward_prediction=True)
    module._network = CfCNetwork(
        input_size=module._featurizer.feature_dim, units=4, seed=seed
    )
    module._pred_head = ForwardPredictionHead(
        input_size=module._featurizer.feature_dim, units=4, seed=seed
    )
    return module


class _Captured:
    """Hands ForkManager.snapshot a module state captured from a real module."""

    def __init__(self, name: str, state: dict[str, Any]) -> None:
        self.name = name
        self._state = copy.deepcopy(state)

    def serialize(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def deserialize(self, state: dict[str, Any]) -> None:
        self._state = copy.deepcopy(state)


class _Registry:
    def __init__(self, modules: list[Any]) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


def _snapshot(mgr: ForkManager, modules: list[Any]) -> str:
    registry = _Registry([_Captured(m.name, m.serialize()) for m in modules])
    return mgr.snapshot(registry).id


@pytest.fixture
def mgr(tmp_path: Path) -> ForkManager:
    return ForkManager(tmp_path / "forks")


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------


def test_merge_refuses_differing_weights_without_choice(mgr: ForkManager):
    a = _snapshot(mgr, [_vision(1)])
    b = _snapshot(mgr, [_vision(2)])
    before = set(mgr.list_snapshots())
    with pytest.raises(ModuleWeightsChoiceRequiredError) as exc:
        mgr.merge(a, b)
    assert exc.value.modules == ("vision",)
    assert "vision" in str(exc.value)
    assert set(mgr.list_snapshots()) == before


def test_merge_takes_vision_weights_exactly_from_b(mgr: ForkManager):
    parent_a, parent_b = _vision(1), _vision(2)
    a = _snapshot(mgr, [parent_a])
    b = _snapshot(mgr, [parent_b])
    merged = mgr.merge(a, b, module_weights_from="b")
    state_b = parent_b.serialize()
    assert merged.modules["vision"]["forward_model"] == state_b["forward_model"]
    assert len(merged.modules["vision"]["forward_model"]["layers"]) == 2
    assert merged.modules["vision"]["encoder_model_id"] == state_b["encoder_model_id"]

    # The restored entity predicts with b's forward model, not a's.
    fresh = _vision(3)
    mgr.restore(merged.id, _Registry([fresh]))
    assert fresh._forward_model.state_dict() == parent_b._forward_model.state_dict()


def test_merge_takes_interoception_weights_and_seed_together(mgr: ForkManager):
    parent_a = _interoception(11, expected=0.1)
    parent_b = _interoception(22, expected=0.3)
    parent_b._feature_layout = 1
    a = _snapshot(mgr, [parent_a])
    b = _snapshot(mgr, [parent_b])
    merged = mgr.merge(a, b, module_weights_from="a")
    got = merged.modules["interoception"]
    want = parent_a.serialize()
    for key in ("forward_model", "reservoir_seed", "feature_layout", "expected_error"):
        assert got[key] == want[key], key
    assert len(got["forward_model"]["weight"]) == 8

    fresh = _interoception(99)
    mgr.restore(merged.id, _Registry([fresh]))
    assert fresh._forward_model.reservoir_seed == 11
    assert fresh._forward_model.state_dict() == parent_a._forward_model.state_dict()


def test_merge_takes_sequence_head_and_seed_together(mgr: ForkManager):
    parent_a, parent_b = _sequence(5), _sequence(6)
    a = _snapshot(mgr, [parent_a])
    b = _snapshot(mgr, [parent_b])
    merged = mgr.merge(a, b, module_weights_from="b")
    got = merged.modules["sequence"]
    want = parent_b.serialize()
    for key in ("pred_head", "reservoir_seed", "featurizer_layout"):
        assert got[key] == want[key], key


def test_merge_per_module_mapping(mgr: ForkManager):
    vis_a, vis_b = _vision(1), _vision(2)
    int_a, int_b = _interoception(11), _interoception(22)
    a = _snapshot(mgr, [vis_a, int_a])
    b = _snapshot(mgr, [vis_b, int_b])
    merged = mgr.merge(a, b, module_weights_from={"vision": "a", "interoception": "b"})
    assert merged.modules["vision"]["forward_model"] == vis_a.serialize()["forward_model"]
    assert merged.modules["interoception"]["forward_model"] == int_b.serialize()["forward_model"]
    assert merged.modules["interoception"]["reservoir_seed"] == 22


def test_mapping_missing_a_module_refused(mgr: ForkManager):
    a = _snapshot(mgr, [_vision(1), _interoception(11)])
    b = _snapshot(mgr, [_vision(2), _interoception(22)])
    before = set(mgr.list_snapshots())
    with pytest.raises(ModuleWeightsChoiceRequiredError) as exc:
        mgr.merge(a, b, module_weights_from={"vision": "a"})
    assert exc.value.modules == ("interoception",)
    assert "interoception" in str(exc.value)
    assert set(mgr.list_snapshots()) == before


@pytest.mark.parametrize(
    "choice",
    ["c", "", {"vision": "c"}, {"not_a_module": "a"}, {"vision": None}, 1],
)
def test_malformed_choice_rejected(mgr: ForkManager, choice):
    a = _snapshot(mgr, [_vision(1)])
    b = _snapshot(mgr, [_vision(2)])
    with pytest.raises(ValueError):
        mgr.merge(a, b, module_weights_from=choice)


def test_equal_groups_need_no_choice(mgr: ForkManager):
    root = _snapshot(mgr, [_vision(1), _interoception(11)])
    a = mgr.fork(root).id
    b = mgr.fork(root).id
    merged = mgr.merge(a, b)
    assert merged.metadata["module_weights_from"]["vision"] == {"from": "a", "reason": "equal"}
    assert merged.metadata["module_weights_from"]["interoception"]["reason"] == "equal"


def test_one_sided_group_needs_no_choice(mgr: ForkManager):
    vision = _vision(1)
    a = _snapshot(mgr, [vision, _interoception(11)])
    # b carries no vision module, and an interoception state with no weight
    # group (its serialize failed).
    b = mgr.snapshot(
        _Registry([_Captured("interoception", {"_serialize_error": "boom"})])
    ).id
    merged = mgr.merge(a, b)
    assert merged.modules["vision"]["forward_model"] == vision.serialize()["forward_model"]
    assert merged.metadata["module_weights_from"]["vision"] == {"from": "a", "reason": "one-sided"}
    assert merged.metadata["module_weights_from"]["interoception"] == {
        "from": "a",
        "reason": "one-sided",
    }


class _Recording:
    def __init__(self) -> None:
        self.seen: list[set[str]] = []

    def merge(self, state_a, state_b):
        for state in (state_a, state_b):
            if state is not None:
                self.seen.append(set(state))
        return UnionMergeStrategy().merge(state_a, state_b)


def test_union_never_sees_a_weight_key(tmp_path: Path):
    recording = _Recording()
    mgr = ForkManager(tmp_path / "forks", default_strategy=recording)
    a = _snapshot(mgr, [_vision(1), _interoception(11), _sequence(5)])
    b = _snapshot(mgr, [_vision(2), _interoception(22), _sequence(6)])
    merged = mgr.merge(a, b, module_weights_from="a")
    assert recording.seen, "the default strategy never ran"
    every_group_key = {k for keys in MODULE_WEIGHT_GROUPS.values() for k in keys}
    for keys in recording.seen:
        assert not (keys & every_group_key), keys & every_group_key
    # The non-weight keys still merged by the strategy (b's scalar wins).
    assert merged.modules["interoception"]["cycle_cursor"] == "0"


def test_choice_recorded_in_metadata(mgr: ForkManager):
    shared = _interoception(11)
    a = _snapshot(mgr, [_vision(1), shared])
    b = _snapshot(mgr, [_vision(2), shared])
    merged = mgr.merge(a, b, module_weights_from="b")
    record = mgr.load(merged.id).metadata["module_weights_from"]
    assert record["vision"] == {"from": "b", "reason": "chosen"}
    assert record["interoception"] == {"from": "a", "reason": "equal"}


class _Boom:
    def merge(self, state_a, state_b):
        raise RuntimeError("strategy exploded")


def test_failing_strategy_for_weight_module_refuses(mgr: ForkManager):
    a = _snapshot(mgr, [_interoception(11)])
    b = _snapshot(mgr, [_interoception(22)])
    before = set(mgr.list_snapshots())
    with pytest.raises(ModuleMergeStrategyError) as exc:
        mgr.merge(a, b, module_weights_from="a", strategies={"interoception": _Boom()})
    assert exc.value.module == "interoception"
    assert "interoception" in str(exc.value)
    assert set(mgr.list_snapshots()) == before


def test_failing_strategy_for_other_module_keeps_todays_fallback(mgr: ForkManager):
    a = mgr.snapshot(_Registry([_Captured("vocal", {"voice_mode": "a"})])).id
    b = mgr.snapshot(_Registry([_Captured("vocal", {"voice_mode": "b"})])).id
    merged = mgr.merge(a, b, strategies={"vocal": _Boom()})
    assert merged.modules["vocal"] == {"voice_mode": "a"}


def test_one_parent_module_still_runs_through_its_strategy(mgr: ForkManager):
    a = _snapshot(mgr, [_interoception(11)])
    b = mgr.snapshot(_Registry([_Captured("vocal", {"voice_mode": "b"})])).id
    with pytest.raises(ModuleMergeStrategyError):
        mgr.merge(a, b, strategies={"interoception": _Boom()})


def test_planning_learned_model_needs_a_choice(mgr: ForkManager):
    def planning(pb: float) -> _Captured:
        return _Captured(
            "planning",
            {
                "posterior": [[0.5, 0.5]],
                "learned": {"pB": [[[pb, 1.0]]], "carried_prior": [[0.5, 0.5]]},
            },
        )

    a = mgr.snapshot(_Registry([planning(1.0)])).id
    b = mgr.snapshot(_Registry([planning(2.0)])).id
    with pytest.raises(ModuleWeightsChoiceRequiredError) as exc:
        mgr.merge(a, b)
    assert exc.value.modules == ("planning",)
    merged = mgr.merge(a, b, module_weights_from="b")
    assert merged.modules["planning"]["learned"]["pB"] == [[[2.0, 1.0]]]


# ---------------------------------------------------------------------------
# Restore refuses a structurally different weight state
# ---------------------------------------------------------------------------


def _union(module_a, module_b) -> dict[str, Any]:
    """The garbled state the pre-fix default merge produced from two real modules."""
    return UnionMergeStrategy().merge(module_a.serialize(), module_b.serialize())


def test_concatenated_vision_layers_refused_on_restore(caplog):
    garbled = _union(_vision(1), _vision(2))
    assert len(garbled["forward_model"]["layers"]) == 4
    fresh = _vision(3)
    untouched = fresh._forward_model.state_dict()
    with caplog.at_level(logging.WARNING):
        fresh.deserialize(garbled)
    assert fresh._forward_model.state_dict() == untouched
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "vision" in text
    assert "4 layers" in text and "2" in text


def test_vision_shape_guard_checks_every_layer():
    model = LatentForwardModel(latent_dim=4, units=3, seed=1, context_dim=CONTEXT_DIM)
    state = model.state_dict()
    assert model.matches_state_shape(state)
    bad = copy.deepcopy(state)
    bad["layers"][1]["bias"] = bad["layers"][1]["bias"] + [0.0]
    assert not model.matches_state_shape(bad)
    assert "bias" in model.state_shape_mismatch(bad)
    three = copy.deepcopy(state)
    three["layers"].insert(1, copy.deepcopy(three["layers"][0]))
    assert "3 layers" in model.state_shape_mismatch(three)


def test_interoception_bad_weights_keep_rest_of_state(caplog):
    garbled = _union(_interoception(11), _interoception(22))
    assert len(garbled["forward_model"]["weight"]) == 16
    garbled["cycle_cursor"] = "123-0"
    garbled["read_interval_s"] = 4.5
    garbled["fatigue"] = {"value": 0.25}
    fresh = _interoception(99)
    with caplog.at_level(logging.WARNING):
        fresh.deserialize(garbled)
    # The readout starts fresh on the restored reservoir seed.
    reference = _interoception(int(garbled["reservoir_seed"]))
    assert fresh._forward_model.state_dict() == reference._forward_model.state_dict()
    # The rest of the restored state is kept.
    assert fresh._cycle_cursor == "123-0"
    assert fresh._read_interval_s == 4.5
    assert fresh._fatigue.state_dict() == {"value": 0.25}
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "interoception" in text and "16" in text


def test_sequence_bad_head_keeps_rest_of_state(caplog):
    garbled = _union(_sequence(5), _sequence(6))
    garbled["user_input_cursors"] = {"audition.out": "77-0"}
    fresh = _sequence(9)
    untouched = fresh._pred_head.state_dict()
    with caplog.at_level(logging.WARNING):
        fresh.deserialize(garbled)
    assert fresh._pred_head.state_dict() == untouched
    assert fresh._user_input_cursors["audition.out"] == "77-0"
    text = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "sequence" in text


# ---------------------------------------------------------------------------
# The inventory of weight-bearing modules
# ---------------------------------------------------------------------------

# The reviewed inventory. Changing it is a persistence and identity change: the
# second review checks each key against the module's serialize/deserialize.
EXPECTED_WEIGHT_GROUPS: dict[str, tuple[str, ...]] = {
    "vision": ("forward_model", "encoder_model_id"),
    "audition": ("forward_model", "forward_model_features", "acoustic_forward_models"),
    "interoception": (
        "forward_model",
        "reservoir_seed",
        "feature_layout",
        "expected_error",
        "self_rhythm",
    ),
    "sequence": ("pred_head", "reservoir_seed", "featurizer_layout"),
    "planning": ("learned",),
}

# Numeric lists in stock module states that are reviewed as not learned
# parameters, with the reason.
NON_WEIGHT_LIST_KEYS: dict[tuple[str, str], str] = {
    # Per-feature mean and variance of the RAM-only frame buffer; content-free
    # statistics (latent-content-privacy) that nothing reads back.
    ("vision", "buffer_summary"): "buffer statistics, not weights",
    ("audition", "auditory_buffer_summary"): "buffer statistics, not weights",
}


def test_weight_group_inventory_is_pinned():
    assert MODULE_WEIGHT_GROUPS == EXPECTED_WEIGHT_GROUPS


def _weight_like(value: Any) -> bool:
    """A nested numeric list, or a list of 16 or more numbers, anywhere in value."""

    def number(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    if isinstance(value, dict):
        return any(_weight_like(v) for v in value.values())
    if isinstance(value, list):
        if value and all(number(x) for x in value) and len(value) >= 16:
            return True
        if any(isinstance(x, list) and x and all(number(y) for y in x) for x in value):
            return True
        return any(_weight_like(x) for x in value if isinstance(x, (dict, list)))
    return False


def _stock_registry(monkeypatch) -> Any:
    """Every stock module, built from the shipped config with every module on."""
    from kaine.boot.registry import build_registry, known_module_names
    from kaine.config import load_kaine_config

    monkeypatch.setenv("KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii"))
    empty = Path(os.environ.get("TMPDIR", "/tmp")) / f"empty-overlay-{os.getpid()}.toml"
    empty.write_text("")
    try:
        cfg = copy.deepcopy(
            load_kaine_config(
                REPO / "config" / "kaine.toml",
                empty,
                profiles_dir=REPO / "config" / "profiles",
                profile="first_configuration",
            )
        )
    finally:
        empty.unlink(missing_ok=True)
    for name in ("episodic_memory", "social_cognition"):
        cfg.setdefault(name, {}).setdefault("qdrant", {}).setdefault("api_key", "test-key")
    for name in known_module_names():
        cfg["modules"][name] = True
    # Switch on every learned component a stock module can carry.
    cfg.setdefault("interoception", {})["self_rhythm_enabled"] = True
    # Audition's forward models are always on; vision's and sequence's are opt-in.
    for name in ("vision", "sequence"):
        cfg.setdefault(name, {})["forward_prediction"] = True
    return build_registry(MagicMock(spec=AsyncBus), cfg)


def _materialise_lazy_weights(registry: Any) -> None:
    """Build the learned parts some modules only build in ``initialize()``.

    Vision builds its forward model after its encoder loads, and sequence builds
    its network and head in ``initialize()``; neither is reachable without a
    bus and an encoder. These mirror those two builders with the real classes.
    """
    vision = registry.get("vision")
    if vision._forward_model is None:
        vision._forward_model = LatentForwardModel(
            latent_dim=4, units=3, seed=0, context_dim=CONTEXT_DIM
        )
    sequence = registry.get("sequence")
    if sequence._network is None:
        sequence._network = CfCNetwork(
            input_size=sequence._featurizer.feature_dim, units=4, seed=0
        )
    if sequence._pred_head is None:
        sequence._pred_head = ForwardPredictionHead(
            input_size=sequence._featurizer.feature_dim, units=4, seed=0
        )


def test_every_weight_like_list_is_declared_or_reviewed(monkeypatch):
    registry = _stock_registry(monkeypatch)
    _materialise_lazy_weights(registry)
    specialised = set(default_strategies())
    states = {m.name: m.serialize() for m in registry.all_modules()}

    # Each declared group is really serialized, so the walk below sees the
    # learned parts and the inventory cannot pass by building them away.
    assert "forward_model" in states["vision"]
    assert "pred_head" in states["sequence"]
    assert "self_rhythm" in states["interoception"]
    assert states["audition"]["acoustic_forward_models"]

    undeclared: list[tuple[str, str]] = []
    for name, state in states.items():
        if name in specialised:
            continue
        group = set(MODULE_WEIGHT_GROUPS.get(name, ()))
        for key, value in state.items():
            if key in group or (name, key) in NON_WEIGHT_LIST_KEYS:
                continue
            if _weight_like(value):
                undeclared.append((name, key))
    assert not undeclared, (
        "module state holds weight-like lists outside its weight group: "
        f"{undeclared}; declare them in MODULE_WEIGHT_GROUPS or review them "
        "into NON_WEIGHT_LIST_KEYS"
    )


def test_guard_names_an_undeclared_decoder():
    state = {"decoder": [[0.1, 0.2], [0.3, 0.4]], "cursor": "0"}
    flagged = [k for k, v in state.items() if _weight_like(v)]
    assert flagged == ["decoder"]


def test_audition_shape_guard_counts_layers():
    from kaine.modules.audition.forward import AuditoryForwardModel

    model = AuditoryForwardModel(feature_dim=4, units=3, seed=1, context_dim=CONTEXT_DIM)
    other = AuditoryForwardModel(feature_dim=4, units=3, seed=2, context_dim=CONTEXT_DIM)
    garbled = UnionMergeStrategy().merge(model.state_dict(), other.state_dict())
    assert len(garbled["layers"]) == 4
    assert not model.matches_state_shape(garbled)
    assert "4 layers" in model.state_shape_mismatch(garbled)
    assert model.matches_state_shape(other.state_dict())


def _bias_only_mismatch(state: dict[str, Any]) -> dict[str, Any]:
    """Valid-shaped weights with new values, and a bias one element too long."""
    weight = [[v + 1.0 for v in row] for row in state["weight"]]
    return {"weight": weight, "bias": list(state["bias"]) + [0.0]}


def test_interoception_torch_readout_load_is_atomic():
    pytest.importorskip("ncps")
    from kaine.modules.interoception.forward import SubstrateForwardModel

    model = SubstrateForwardModel(feature_dim=8, units=4, backend="torch", seed=3)
    before = model.state_dict()
    with pytest.raises(ValueError):
        model.load_state_dict(_bias_only_mismatch(before))
    assert model.state_dict() == before


def test_sequence_torch_head_load_is_atomic():
    pytest.importorskip("torch")
    head = ForwardPredictionHead(input_size=24, units=4, backend="torch", seed=3)
    before = head.state_dict()
    with pytest.raises(ValueError):
        head.load_state_dict(_bias_only_mismatch(before))
    assert head.state_dict() == before


def test_self_rhythm_refuses_concatenated_population():
    from kaine.oscillator.module_oscillator import (
        make_self_rhythm_oscillator,
        snntorch_available,
    )

    if not snntorch_available():
        pytest.skip("the oscillator extra (snnTorch) is not installed")
    one = make_self_rhythm_oscillator(seed=1)
    two = make_self_rhythm_oscillator(seed=2)
    garbled = UnionMergeStrategy().merge(one.serialize(), two.serialize())
    assert len(garbled["mem"]) > one.population_size or len(garbled["weights"]) > one.population_size
    fresh = make_self_rhythm_oscillator(seed=3)
    before = fresh.serialize()
    fresh.deserialize(garbled)
    after = fresh.serialize()
    assert len(after["mem"]) == fresh.population_size
    assert after["weights"] == before["weights"]
