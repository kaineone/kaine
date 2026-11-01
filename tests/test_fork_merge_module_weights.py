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
    "planning": ("learned", "posterior", "last_action"),
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


def _live_a_little(registry: Any) -> None:
    """Drive the learned parts through some experience, so the walk sees the
    shapes a lived state has (filled statistics, grown histories), not only a
    freshly built one."""
    import random

    rng = random.Random(7)
    vision = registry.get("vision")._forward_model
    for _ in range(4):
        vision.step([rng.random() for _ in range(vision.latent_dim)])
    audition = registry.get("audition")
    for _ in range(4):
        fm = audition._forward_model
        fm.step([rng.random() for _ in range(fm.feature_dim)])
    acoustic = getattr(audition, "_acoustic_forward_model", None)
    if acoustic is not None:
        for _ in range(4):
            acoustic.step([rng.random() for _ in range(acoustic.feature_dim)])
    interoception = registry.get("interoception")
    for _ in range(4):
        interoception._forward_model.step([rng.random() for _ in range(8)])
        interoception._expected_error.unexpected([rng.random() for _ in range(8)], 1.0)
        if interoception._self_rhythm is not None:
            interoception._self_rhythm.step(rng.random())
    sequence = registry.get("sequence")
    dim = sequence._featurizer.feature_dim
    for _ in range(4):
        sequence._pred_head.adapt([rng.random() for _ in range(4)], [rng.random() for _ in range(dim)])


def test_every_weight_like_list_is_declared_or_reviewed(monkeypatch):
    registry = _stock_registry(monkeypatch)
    _materialise_lazy_weights(registry)
    _live_a_little(registry)
    states = {m.name: m.serialize() for m in registry.all_modules()}

    # Each declared group is really serialized, so the walk below sees the
    # learned parts and the inventory cannot pass by building them away.
    assert "forward_model" in states["vision"]
    assert "pred_head" in states["sequence"]
    assert "self_rhythm" in states["interoception"]
    assert states["audition"]["acoustic_forward_models"]
    # ... and the walk sees a lived state, not only a freshly built one.
    assert states["interoception"]["expected_error"]["expected"]

    # Every module is walked, the ones with a specialised strategy too: a
    # learned key added to one of them must be declared like any other.
    assert set(default_strategies()) <= set(states)
    undeclared: list[tuple[str, str]] = []
    for name, state in states.items():
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


# ---------------------------------------------------------------------------
# The world model's module state follows world_model_from (second review R1)
# ---------------------------------------------------------------------------


def _wm_bus() -> AsyncBus:
    from unittest.mock import AsyncMock

    bus = MagicMock(spec=AsyncBus)
    bus.client = MagicMock()
    bus.client.xrevrange = AsyncMock(return_value=[])
    return bus


def _world_model(path: Path, *, persist: bool = True, seed: int = 0):
    from kaine.modules.world_model.module import WorldModel

    return WorldModel(
        _wm_bus(),
        backend="dreamerv3",
        engine="numpy",
        persist_weights=persist,
        checkpoint_path=str(path),
        world_model_kwargs={
            "seed": seed,
            "deter_dim": 8,
            "stoch_dim": 4,
            "stoch_classes": 4,
            "hidden_dim": 8,
        },
    )


def _sidecar(path: Path) -> dict[str, Any]:
    import json

    return json.loads(Path(str(path) + ".passes.json").read_text())


def test_world_model_state_follows_world_model_from(tmp_path: Path):
    """The reviewer's reproduction: a persist-off restore of a merge made with
    world_model_from='a' rewrote parent b's pass-count sidecar from 7 to 3."""
    mgr = ForkManager(tmp_path / "forks")
    pa = tmp_path / "entity_a" / "world_model.ckpt"
    pb = tmp_path / "entity_b" / "world_model.ckpt"
    pa.parent.mkdir()
    pb.parent.mkdir()
    a_model, b_model = _world_model(pa, seed=1), _world_model(pb, seed=2)
    a_model._successful_training_passes = 3
    b_model._successful_training_passes = 7
    a_model._save_weights(reason="test")
    b_model._save_weights(reason="test")
    a = mgr.snapshot(_Registry([a_model])).id
    b = mgr.snapshot(_Registry([b_model])).id

    merged = mgr.merge(a, b, world_model_from="a")
    assert merged.metadata["artifact_sources"]["world_model"] == "a"
    assert merged.modules["world_model"] == a_model.serialize()
    assert merged.metadata["module_weights_from"]["world_model"] == {
        "from": "a",
        "reason": "chosen",
    }

    # Persistence on: the instance keeps its own path and gets a's weights and count.
    pc = tmp_path / "entity_c" / "world_model.ckpt"
    pc.parent.mkdir()
    c_model = _world_model(pc, seed=9)
    mgr.restore(merged.id, _Registry([c_model]))
    assert c_model._checkpoint_path == str(pc.resolve())
    assert c_model._wm.export_params(extra={}) == a_model._wm.export_params(extra={})
    assert c_model.successful_training_passes == 3

    # Persistence off: nothing is adopted from snapshot data, nothing is written.
    d_model = _world_model(tmp_path / "unused.ckpt", persist=False, seed=9)
    mgr.restore(merged.id, _Registry([d_model]))
    assert d_model._checkpoint_path is None
    assert d_model.successful_training_passes == 3
    assert _sidecar(pb) == {"successful_training_passes": 7}
    assert _sidecar(pa) == {"successful_training_passes": 3}
    assert not (tmp_path / "unused.ckpt.passes.json").exists()


