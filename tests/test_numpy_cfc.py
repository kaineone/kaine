# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the NumPy CfC implementation and backend parity."""
from __future__ import annotations

import importlib.util
import logging
import math
import subprocess
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from kaine.cfc_numpy import (
    NumpyReadout,
    ReservoirWeights,
    draw_reservoir_seed,
    generate_cfc_weights,
    numpy_cfc_step,
)
from kaine.experiment.seeding import set_global_seed
from kaine.extras import REQUIREMENTS
from kaine.modules.chronos.network import CfCNetwork, ForwardPredictionHead
from kaine.modules.soma.expected_error import ExpectedErrorModel
from kaine.modules.soma.forward import SubstrateForwardModel
from kaine.modules.soma.module import Soma

_TORCH = (
    importlib.util.find_spec("torch") is not None
    and importlib.util.find_spec("ncps") is not None
)


# ---------------------------------------------------------------------------
# kaine.cfc_numpy unit tests
# ---------------------------------------------------------------------------

def test_reservoir_generation_shape_and_seed_sensitivity():
    r1 = ReservoirWeights.generate(seed=12345, input_size=8, units=32)
    r2 = ReservoirWeights.generate(seed=12345, input_size=8, units=32)
    r3 = ReservoirWeights.generate(seed=54321, input_size=8, units=32)

    assert r1.input_size == 8
    assert r1.units == 32
    assert r1.backbone_units == 128
    assert r1.backbone_w.shape == (128, 8 + 32)
    assert r1.backbone_b.shape == (128,)
    for name in ("ff1", "ff2", "time_a", "time_b"):
        w = getattr(r1, f"{name}_w")
        b = getattr(r1, f"{name}_b")
        assert w.shape == (32, 128)
        assert b.shape == (32,)

    assert np.allclose(r1.backbone_w, r2.backbone_w)
    assert np.allclose(r1.ff1_w, r2.ff1_w)
    assert not np.allclose(r1.backbone_w, r3.backbone_w)


def test_generate_cfc_weights_readout_uses_same_seed():
    reservoir, readout = generate_cfc_weights(seed=7, input_size=4, units=8, out=4)
    assert readout.W.shape == (4, 8)
    assert readout.b.shape == (4,)
    # Readout weights must differ from reservoir weights (different distribution).
    assert not np.allclose(readout.W, reservoir.backbone_w[:4, :8])


def test_numpy_cfc_step_shape_and_finite():
    r = ReservoirWeights.generate(seed=1, input_size=4, units=8)
    h = numpy_cfc_step(r, [0.1, 0.2, 0.3, 0.4], [0.0] * 8)
    assert len(h) == 8
    assert all(math.isfinite(v) for v in h)


def test_numpy_readout_sgd_step_changes_weights():
    rng = np.random.default_rng(11)
    readout = NumpyReadout(units=8, out=4, rng=rng)
    hidden = [0.1] * 8
    target = [0.5, -0.2, 0.1, 0.9]
    before_w = readout.W.copy()
    loss = readout.sgd_step(hidden, target, lr=0.1)
    assert math.isfinite(loss)
    assert not np.allclose(readout.W, before_w)


# ---------------------------------------------------------------------------
# Soma numpy / torch parity
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _TORCH, reason="torch/ncps not installed")
def test_soma_numpy_torch_parity_over_500_steps():
    m_np = SubstrateForwardModel(
        backend="numpy", feature_dim=8, units=16, seed=123, lr=0.01
    )
    m_torch = SubstrateForwardModel(
        backend="torch", feature_dim=8, units=16, seed=123, lr=0.01
    )

    rng = np.random.default_rng(99)
    for step in range(500):
        x = rng.uniform(0.0, 1.0, size=8).tolist()
        err_np = m_np.step(x)
        err_torch = m_torch.step(x)
        assert err_np == pytest.approx(err_torch, abs=1e-5)
        assert np.allclose(m_np._last_hidden, m_torch._last_hidden, atol=1e-5)
        assert np.allclose(m_np._last_prediction, m_torch._last_prediction, atol=1e-5)
        if step % 50 == 0:
            assert np.allclose(
                np.asarray(m_np.state_dict()["weight"]),
                np.asarray(m_torch.state_dict()["weight"]),
                atol=1e-5,
            )
            assert np.allclose(
                np.asarray(m_np.state_dict()["bias"]),
                np.asarray(m_torch.state_dict()["bias"]),
                atol=1e-5,
            )

    assert np.allclose(
        np.asarray(m_np.state_dict()["weight"]),
        np.asarray(m_torch.state_dict()["weight"]),
        atol=1e-5,
    )


