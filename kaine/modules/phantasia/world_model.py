# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""World-model protocol + a zero-dep fake + the real DreamerV3 adapter.

`WorldModel` is the thin contract Phantasia depends on:

  * ``observe(obs)``  — fold one observation into the recurrent state, returning
    the world-prediction error (||predicted - actual|| of the latent) as a
    scalar in [0, 1]. Cheap; the waking-tick path.
  * ``imagine(horizon)`` — roll out ``horizon`` imagined observation steps from
    the current state; returns a list of observation vectors (the offline
    scenario path).
  * ``train(trajectory)`` — in-memory training pass over a batch of observation
    sequences; returns a :class:`TrainOutcome`. NaN/Inf-guarded: an aborted pass
    NEVER corrupts in-memory state.

`FakeWorldModel` satisfies the protocol with pure Python (no JAX, no vendored
code) and is used by ALL tests, keeping the suite green without the
``[worldmodel]`` extra.

`DreamerV3WorldModel` wraps the vendored RSSM core (``external/dreamerv3``). It
is imported ONLY when the ``dreamerv3`` backend is selected via
:func:`load_world_model`; that import fails gracefully with a clear message when
JAX / the extra is absent, and never breaks ``import``-ing this module.

WORLD MODEL ONLY: neither implementation has an actor, critic, reward head, or
return head. Nous owns action selection. ``parameter_names()`` exposes the param
tree's top-level names so tests can assert no actor/critic tensors exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TrainOutcome:
    """Result of one in-memory training pass."""

    loss: float
    steps: int
    aborted: bool = False
    reason: str = ""


class CheckpointMismatchError(RuntimeError):
    """A weight checkpoint does not match the running world-model config.

    Raised by :meth:`DreamerV3WorldModel.import_params` (and propagated by
    Phantasia at initialize) instead of silently discarding the checkpoint —
    throwing away learned weights without operator consent would destroy
    entity experience. The operator resolves it by moving/deleting the file
    or reverting the config change that caused the mismatch."""


@runtime_checkable
class WorldModel(Protocol):
    """The contract Phantasia depends on. Implementations hold all state
    in-memory and write NOTHING to disk.

    Optional capability (not part of the protocol): implementations with
    *real learned parameters* may additionally provide
    ``export_params(*, extra=None) -> bytes`` / ``import_params(blob, *,
    extra=None)`` so Phantasia can persist learned weights across restarts
    (opt-in via ``persist_weights``). ``FakeWorldModel`` deliberately does
    NOT implement it — persisting the EMA stub would dress a fake up as
    learned state."""

    obs_dim: int

    def observe(self, obs: list[float]) -> float:
        """Fold one observation in; return world-prediction error in [0, 1]."""
        ...

    def imagine(self, horizon: int) -> list[list[float]]:
        """Roll out `horizon` imagined observation vectors from current state."""
        ...

    def train(self, trajectory: list[list[float]]) -> TrainOutcome:
        """In-memory training pass over a single observation sequence."""
        ...

    def reset_state(self) -> None:
        """Reset the recurrent state (e.g. before seeding an imagined rollout)."""
        ...

    def parameter_names(self) -> list[str]:
        """Top-level parameter-group names (for actor/critic-absence checks)."""
        ...


# ---------------------------------------------------------------------------
# FakeWorldModel — zero-dependency stub used by ALL tests
# ---------------------------------------------------------------------------