def test_world_model_deserialize_never_adopts_a_snapshot_path(tmp_path: Path):
    model = _world_model(tmp_path / "unused.ckpt", persist=False)
    model.deserialize({"checkpoint_path": str(tmp_path / "other.ckpt")})
    assert model._checkpoint_path is None
    model.restore_training_pass_count(5)
    assert model.successful_training_passes == 5
    assert not (tmp_path / "other.ckpt.passes.json").exists()


def test_pass_count_sidecar_written_only_with_persistence_on(tmp_path: Path):
    model = _world_model(tmp_path / "unused.ckpt", persist=False)
    # Even a path that reached the instance some other way is never written to
    # while persistence is off.
    model._checkpoint_path = str(tmp_path / "stray.ckpt")
    model.restore_training_pass_count(4)
    assert model.successful_training_passes == 4
    assert not (tmp_path / "stray.ckpt.passes.json").exists()


def test_one_sided_world_model_state_comes_with_its_weights(tmp_path: Path):
    mgr = ForkManager(tmp_path / "forks")
    pa = tmp_path / "entity_a" / "world_model.ckpt"
    pa.parent.mkdir()
    a_model = _world_model(pa, seed=1)
    a_model._save_weights(reason="test")
    b_model = _world_model(tmp_path / "unused.ckpt", persist=False, seed=2)
    a = mgr.snapshot(_Registry([a_model])).id
    b = mgr.snapshot(_Registry([b_model])).id
    merged = mgr.merge(b, a)
    assert merged.modules["world_model"] == a_model.serialize()
    assert merged.metadata["module_weights_from"]["world_model"] == {
        "from": "b",
        "reason": "one-sided",
    }


# ---------------------------------------------------------------------------
# Second review S1-S3 and the minor findings
# ---------------------------------------------------------------------------


def _planning(pb: float, posterior: list[float], action: str) -> _Captured:
    return _Captured(
        "planning",
        {
            "posterior": [posterior],
            "last_action": action,
            "step_counter": 4,
            "learned": {"pB": [[[pb, 1.0]]], "carried_prior": [[0.5, 0.5]], "last_action_index": 1},
        },
    )


def test_planning_belief_travels_with_its_learned_prior(mgr: ForkManager):
    # b is far more certain; the certainty pick must not pair b's belief with a's prior.
    a = mgr.snapshot(_Registry([_planning(1.0, [0.5, 0.5], "act1")])).id
    b = mgr.snapshot(_Registry([_planning(2.0, [0.99, 0.01], "act2")])).id
    merged = mgr.merge(a, b, module_weights_from="a").modules["planning"]
    assert merged["posterior"] == [[0.5, 0.5]]
    assert merged["last_action"] == "act1"
    assert merged["learned"]["pB"] == [[[1.0, 1.0]]]
    assert "selected_fork_entropy" not in merged


def _vision_without_forward_model(model_id: str = _Encoder.model_id) -> _Captured:
    return _Captured("vision", {"encoder_model_id": model_id})


def test_bindings_only_side_is_one_sided(mgr: ForkManager):
    trained = _vision(1)
    a = _snapshot(mgr, [trained])
    b = mgr.snapshot(_Registry([_vision_without_forward_model()])).id
    merged = mgr.merge(a, b)
    assert merged.modules["vision"]["forward_model"] == trained.serialize()["forward_model"]
    assert merged.metadata["module_weights_from"]["vision"] == {"from": "a", "reason": "one-sided"}