# ---------------------------------------------------------------------------
# Chronos head numpy / torch parity
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _TORCH, reason="torch/ncps not installed")
def test_chronos_head_numpy_torch_parity():
    head_np = ForwardPredictionHead(
        backend="numpy", input_size=8, units=16, seed=55, lr=0.05
    )
    head_torch = ForwardPredictionHead(
        backend="torch", input_size=8, units=16, seed=55, lr=0.05
    )

    hidden = [0.3] * 16
    target = [0.5] * 8
    for _ in range(200):
        pred_np = head_np.predict(hidden)
        pred_torch = head_torch.predict(hidden)
        assert np.allclose(pred_np, pred_torch, atol=1e-5)

        loss_np = head_np.adapt(hidden, target)
        loss_torch = head_torch.adapt(hidden, target)
        assert loss_np == pytest.approx(loss_torch, abs=1e-5)

    assert np.allclose(
        np.asarray(head_np.state_dict()["weight"]),
        np.asarray(head_torch.state_dict()["weight"]),
        atol=1e-5,
    )


# ---------------------------------------------------------------------------
# Preservation / revive behaviour
# ---------------------------------------------------------------------------

def test_revive_keeps_soma_reservoir_and_readout():
    m1 = SubstrateForwardModel(
        backend="numpy", feature_dim=8, units=16, seed=777, lr=0.01
    )
    rng = np.random.default_rng(42)
    for _ in range(20):
        m1.step(rng.uniform(0.0, 1.0, size=8).tolist())

    snapshot = {
        "readout": m1.state_dict(),
        "seed": m1.reservoir_seed,
    }

    m1.reset()
    m2 = SubstrateForwardModel(
        backend="numpy", feature_dim=8, units=16, seed=snapshot["seed"], lr=0.01
    )
    m2.load_state_dict(snapshot["readout"])

    for _ in range(30):
        x = rng.uniform(0.0, 1.0, size=8).tolist()
        err1 = m1.step(x)
        err2 = m2.step(x)
        assert err1 == pytest.approx(err2, abs=1e-5)
        assert np.allclose(m1._last_hidden, m2._last_hidden, atol=1e-5)
        assert np.allclose(m1._last_prediction, m2._last_prediction, atol=1e-5)


def test_revive_keeps_chronos_reservoir():
    net1 = CfCNetwork(backend="numpy", input_size=12, units=16, seed=333)
    rng = np.random.default_rng(17)
    for _ in range(15):
        net1.tick(rng.uniform(-1.0, 1.0, size=12).tolist())

    snapshot_seed = net1.reservoir_seed
    net1.reset()
    net2 = CfCNetwork(backend="numpy", input_size=12, units=16, seed=snapshot_seed)

    for _ in range(20):
        x = rng.uniform(-1.0, 1.0, size=12).tolist()
        h1 = net1.tick(x)
        h2 = net2.tick(x)
        assert np.allclose(h1, h2, atol=1e-5)


# ---------------------------------------------------------------------------
# Older snapshots start a new reservoir and log it
# ---------------------------------------------------------------------------

def test_soma_module_logs_new_reservoir_for_old_snapshot(caplog):
    from kaine.modules.soma.module import Soma

    fm = SubstrateForwardModel(backend="numpy", feature_dim=4, units=8, seed=10)
    for _ in range(5):
        fm.step([0.1, 0.2, 0.3, 0.4])

    # Simulate an old snapshot: readout but no reservoir_seed.
    old_state = {"forward_model": fm.state_dict()}

    s = object.__new__(Soma)
    s._forward_model = SubstrateForwardModel(
        backend="numpy", feature_dim=4, units=8, seed=20
    )
    s._cycle_cursor = "0"
    s._read_interval_s = 1.0
    s._fatigue = MagicMock()
    s._self_rhythm = None

    with caplog.at_level(logging.WARNING, logger="kaine.modules.soma.module"):
        s.deserialize(old_state)

    assert "soma: snapshot has no reservoir seed; the reservoir is new" in caplog.text
    # The new model keeps the fresh reservoir it was born with.
    assert s._forward_model.reservoir_seed == 20