class FakeWorldModel:
    """Deterministic, dependency-free WorldModel for tests and CI.

    Models the recurrent state as a simple exponential moving average of the
    observation. Prediction = the running average; world error = mean absolute
    difference between the new observation and that prediction, clipped to
    [0, 1]. Training nudges the EMA decay toward a target and is NaN-guarded.

    No JAX, no vendored code, no disk I/O. There is deliberately NO actor or
    critic anywhere in this object.
    """

    def __init__(self, obs_dim: int, *, decay: float = 0.5) -> None:
        if obs_dim <= 0:
            raise ValueError("obs_dim must be positive")
        self.obs_dim = int(obs_dim)
        self._decay = float(decay)
        # In-memory "parameters" — a single EMA decay weight. No actor/critic.
        self._state: list[float] = [0.0] * self.obs_dim
        self._seen = False

    # -- contract -------------------------------------------------------

    def observe(self, obs: list[float]) -> float:
        obs = self._coerce(obs)
        if not self._seen:
            # First observation: no prediction yet → zero error, seed state.
            self._state = list(obs)
            self._seen = True
            return 0.0
        prediction = list(self._state)
        err = sum(abs(p - o) for p, o in zip(prediction, obs)) / self.obs_dim
        # Advance state (EMA filter).
        self._state = [
            self._decay * o + (1.0 - self._decay) * p
            for p, o in zip(prediction, obs)
        ]
        return _clip01(err)

    def imagine(self, horizon: int) -> list[list[float]]:
        # Prior-only "dreaming": the fake repeats its current latent estimate
        # with a small deterministic decay so the rollout has the right shape.
        out: list[list[float]] = []
        cur = list(self._state)
        for _ in range(max(0, int(horizon))):
            cur = [v * 0.9 for v in cur]
            out.append(list(cur))
        return out

    def train(self, trajectory: list[list[float]]) -> TrainOutcome:
        if not trajectory:
            return TrainOutcome(loss=0.0, steps=0)
        snapshot_decay = self._decay  # last known-good
        total = 0.0
        n = 0
        for row in trajectory:
            row = self._coerce(row)
            if any(_isnan(v) for v in row):
                # Abort WITHOUT corrupting in-memory state (restore decay).
                self._decay = snapshot_decay
                return TrainOutcome(
                    loss=float("nan"), steps=n, aborted=True, reason="non-finite input"
                )
            total += sum(v * v for v in row) / self.obs_dim
            n += 1
        loss = total / max(1, n)
        if _isnan(loss):
            self._decay = snapshot_decay
            return TrainOutcome(loss=float("nan"), steps=n, aborted=True, reason="non-finite loss")
        # "Learning": nudge decay toward 0.5 (a no-op-ish stable point).
        self._decay = snapshot_decay + 0.01 * (0.5 - snapshot_decay)
        return TrainOutcome(loss=float(loss), steps=n, aborted=False)

    def reset_state(self) -> None:
        self._state = [0.0] * self.obs_dim
        self._seen = False

    def parameter_names(self) -> list[str]:
        # World-model-only: a single decay weight. No actor/critic/return heads.
        return ["ema_decay"]

    # -- helpers --------------------------------------------------------

    def _coerce(self, obs: list[float]) -> list[float]:
        vals = [float(v) for v in obs]
        if len(vals) != self.obs_dim:
            raise ValueError(
                f"observation has length {len(vals)}, expected {self.obs_dim}"
            )
        return vals


def _clip01(x: float) -> float:
    if _isnan(x):
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _isnan(x: float) -> bool:
    return x != x


# ---------------------------------------------------------------------------
# DreamerV3WorldModel — real adapter over the vendored RSSM (extra-gated)
# ---------------------------------------------------------------------------