def test_bindings_only_side_with_other_bindings_needs_a_choice_naming_the_holder(mgr: ForkManager):
    a = _snapshot(mgr, [_vision(1)])
    b = mgr.snapshot(_Registry([_vision_without_forward_model("other/encoder")])).id
    with pytest.raises(ModuleWeightsChoiceRequiredError) as exc:
        mgr.merge(a, b)
    assert exc.value.holders == {"vision": ("a",)}
    assert "only a holds learned weights" in str(exc.value)


def test_strategy_error_carries_the_type_only(mgr: ForkManager):
    class _Leaky:
        def merge(self, state_a, state_b):
            raise ValueError("cursor 1714-0 and the secret value 0.4242")

    a = _snapshot(mgr, [_interoception(11)])
    b = _snapshot(mgr, [_interoception(22)])
    with pytest.raises(ModuleMergeStrategyError) as exc:
        mgr.merge(a, b, module_weights_from="a", strategies={"interoception": _Leaky()})
    assert "ValueError" in str(exc.value)
    assert "0.4242" not in str(exc.value)


def test_mapping_naming_an_old_and_a_current_name_refused(mgr: ForkManager):
    a = _snapshot(mgr, [_vision(1)])
    b = _snapshot(mgr, [_vision(2)])
    from kaine import legacy_names

    old = next(k for k, e in legacy_names.MODULES.items() if e["new_key"] == "vision")
    with pytest.raises(ValueError, match="twice"):
        mgr.merge(a, b, module_weights_from={old: "a", "vision": "b"})


def test_serialize_error_marker_not_carried_into_the_merge(mgr: ForkManager):
    vision = _vision(1)
    a = mgr.snapshot(
        _Registry([_Captured("vision", vision.serialize()), _Captured("vocal", {"voice_mode": "a"})])
    ).id
    b = mgr.snapshot(
        _Registry(
            [
                _Captured("vision", {"_serialize_error": "boom"}),
                _Captured("vocal", {"_serialize_error": "boom"}),
            ]
        )
    ).id
    merged = mgr.merge(a, b)
    assert "_serialize_error" not in merged.modules["vision"]
    assert merged.modules["vocal"] == {"voice_mode": "a"}
    assert merged.metadata["serialize_errors_dropped"] == {"vision": ["b"], "vocal": ["b"]}


def test_refused_readout_drops_its_expected_error(caplog):
    garbled = _union(_interoception(11), _interoception(22))
    garbled["expected_error"] = {"expected": [0.5] * 8, "spread": [0.5] * 8}
    fresh = _interoception(99)
    fresh._expected_error.load_state_dict({"expected": [], "spread": []})
    with caplog.at_level(logging.WARNING):
        fresh.deserialize(garbled)
    assert fresh._expected_error.state_dict() == {"expected": [], "spread": []}
    assert "expected-error" in caplog.text