def test_soma_module_restore_with_seed_rebuilds_same_reservoir():
    from kaine.modules.soma.module import Soma

    fm1 = SubstrateForwardModel(backend="numpy", feature_dim=4, units=8, seed=10)
    for _ in range(5):
        fm1.step([0.1, 0.2, 0.3, 0.4])

    state = {
        "forward_model": fm1.state_dict(),
        "reservoir_seed": fm1.reservoir_seed,
    }

    s = object.__new__(Soma)
    s._forward_model = SubstrateForwardModel(
        backend="numpy", feature_dim=4, units=8, seed=99
    )
    s._cycle_cursor = "0"
    s._read_interval_s = 1.0
    s._fatigue = MagicMock()
    s._self_rhythm = None

    s.deserialize(state)

    fm1.reset()
    s._forward_model.reset()
    pred1 = fm1.predict([0.5, 0.5, 0.5, 0.5])
    pred2 = s._forward_model.predict([0.5, 0.5, 0.5, 0.5])
    assert pred1 == pytest.approx(pred2, abs=1e-5)


def test_chronos_module_logs_new_reservoir_for_old_snapshot(caplog):
    from kaine.modules.chronos.featurizer import SnapshotFeaturizer
    from kaine.modules.chronos.module import Chronos

    net = CfCNetwork(backend="numpy", input_size=8, units=8, seed=1)
    head = ForwardPredictionHead(
        backend="numpy", input_size=8, units=8, seed=net.reservoir_seed
    )

    c = object.__new__(Chronos)
    c._network = net
    c._pred_head = head
    c._last_interaction_at = None
    c._user_input_cursors = {}
    c._featurizer = SnapshotFeaturizer()

    old_state = {"pred_head": head.state_dict()}

    with caplog.at_level(logging.WARNING, logger="kaine.modules.chronos.module"):
        c.deserialize(old_state)

    assert "chronos: snapshot has no reservoir seed; the reservoir is new" in caplog.text


def test_chronos_module_restore_with_seed_rebuilds_same_reservoir():
    from kaine.modules.chronos.featurizer import SnapshotFeaturizer
    from kaine.modules.chronos.module import Chronos

    net1 = CfCNetwork(backend="numpy", input_size=8, units=8, seed=5)
    head1 = ForwardPredictionHead(
        backend="numpy", input_size=8, units=8, seed=net1.reservoir_seed
    )

    rng = np.random.default_rng(3)
    for _ in range(10):
        h = net1.tick(rng.uniform(-1.0, 1.0, size=8).tolist())
        head1.adapt(h, rng.uniform(-1.0, 1.0, size=8).tolist())

    c = object.__new__(Chronos)
    c._network = CfCNetwork(backend="numpy", input_size=8, units=8, seed=50)
    c._pred_head = ForwardPredictionHead(
        backend="numpy", input_size=8, units=8, seed=c._network.reservoir_seed
    )
    c._last_interaction_at = None
    c._user_input_cursors = {}
    c._featurizer = SnapshotFeaturizer()

    c.deserialize(
        {
            "reservoir_seed": net1.reservoir_seed,
            "pred_head": head1.state_dict(),
        }
    )

    net1.reset()
    c._network.reset()
    c._pred_head.load_state_dict(head1.state_dict())

    for _ in range(15):
        x = rng.uniform(-1.0, 1.0, size=8).tolist()
        h1 = net1.tick(x)
        h2 = c._network.tick(x)
        assert np.allclose(h1, h2, atol=1e-5)


# ---------------------------------------------------------------------------
# numpy backend needs no torch
# ---------------------------------------------------------------------------

def test_numpy_backend_runs_without_torch_in_subprocess():
    code = r"""
import sys

class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "torch" or name.startswith("torch.") or name == "ncps" or name.startswith("ncps."):
            raise ImportError(f"{name} is blocked")
        return None

    def find_module(self, name, path=None):
        return None

sys.meta_path.insert(0, _Blocker())
sys.modules.pop("torch", None)
sys.modules.pop("ncps", None)

from kaine.modules.soma.forward import SubstrateForwardModel
from kaine.modules.chronos.network import CfCNetwork

m = SubstrateForwardModel(backend="numpy", feature_dim=8, units=8, seed=1)
_ = m.predict([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])

n = CfCNetwork(backend="numpy", input_size=8, units=8, seed=1)
_ = n.tick([0.1] * 8)

assert "torch" not in sys.modules
assert "ncps" not in sys.modules
"""

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"numpy-only run failed:\n{result.stdout}\n{result.stderr}")


