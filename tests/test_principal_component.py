# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kaine.experiment.principal_component import (
    PrincipalComponent,
    PrincipalComponentError,
    PrincipalComponentEstimator,
    canonical_bytes,
    file_sha256,
    load_principal_component,
    principal_component_path,
    write_principal_component,
)


def _make_planted_pc(n: int, seed: int) -> PrincipalComponent:
    rng = np.random.default_rng(seed)
    dim = 6
    mean = np.array([0.5, -0.2, 0.1, 0.0, 0.3, -0.1])
    raw = np.array([1.0, 2.0, 0.0, -1.0, 0.5, 0.0])
    v = raw / np.linalg.norm(raw)
    z1 = rng.standard_normal(size=n)
    noise = rng.standard_normal(size=(n, dim))
    samples = mean[None, :] + 3.0 * z1[:, None] * v[None, :] + 0.3 * noise
    estimator = PrincipalComponentEstimator()
    for x in samples:
        estimator.add(x.tolist())
    return estimator.result(processor="topos", run_id="runA"), v, mean


def test_estimator_recovers_planted_direction() -> None:
    pc, v, mean = _make_planted_pc(5000, 11)
    dot = sum(d * vi for d, vi in zip(pc.direction, v))
    assert abs(dot) > 0.999
    assert np.allclose(np.array(pc.mean), mean, atol=0.05)
    assert pc.variance == pytest.approx(9.0 + 0.09, rel=0.1)


def test_estimator_sign_convention() -> None:
    pc, _, _ = _make_planted_pc(5000, 11)
    max_idx = max(range(pc.dim), key=lambda i: abs(pc.direction[i]))
    assert pc.direction[max_idx] > 0.0


def test_estimator_matches_numpy_covariance() -> None:
    rng = np.random.default_rng(13)
    dim = 4
    n = 200
    samples = rng.standard_normal(size=(n, dim))
    estimator = PrincipalComponentEstimator()
    for x in samples:
        estimator.add(x.tolist())
    pc = estimator.result(processor="topos", run_id="runB")
    cov = np.cov(samples, rowvar=False)
    eigvals = np.linalg.eigvalsh(cov)
    assert pc.variance == pytest.approx(float(np.max(eigvals)), rel=1e-9)
    assert pc.total_variance == pytest.approx(float(np.trace(cov)), rel=1e-9)


def test_estimator_errors() -> None:
    empty = PrincipalComponentEstimator()
    with pytest.raises(PrincipalComponentError):
        empty.result(processor="p", run_id="r")
    est = PrincipalComponentEstimator()
    est.add([1.0, 2.0, 3.0])
    with pytest.raises(PrincipalComponentError):
        est.add([1.0, 2.0])
    with pytest.raises(PrincipalComponentError):
        est.add([1.0, 2.0, float("nan")])
    const = PrincipalComponentEstimator()
    for _ in range(5):
        const.add([1.0, 1.0, 1.0, 1.0])
    with pytest.raises(PrincipalComponentError):
        const.result(processor="p", run_id="r")


def test_project() -> None:
    pc = PrincipalComponent(
        processor="p",
        run_id="r",
        n_inputs=2,
        dim=3,
        mean=(1.0, 0.0, -1.0),
        direction=(0.0, 1.0, 0.0),
        variance=1.0,
        total_variance=1.0,
    )
    assert pc.project([1.0, 5.0, 2.0]) == pytest.approx(5.0)
    with pytest.raises(PrincipalComponentError):
        pc.project([1.0, 5.0])


def test_write_load_round_trip(tmp_path: Path) -> None:
    pc = PrincipalComponent(
        processor="topos",
        run_id="run1",
        n_inputs=3,
        dim=2,
        mean=(0.0, 0.0),
        direction=(1.0, 0.0),
        variance=2.0,
        total_variance=2.5,
    )
    path = tmp_path / "pc.json"
    sha = write_principal_component(pc, path)
    assert sha == file_sha256(path)
    loaded = load_principal_component(path, expected_sha256=sha)
    assert loaded == pc
    with pytest.raises(PrincipalComponentError, match="sha256 mismatch"):
        load_principal_component(path, expected_sha256="0" * 64)
    bad = pc.to_payload()
    bad["direction"] = [0.6, 0.6]
    path2 = tmp_path / "bad.json"
    path2.write_bytes(canonical_bytes(bad))
    with pytest.raises(PrincipalComponentError, match="direction"):
        load_principal_component(path2)
    other = pc.to_payload()
    other["schema"] = "other"
    path3 = tmp_path / "other.json"
    path3.write_bytes(canonical_bytes(other))
    with pytest.raises(PrincipalComponentError, match="schema"):
        load_principal_component(path3)


def test_principal_component_path() -> None:
    processor = "topos"
    with pytest.raises(PrincipalComponentError):
        principal_component_path(Path("x"), "../x", processor)
    with pytest.raises(PrincipalComponentError):
        principal_component_path(Path("x"), "a/b", processor)
    assert principal_component_path(Path("x"), "run1", processor) == Path(
        f"x/run1/principal_component_{processor}.json"
    )
