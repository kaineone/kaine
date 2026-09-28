# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Record golden fixtures from the JAX RSSM world model for the NumPy engine.

This script runs only where ``jax`` is installed. It records compressed NumPy
fixtures under ``tests/fixtures/phantasia_golden/`` from a fixed set of
``external.dreamerv3.rssm.RSSMConfig`` cases covering both categorical and
Gaussian latents, trivial and non-trivial sequence lengths, free bits active
and inactive, and a shipped-sized configuration.

For each case the fixture contains:

1. The fixed observation sequence, perturbed initial parameters, and the
   sequence loss / gradients from ``jax.value_and_grad(sequence_loss)``.
2. A deterministic filtering trace: prior predictions, and the ``deter``/``stoch``
   states after each ``observe_step`` (``key=None``).
3. Four deterministic imagination steps decoded from the final filtered state.
4. Five consecutive ``sgd_update`` training steps and the resulting parameters.

Re-recording is a deliberate operator step. Run as::

    python scripts/record_phantasia_golden.py [--out DIR]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import jax
import jax.numpy as jnp
import numpy as np

from external.dreamerv3 import rssm
from kaine.modules.phantasia.encoder import observation_dim

CASES: list[dict[str, Any]] = [
    {
        "name": "cat_small_t1",
        "obs_dim": 5,
        "deter_dim": 8,
        "stoch_dim": 4,
        "stoch_classes": 3,
        "hidden_dim": 8,
        "latent_kind": "categorical",
        "kl_free_bits": 0.0,
        "T": 1,
        "seed": 1,
    },
    {
        "name": "cat_small_t16",
        "obs_dim": 5,
        "deter_dim": 8,
        "stoch_dim": 4,
        "stoch_classes": 3,
        "hidden_dim": 8,
        "latent_kind": "categorical",
        "kl_free_bits": 0.0,
        "T": 16,
        "seed": 2,
    },
    {
        "name": "cat_small_freebits",
        "obs_dim": 5,
        "deter_dim": 8,
        "stoch_dim": 4,
        "stoch_classes": 3,
        "hidden_dim": 8,
        "latent_kind": "categorical",
        "kl_free_bits": 1000.0,
        "T": 16,
        "seed": 3,
    },
    {
        "name": "gauss_small_t16",
        "obs_dim": 5,
        "deter_dim": 8,
        "stoch_dim": 4,
        "stoch_classes": 3,
        "hidden_dim": 8,
        "latent_kind": "gaussian",
        "kl_free_bits": 0.0,
        "T": 16,
        "seed": 4,
    },
    {
        "name": "gauss_small_freebits",
        "obs_dim": 5,
        "deter_dim": 8,
        "stoch_dim": 4,
        "stoch_classes": 3,
        "hidden_dim": 8,
        "latent_kind": "gaussian",
        "kl_free_bits": 1000.0,
        "T": 16,
        "seed": 5,
    },
    {
        "name": "cat_shipped",
        "obs_dim": None,  # filled in below from observation_dim()
        "deter_dim": 64,
        "stoch_dim": 16,
        "stoch_classes": 8,
        "hidden_dim": 64,
        "latent_kind": "categorical",
        "kl_free_bits": 0.1,
        "T": 32,
        "seed": 6,
    },
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record JAX Phantasia RSSM golden fixtures for the NumPy engine."
    )
    parser.add_argument(
        "--out",
        default="tests/fixtures/phantasia_golden",
        help="Directory to write the compressed NPZ fixtures (default: tests/fixtures/phantasia_golden).",
    )
    return parser.parse_args()


def _perturb_params(
    params: dict[str, Any], seed: int, scale: float = 0.3
) -> dict[str, Any]:
    """Add ``scale * N(0,1)`` noise to every bias in fixed lexicographic order."""
    rng = np.random.default_rng(seed)
    new_params: dict[str, Any] = {}
    for group in sorted(params.keys()):
        sub = params[group]
        new_sub: dict[str, Any] = {}
        for name in sorted(sub.keys()):
            arr = sub[name]
            if name == "b":
                noise = jnp.asarray(
                    rng.normal(size=arr.shape).astype(np.float32) * scale
                )
                new_sub[name] = jnp.asarray(arr + noise, dtype=jnp.float32)
            else:
                new_sub[name] = arr
        new_params[group] = new_sub
    return new_params


def _flatten_params(params: dict[str, Any], prefix: str) -> dict[str, np.ndarray]:
    """Flatten a 2-level parameter dict into ``prefix/group/name`` arrays."""
    flat: dict[str, np.ndarray] = {}
    for group in sorted(params.keys()):
        sub = params[group]
        for name in sorted(sub.keys()):
            flat[f"{prefix}/{group}/{name}"] = np.asarray(sub[name], dtype=np.float32)
    return flat


def _make_header(case: dict[str, Any], cfg: rssm.RSSMConfig) -> np.ndarray:
    header = {
        "format": "kaine-phantasia-golden-v1",
        "case": case["name"],
        "config": dataclasses.asdict(cfg),
        "T": case["T"],
        "seed": case["seed"],
        "jax_version": jax.__version__,
    }
    return np.asarray(json.dumps(header, sort_keys=True))