# ---------------------------------------------------------------------------
# extras check no longer requires core on the numpy backend
# ---------------------------------------------------------------------------

def test_extras_predicates_torch_only_when_backend_is_torch():
    soma_torch = next(
        r for r in REQUIREMENTS["soma"] if r.import_name == "torch"
    )
    soma_ncps = next(
        r for r in REQUIREMENTS["soma"] if r.import_name == "ncps"
    )
    chronos_torch = next(
        r for r in REQUIREMENTS["chronos"] if r.import_name == "torch"
    )
    chronos_ncps = next(
        r for r in REQUIREMENTS["chronos"] if r.import_name == "ncps"
    )

    assert not soma_torch.applies({"soma": {"cfc_backend": "numpy"}})
    assert soma_torch.applies({"soma": {"cfc_backend": "torch"}})
    assert not soma_ncps.applies({"soma": {"cfc_backend": "numpy"}})
    assert soma_ncps.applies({"soma": {"cfc_backend": "torch"}})

    assert not chronos_torch.applies({"chronos": {"cfc_backend": "numpy"}})
    assert chronos_torch.applies({"chronos": {"cfc_backend": "torch"}})
    assert not chronos_ncps.applies({"chronos": {"cfc_backend": "numpy"}})
    assert chronos_ncps.applies({"chronos": {"cfc_backend": "torch"}})


async def test_chronos_keeps_the_preserved_seed_when_restored_before_initialize():
    # A revive may restore state before the lazily built network exists; the
    # network built afterwards must still be the preserved reservoir.
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.chronos.module import Chronos

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    preserved = Chronos(bus)
    await preserved.initialize()
    seed = preserved.serialize()["reservoir_seed"]

    revived = Chronos(bus)
    revived.deserialize({"reservoir_seed": seed})
    await revived.initialize()
    assert revived._network.reservoir_seed == seed

    x = [0.1] * revived._featurizer.feature_dim
    preserved._network.reset()
    revived._network.reset()
    assert np.allclose(preserved._network.tick(x), revived._network.tick(x), atol=1e-6)
    await preserved.shutdown()
    await revived.shutdown()
    await bus.close()


def test_seeded_experiment_reproduces_unseeded_reservoirs():
    set_global_seed(99)
    soma1 = SubstrateForwardModel()
    net1 = CfCNetwork(input_size=8, units=16)
    head1 = ForwardPredictionHead(input_size=8, units=16)

    soma_seed1 = soma1.reservoir_seed
    net_seed1 = net1.reservoir_seed
    head_pred1 = head1.predict([0.1] * 16)

    set_global_seed(99)
    soma2 = SubstrateForwardModel()
    net2 = CfCNetwork(input_size=8, units=16)
    head2 = ForwardPredictionHead(input_size=8, units=16)

    soma_seed2 = soma2.reservoir_seed
    net_seed2 = net2.reservoir_seed
    head_pred2 = head2.predict([0.1] * 16)

    assert soma_seed1 == soma_seed2
    assert net_seed1 == net_seed2
    assert head_pred1 == pytest.approx(head_pred2, abs=1e-5)


def test_unseeded_draws_differ():
    a = draw_reservoir_seed()
    b = draw_reservoir_seed()
    assert a != b
    assert 0 <= a < 2**63 - 1
    assert 0 <= b < 2**63 - 1


# ---------------------------------------------------------------------------
# Hardened NumPy CfC readout and Soma seed restore
# ---------------------------------------------------------------------------

def test_numpy_readout_load_state_dict_rejects_invalid_and_leaves_state():
    readout = NumpyReadout(units=8, out=4, rng=np.random.default_rng(1))
    good_state = readout.state_dict()
    before_w = readout.W.copy()
    before_b = readout.b.copy()
    before_out = readout.out
    before_units = readout.units

    bad_weight = {"weight": [[0.0] * 8] * 8, "bias": good_state["bias"]}
    with pytest.raises(ValueError, match="expected weight shape"):
        readout.load_state_dict(bad_weight)
    assert np.array_equal(readout.W, before_w)
    assert np.array_equal(readout.b, before_b)
    assert readout.out == before_out
    assert readout.units == before_units

    bad_bias = {"weight": good_state["weight"], "bias": [0.0] * 8}
    with pytest.raises(ValueError, match="expected bias shape"):
        readout.load_state_dict(bad_bias)
    assert np.array_equal(readout.W, before_w)
    assert np.array_equal(readout.b, before_b)
    assert readout.out == before_out
    assert readout.units == before_units

    nan_weight = np.array(good_state["weight"], dtype=np.float32)
    nan_weight[0, 0] = float("nan")
    bad_finite = {"weight": nan_weight.tolist(), "bias": good_state["bias"]}
    with pytest.raises(ValueError, match="finite"):
        readout.load_state_dict(bad_finite)
    assert np.array_equal(readout.W, before_w)
    assert np.array_equal(readout.b, before_b)
    assert readout.out == before_out
    assert readout.units == before_units


