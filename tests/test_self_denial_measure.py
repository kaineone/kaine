import importlib.util
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "self_denial_measure", REPO / "scripts" / "self_denial_measure.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fake_sums_and_counts():
    num_layers = 3
    dim = 4
    deny_count = 5
    other_count = 7
    deny_sums = [
        torch.full((dim,), float((layer + 1) * deny_count), dtype=torch.float64)
        for layer in range(num_layers)
    ]
    other_sums = [
        torch.full((dim,), float((layer + 10) * other_count), dtype=torch.float64)
        for layer in range(num_layers)
    ]
    sums = {"deny": deny_sums, "other": other_sums}
    counts = {"deny": deny_count, "other": other_count}
    return sums, counts, num_layers, dim


def test_build_results_keys_shapes_means_and_refusenorm():
    sums, counts, num_layers, dim = _fake_sums_and_counts()
    results = MODULE.build_results(
        sums, counts, num_layers, torch.float32, min_per_group=1
    )

    assert results["layers"] == num_layers
    assert results["counts"] == {"deny": 5, "other": 7}

    for layer in range(num_layers):
        assert results[f"harmful_{layer}"].shape == (dim,)
        assert results[f"harmless_{layer}"].shape == (dim,)
        assert results[f"refuse_{layer}"].shape == (dim,)
        assert results[f"refusenorm_{layer}"].shape == (dim,)
        assert results[f"harmful_{layer}"].dtype == torch.float32

        expected_deny_mean = float(layer + 1)
        expected_other_mean = float(layer + 10)
        expected_refuse = expected_deny_mean - expected_other_mean

        assert torch.allclose(
            results[f"harmful_{layer}"],
            torch.full((dim,), expected_deny_mean),
        )
        assert torch.allclose(
            results[f"harmless_{layer}"],
            torch.full((dim,), expected_other_mean),
        )
        assert torch.allclose(
            results[f"refuse_{layer}"],
            torch.full((dim,), expected_refuse),
        )
        assert torch.allclose(
            results[f"refusenorm_{layer}"].norm(),
            torch.tensor(1.0),
            atol=1e-5,
        )


def test_build_results_raises_when_below_min_per_group():
    sums, counts, num_layers, _ = _fake_sums_and_counts()
    with pytest.raises(ValueError):
        MODULE.build_results(
            sums, counts, num_layers, torch.float32, min_per_group=10
        )