class DreamerV3WorldModel:
    """Real WorldModel backed by the vendored DreamerV3 RSSM core.

    Imported only by :func:`load_world_model` when backend="dreamerv3". Requires
    JAX (the ``[worldmodel]`` extra); construction raises a clear ImportError
    otherwise. Holds all parameters and recurrent state in memory and writes
    NOTHING to disk — the upstream checkpoint/replay-flush hooks are not wired.
    """

    def __init__(
        self,
        obs_dim: int,
        *,
        deter_dim: int = 64,
        stoch_dim: int = 16,
        stoch_classes: int = 8,
        hidden_dim: int = 64,
        latent_kind: str = "categorical",
        learning_rate: float = 1e-3,
        kl_balance: float = 0.8,
        kl_free_bits: float = 0.1,
        kl_scale: float = 1.0,
        seed: int = 0,
    ) -> None:
        try:
            from external.dreamerv3 import rssm as _rssm
        except ImportError as exc:  # pragma: no cover - covered by missing-extra path
            raise ImportError(
                "Phantasia backend 'dreamerv3' requires the [worldmodel] extra "
                "(jax). Install it with: pip install '.[worldmodel]' — or set "
                "[phantasia].backend = \"fake\"."
            ) from exc

        self._rssm = _rssm
        self.obs_dim = int(obs_dim)
        self._cfg = _rssm.RSSMConfig(
            obs_dim=self.obs_dim,
            deter_dim=deter_dim,
            stoch_dim=stoch_dim,
            stoch_classes=stoch_classes,
            hidden_dim=hidden_dim,
            latent_kind=latent_kind,
            learning_rate=learning_rate,
            kl_balance=kl_balance,
            kl_free_bits=kl_free_bits,
            kl_scale=kl_scale,
        )
        self._params = _rssm.init_params(self._cfg, seed=seed)
        self._state = _rssm.initial_state(self._cfg)

    def observe(self, obs: list[float]) -> float:
        import jax.numpy as jnp

        arr = jnp.asarray(obs, dtype=jnp.float32)
        predicted = self._rssm.predict_next_obs(self._cfg, self._params, self._state)
        self._state = self._rssm.observe_step(self._cfg, self._params, self._state, arr)
        err = float(jnp.mean(jnp.abs(predicted - arr)))
        return _clip01(err)

    def imagine(self, horizon: int) -> list[list[float]]:
        outs = self._rssm.rollout(self._cfg, self._params, self._state, int(horizon))
        return [[float(v) for v in row] for row in outs]

    def train(self, trajectory: list[list[float]]) -> TrainOutcome:
        import jax.numpy as jnp

        if not trajectory:
            return TrainOutcome(loss=0.0, steps=0)
        seq = jnp.asarray(trajectory, dtype=jnp.float32)
        result = self._rssm.sgd_update(self._cfg, self._params, seq, steps=1)
        if result.aborted:
            # last-known-good params returned; do NOT install corrupted weights.
            return TrainOutcome(
                loss=result.loss, steps=0, aborted=True, reason=result.reason
            )
        self._params = result.params
        return TrainOutcome(loss=float(result.loss), steps=1, aborted=False)

    def reset_state(self) -> None:
        self._state = self._rssm.initial_state(self._cfg)

    def parameter_names(self) -> list[str]:
        # Top-level param groups — all world-model (encoder/gru/prior/post/dec).
        # No actor/critic/reward/return groups exist in the tree.
        return sorted(self._params.keys())

    # -- weight persistence codec (opt-in via Phantasia persist_weights) ---

    _CHECKPOINT_FORMAT = "kaine-phantasia-rssm-npz-v1"

    def _config_header(self, extra: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "format": self._CHECKPOINT_FORMAT,
            "obs_dim": int(self._cfg.obs_dim),
            "deter_dim": int(self._cfg.deter_dim),
            "stoch_dim": int(self._cfg.stoch_dim),
            "stoch_classes": int(self._cfg.stoch_classes),
            "hidden_dim": int(self._cfg.hidden_dim),
            "latent_kind": str(self._cfg.latent_kind),
            "extra": {k: extra[k] for k in sorted(extra)} if extra else {},
        }

    def export_params(self, *, extra: dict[str, Any] | None = None) -> bytes:
        """Serialize the RSSM param tree to opaque bytes (in-memory NPZ).

        The blob embeds a JSON config header (RSSM dims, latent kind, plus
        caller-supplied ``extra`` such as the encoder version) that
        :meth:`import_params` validates before installing anything. Contains
        ONLY learned world-model parameters — never observations, the
        trajectory buffer, or anything raw-sense-derived.
        """
        import io
        import json

        import numpy as np

        arrays: dict[str, Any] = {
            f"{group}/{name}": np.asarray(arr)
            for group, sub in self._params.items()
            for name, arr in sub.items()
        }
        header = json.dumps(self._config_header(extra), sort_keys=True)
        buf = io.BytesIO()
        # 0-d unicode array: loads without allow_pickle.
        np.savez(buf, __header__=np.asarray(header), **arrays)
        return buf.getvalue()

    def import_params(self, blob: bytes, *, extra: dict[str, Any] | None = None) -> None:
        """Install previously exported parameters, failing closed on mismatch.

        Every header field and every array shape is validated against the
        running config BEFORE anything is installed; any difference raises
        :class:`CheckpointMismatchError` and leaves the model untouched.
        The recurrent state is reset (it belonged to the prior weights).
        """
        import io
        import json

        import jax.numpy as jnp
        import numpy as np

        try:
            data = np.load(io.BytesIO(blob), allow_pickle=False)
            header = json.loads(str(data["__header__"][()]))
        except Exception as exc:
            raise CheckpointMismatchError(
                f"checkpoint is not a readable {self._CHECKPOINT_FORMAT} blob: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        expected = self._config_header(extra)
        mismatches = [
            f"{key}: checkpoint={header.get(key)!r} running={expected[key]!r}"
            for key in expected
            if header.get(key) != expected[key]
        ]
        if mismatches:
            raise CheckpointMismatchError(
                "checkpoint config does not match the running world model: "
                + "; ".join(mismatches)
            )

        new_params: dict[str, Any] = {}
        for group, sub in self._params.items():
            new_params[group] = {}
            for name, cur in sub.items():
                key = f"{group}/{name}"
                if key not in data:
                    raise CheckpointMismatchError(f"checkpoint is missing array {key!r}")
                arr = data[key]
                if tuple(arr.shape) != tuple(cur.shape):
                    raise CheckpointMismatchError(
                        f"array {key!r} has shape {tuple(arr.shape)}, "
                        f"expected {tuple(cur.shape)}"
                    )
                new_params[group][name] = jnp.asarray(arr, dtype=jnp.float32)
        unexpected = (
            set(data.files) - {"__header__"}
            - {f"{g}/{n}" for g, sub in self._params.items() for n in sub}
        )
        if unexpected:
            raise CheckpointMismatchError(
                f"checkpoint contains unexpected arrays: {sorted(unexpected)}"
            )

        self._params = new_params
        self.reset_state()


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def load_world_model(backend: str, obs_dim: int, **kwargs: Any) -> WorldModel:
    """Construct a WorldModel for the configured backend.

    ``backend="fake"`` (or "inmemory") → :class:`FakeWorldModel` (no deps).
    ``backend="dreamerv3"`` → :class:`DreamerV3WorldModel` (requires the
    ``[worldmodel]`` extra; a clear ImportError is raised if it is absent).
    """
    if backend in ("fake", "inmemory", "none"):
        decay = float(kwargs.get("decay", 0.5))
        return FakeWorldModel(obs_dim, decay=decay)
    if backend == "dreamerv3":
        allowed = {
            "deter_dim", "stoch_dim", "stoch_classes", "hidden_dim",
            "latent_kind", "learning_rate", "kl_balance", "kl_free_bits",
            "kl_scale", "seed",
        }
        sub = {k: v for k, v in kwargs.items() if k in allowed}
        return DreamerV3WorldModel(obs_dim, **sub)
    raise ValueError(f"unknown phantasia backend {backend!r}")