def test_numpy_readout_from_arrays_rejects_invalid():
    w = np.zeros((4, 8), dtype=np.float32)
    b = np.zeros(4, dtype=np.float32)
    with pytest.raises(ValueError, match="2-D"):
        NumpyReadout.from_arrays(w.flatten(), b)
    with pytest.raises(ValueError, match="bias"):
        NumpyReadout.from_arrays(w, np.zeros(8, dtype=np.float32))


def test_soma_load_state_dict_wrong_width_raises_and_module_recover():
    fm64 = SubstrateForwardModel(backend="numpy", feature_dim=8, units=64, seed=1)
    fm32 = SubstrateForwardModel(backend="numpy", feature_dim=8, units=32, seed=2)

    with pytest.raises(ValueError):
        fm32.load_state_dict(fm64.state_dict())

    s = object.__new__(Soma)
    s._forward_model = fm32
    s._cycle_cursor = "0"
    s._read_interval_s = 1.0
    s._fatigue = MagicMock()
    s._self_rhythm = None

    s.deserialize({"forward_model": fm64.state_dict()})
    result = s._forward_model.step([0.1] * 8)
    assert math.isfinite(result)


def test_chronos_head_load_state_dict_wrong_width_raises():
    head64 = ForwardPredictionHead(backend="numpy", input_size=8, units=64, seed=1)
    head32 = ForwardPredictionHead(backend="numpy", input_size=8, units=32, seed=2)
    with pytest.raises(ValueError):
        head32.load_state_dict(head64.state_dict())


def test_numpy_readout_sgd_step_nonfinite_returns_nan_and_model_logs(caplog):
    readout = NumpyReadout(units=8, out=4, rng=np.random.default_rng(3))
    hidden = [0.1] * 8
    target = [0.5, -0.2, 0.1, float("inf")]
    before_w = readout.W.copy()
    before_b = readout.b.copy()
    loss = readout.sgd_step(hidden, target, lr=0.1)
    assert math.isnan(loss)
    assert np.array_equal(readout.W, before_w)
    assert np.array_equal(readout.b, before_b)

    model = SubstrateForwardModel(backend="numpy", feature_dim=8, units=8, seed=4)
    model._last_hidden = [float("inf")] * model.units
    with caplog.at_level(logging.WARNING, logger="kaine.modules.soma.forward"):
        result = model.step([0.1] * 8)
    assert math.isfinite(result)
    assert "non-finite" in caplog.text


def test_soma_serialize_omits_none_seed_and_deserialize_none(caplog):
    s = object.__new__(Soma)
    s._forward_model = MagicMock(spec=["state_dict"])
    s._forward_model.state_dict.return_value = {"weight": [], "bias": []}
    s._cycle_cursor = "0"
    s._read_interval_s = 1.0
    s._fatigue = MagicMock()
    s._expected_error = ExpectedErrorModel()
    s._self_rhythm = None
    s._feature_layout = 2

    state = s.serialize()
    assert "reservoir_seed" not in state
    assert state["forward_model"] == {"weight": [], "bias": []}

    s2 = object.__new__(Soma)
    s2._forward_model = SubstrateForwardModel(
        backend="numpy", feature_dim=4, units=8, seed=5
    )
    s2._cycle_cursor = "0"
    s2._read_interval_s = 1.0
    s2._fatigue = MagicMock()
    s2._expected_error = ExpectedErrorModel()
    s2._self_rhythm = None

    with caplog.at_level(logging.WARNING, logger="kaine.modules.soma.module"):
        s2.deserialize({"reservoir_seed": None})

    assert "soma: snapshot has no reservoir seed; the reservoir is new" in caplog.text
    s2._forward_model.step([0.1, 0.2, 0.3, 0.4])