def _assert_all_finite(arrays: dict[str, np.ndarray], case_name: str) -> None:
    for key, arr in arrays.items():
        if arr.dtype.kind in "iub":  # integers/unsigned/boolean are discrete
            continue
        if not np.all(np.isfinite(arr)):
            print(
                f"record_phantasia_golden: case {case_name}: non-finite values in {key}",
                file=sys.stderr,
            )
            sys.exit(1)


def _record_case(out_dir: Path, case: dict[str, Any]) -> None:
    name = case["name"]
    cfg = rssm.RSSMConfig(
        obs_dim=case["obs_dim"],
        deter_dim=case["deter_dim"],
        stoch_dim=case["stoch_dim"],
        stoch_classes=case["stoch_classes"],
        hidden_dim=case["hidden_dim"],
        latent_kind=case["latent_kind"],
        learning_rate=1e-3,
        kl_balance=0.8,
        kl_free_bits=case["kl_free_bits"],
        kl_scale=1.0,
    )

    # 1. Parameters with perturbed biases.
    params = rssm.init_params(cfg, seed=case["seed"])
    params = _perturb_params(params, seed=case["seed"] + 1000)

    # 2. Fixed observation sequence.
    rng = np.random.default_rng(case["seed"])
    obs = rng.uniform(0.0, 1.0, size=(case["T"], cfg.obs_dim)).astype(np.float32)

    # 3. Loss and gradients.
    loss, grads = jax.value_and_grad(
        lambda p: rssm.sequence_loss(cfg, p, jnp.asarray(obs))
    )(params)

    # 4. Deterministic filtering trace.
    state = rssm.initial_state(cfg)
    preds: list[np.ndarray] = []
    deters: list[np.ndarray] = []
    stochs: list[np.ndarray] = []
    for t in range(case["T"]):
        pred_t = rssm.predict_next_obs(cfg, params, state)
        preds.append(np.asarray(pred_t, dtype=np.float32))
        state = rssm.observe_step(
            cfg, params, state, jnp.asarray(obs[t]), key=None
        )
        deters.append(np.asarray(state.deter, dtype=np.float32))
        stochs.append(np.asarray(state.stoch, dtype=np.float32))

    pred = np.stack(preds, axis=0) if preds else np.zeros((0, cfg.obs_dim), dtype=np.float32)
    deter = np.stack(deters, axis=0) if deters else np.zeros((0, cfg.deter_dim), dtype=np.float32)
    stoch = np.stack(stochs, axis=0) if stochs else np.zeros((0, cfg.stoch_flat), dtype=np.float32)

    # 5. Deterministic imagination from the final filtered state.
    imagine_steps = 4
    imagine_preds: list[np.ndarray] = []
    imagine_state = state
    for _ in range(imagine_steps):
        imagine_state = rssm.imagine_step(cfg, params, imagine_state, key=None)
        feature = imagine_state.feature()
        dec = rssm._decode(params, feature)
        imagine_preds.append(np.asarray(dec, dtype=np.float32))
    imagine_det = np.stack(imagine_preds, axis=0)

    # 6. Training trajectory: five consecutive SGD updates from perturbed params.
    train_losses: list[float] = []
    train_aborted: list[float] = []
    current_params = params
    for _ in range(5):
        result = rssm.sgd_update(
            cfg, current_params, jnp.asarray(obs), steps=1
        )
        train_losses.append(np.float32(result.loss))
        train_aborted.append(np.float32(1.0 if result.aborted else 0.0))
        if result.aborted:
            break
        current_params = result.params

    if any(train_aborted):
        print(
            f"record_phantasia_golden: case {name}: training aborted unexpectedly",
            file=sys.stderr,
        )
        sys.exit(1)

    arrays: dict[str, np.ndarray] = {
        "obs": obs,
        "loss": np.asarray(loss, dtype=np.float32),
        "pred": pred,
        "deter": deter,
        "stoch": stoch,
        "imagine_det": imagine_det,
        "train_loss": np.asarray(train_losses, dtype=np.float32),
        "train_aborted": np.asarray(train_aborted, dtype=np.float32),
    }
    arrays.update(_flatten_params(params, "params"))
    arrays.update(_flatten_params(grads, "grads"))
    arrays.update(_flatten_params(current_params, "trained"))

    _assert_all_finite(arrays, name)

    arrays["__header__"] = _make_header(case, cfg)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.npz"
    np.savez_compressed(out_path, **arrays)

    size_kb = out_path.stat().st_size / 1024.0
    print(f"{name}: loss={float(loss):.6f}, size={size_kb:.1f} KB")


def main() -> None:
    args = _parse_args()
    out_dir = Path(args.out)

    # Fill in the shipped observation dimension now that imports are available.
    shipped_obs_dim = observation_dim()
    for case in CASES:
        if case["obs_dim"] is None:
            case["obs_dim"] = shipped_obs_dim

    for case in CASES:
        _record_case(out_dir, case)


if __name__ == "__main__":
    main()