def test_refused_self_rhythm_warns_and_restores_nothing(caplog):
    from kaine.oscillator.module_oscillator import (
        make_self_rhythm_oscillator,
        snntorch_available,
    )

    if not snntorch_available():
        pytest.skip("the oscillator extra (snnTorch) is not installed")
    donor = make_self_rhythm_oscillator(seed=1)
    for _ in range(5):
        donor.step(0.7)
    state = donor.serialize()
    state["rng_state"] = {"not": "a bit generator state"}
    fresh = make_self_rhythm_oscillator(seed=3)
    before = fresh.serialize()
    with caplog.at_level(logging.WARNING):
        fresh.deserialize(state)
    assert fresh.serialize() == before
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("interoception self-rhythm" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# Restored before initialize(): the weights wait for the model to be built
# ---------------------------------------------------------------------------


def _init_bus() -> AsyncBus:
    from unittest.mock import AsyncMock

    bus = MagicMock(spec=AsyncBus)
    bus.client = MagicMock()
    bus.client.xrevrange = AsyncMock(return_value=[])
    bus.read = AsyncMock(return_value=[])
    return bus


@pytest.mark.asyncio
async def test_vision_restored_before_initialize_keeps_its_forward_model():
    parent = _vision(1)
    state = copy.deepcopy(parent.serialize())
    vision = Vision(_init_bus(), encoder=_Encoder(), forward_prediction=True, forward_model_units=3)
    vision.deserialize(copy.deepcopy(state))
    assert vision.serialize()["forward_model"] == state["forward_model"]
    await vision.initialize()
    try:
        assert vision._forward_model.state_dict() == parent._forward_model.state_dict()
    finally:
        await vision.shutdown()


@pytest.mark.asyncio
async def test_sequence_restored_before_initialize_keeps_its_head():
    parent = _sequence(5)
    head = parent._pred_head.state_dict()
    parent._pred_head.load_state_dict(
        {"weight": [[w + 0.5 for w in row] for row in head["weight"]], "bias": [b + 0.5 for b in head["bias"]]}
    )
    state = copy.deepcopy(parent.serialize())
    sequence = Sequence(_init_bus(), reservoir_seed=9, cfc_units=4, forward_prediction=True)
    sequence.deserialize(copy.deepcopy(state))
    assert sequence.serialize()["pred_head"] == state["pred_head"]
    await sequence.initialize()
    try:
        assert sequence._pred_head.state_dict() == parent._pred_head.state_dict()
        assert sequence._network.reservoir_seed == 5
    finally:
        await sequence.shutdown()


def test_forward_prediction_off_warns_when_a_forward_model_is_dropped(caplog):
    state = _vision(1).serialize()
    vision = Vision(_bus(), encoder=_Encoder(), forward_prediction=False)
    with caplog.at_level(logging.WARNING):
        vision.deserialize(state)
    assert "forward prediction is off" in caplog.text
    sequence = Sequence(_bus(), reservoir_seed=5, cfc_units=4, forward_prediction=False)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        sequence.deserialize(_sequence(5).serialize())
    assert "forward prediction is off" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("second_has_weights", [False, True])
async def test_vision_second_restore_before_initialize_replaces_the_pending_model(second_has_weights):
    first, second = _vision(1), _vision(2)
    second_state = second.serialize()
    if not second_has_weights:
        second_state = {"encoder_model_id": second_state["encoder_model_id"]}
    vision = Vision(_init_bus(), encoder=_Encoder(), forward_prediction=True, forward_model_units=3)
    fresh = vision.serialize()
    vision.deserialize(copy.deepcopy(first.serialize()))
    vision.deserialize(copy.deepcopy(second_state))
    await vision.initialize()
    try:
        got = vision._forward_model.state_dict()
        assert got != first._forward_model.state_dict()
        if second_has_weights:
            assert got == second._forward_model.state_dict()
        else:
            assert "forward_model" not in fresh  # nothing was built or pending before
    finally:
        await vision.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("second_has_weights", [False, True])
async def test_sequence_second_restore_before_initialize_replaces_the_pending_head(second_has_weights):
    first, second = _sequence(5), _sequence(6)
    second_state = second.serialize()
    if not second_has_weights:
        second_state = {k: v for k, v in second_state.items() if k != "pred_head"}
    sequence = Sequence(_init_bus(), reservoir_seed=9, cfc_units=4, forward_prediction=True)
    sequence.deserialize(copy.deepcopy(first.serialize()))
    sequence.deserialize(copy.deepcopy(second_state))
    await sequence.initialize()
    try:
        assert sequence._network.reservoir_seed == 6
        got = sequence._pred_head.state_dict()
        # The first snapshot's head (trained on reservoir 5) never lands on reservoir 6.
        assert got != first._pred_head.state_dict()
        if second_has_weights:
            assert got == second._pred_head.state_dict()
    finally:
        await sequence.shutdown()


def test_world_model_state_reason_when_the_weights_parent_has_no_state(tmp_path: Path):
    mgr = ForkManager(tmp_path / "forks")
    pa = tmp_path / "entity_a" / "world_model.ckpt"
    pb = tmp_path / "entity_b" / "world_model.ckpt"
    pa.parent.mkdir()
    pb.parent.mkdir()
    a_model, b_model = _world_model(pa, seed=1), _world_model(pb, seed=2)
    a_model._save_weights(reason="test")
    b_model._save_weights(reason="test")
    a = mgr.snapshot(_Registry([a_model])).id
    b = mgr.snapshot(_Registry([b_model])).id
    # a's snapshot keeps its world-model artifacts but loses the module state.
    from kaine.lifecycle.snapshot import load_snapshot, save_snapshot

    snap_a = load_snapshot(mgr.root, a)
    save_snapshot(mgr.root, snap_a.with_modules({}))
    merged = mgr.merge(a, b, world_model_from="a")
    assert merged.metadata["artifact_sources"]["world_model"] == "a"
    assert merged.metadata["module_weights_from"]["world_model"] == {
        "from": "b",
        "reason": "the weights' parent holds no module state",
    }
