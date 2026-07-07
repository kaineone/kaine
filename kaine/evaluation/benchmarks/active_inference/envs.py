# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Discrete-POMDP task library for the AIF-vs-RL benchmark.

The benchmark needs tasks that both agents can play *fairly*: the RL baseline
consumes scalar reward; the active-inference agent consumes a preference vector
``C`` over observations. The matched-information assumption (design.md) is that
both agents observe the same thing and receive the same reward — the AIF agent
additionally gets the generative model (``A``/``B``/``C``/``D``) it is entitled
to, because *that generative model is the thing under test*.

Interface
---------
Every task is a :class:`DiscretePOMDP`:

- ``reset(rng) -> obs`` starts an episode (drawing a new hidden context where one
  exists) and returns the initial observation, a tuple of per-modality int
  indices.
- ``step(action) -> (obs, reward, done, info)`` advances one timestep. ``obs`` is
  an observation tuple; ``reward`` is a float; ``done`` ends the episode;
  ``info`` is a dict (carries e.g. ``{"is_probe": bool}``).
- ``num_states`` / ``num_obs`` / ``num_actions`` describe the discrete spaces.
  For multi-factor / multi-modality tasks these are *lists* (per factor /
  modality), mirroring pymdp's layout; for the flat exploitation task they are
  ints.
- ``A`` / ``B`` are the generative-model observation / transition tensors (lists
  over modalities / factors, pymdp layout) the AIF agent is handed.
- ``preference_C()`` returns the per-modality AIF preference (pymdp
  log-preference convention: higher = more preferred) encoding the *same* reward
  the RL agent receives — the matching is documented in
  :meth:`DiscretePOMDP.reward_matching`.
- ``rl_obs_key(obs)`` flattens the observation tuple to the scalar key the
  tabular RL baseline indexes its Q-table by (the baseline has no belief state).
- ``optimal_return()`` is the expected per-episode return of an oracle that
  exploits the generative model, used for regret.

Two task families are provided (design.md task suite):

1. :class:`TMazeEpistemicPOMDP` — the canonical information-seeking task. A
   hidden reward condition (left vs right arm) is unobservable until the agent
   visits a *cue* location (the probe) at a small opportunity cost. The
   reward-maximising policy must probe the cue before committing to an arm. This
   is the literature-standard case (Friston et al.'s T-maze) where EFE's
   epistemic term produces earlier, more reliable probing than ε-greedy. The
   matrices replicate pymdp's shipped ``TMaze`` (5 locations, adjacent
   connectivity) — the structure under which a correctly-wired EFE agent
   provably visits the cue first.
2. :class:`ExploitationPOMDP` — fully observed, no hidden state; a fixed
   observation->action mapping is optimal. Model-free RL is expected to be
   competitive; including it guards against an AIF-favourable suite (design.md).

All tasks are parameterised over noise / horizon / info-cost so sensitivity runs
are possible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

import numpy as np

Obs = tuple[int, ...]


@runtime_checkable
class DiscretePOMDP(Protocol):
    """Minimal discrete-POMDP interface shared by both agents."""

    name: str
    horizon: int
    A: list[np.ndarray]
    B: list[np.ndarray]
    A_dependencies: list[list[int]]
    D: list[np.ndarray]
    # AIF planning depth needed to expose this task's epistemic structure.
    policy_len: int
    # Index of the controllable factor's action that is the "probe" (or None).
    probe_action: Optional[int]

    def reset(self, rng: np.random.Generator) -> Obs:
        raise NotImplementedError

    def step(self, action: int) -> tuple[Obs, float, bool, dict[str, Any]]:
        raise NotImplementedError

    def preference_C(self) -> list[np.ndarray]:
        raise NotImplementedError

    def rl_obs_key(self, obs: Obs) -> int:
        raise NotImplementedError

    def num_actions(self) -> int:
        raise NotImplementedError

    def optimal_return(self) -> float:
        raise NotImplementedError

    def reward_matching(self) -> dict[str, Any]:
        raise NotImplementedError


def _normalize_columns(mat: np.ndarray) -> np.ndarray:
    col_sums = mat.sum(axis=0, keepdims=True)
    col_sums = np.where(col_sums == 0.0, 1.0, col_sums)
    return mat / col_sums


# ---------------------------------------------------------------------------
# Epistemic task — T-maze with a costed cue (probe).
# ---------------------------------------------------------------------------


@dataclass
class TMazeEpistemicPOMDP:
    """T-maze: the reward arm is hidden until the agent probes the cue.

    Layout (5 locations, indices match pymdp's ``TMaze``):
    ``centre=0, left=1, right=2, cue=3, middle=4``. From centre the agent can
    step to the cue (one move) or toward the arms via the middle. One arm yields
    ``reward_correct`` and the other ``reward_wrong``; which is which is the
    *hidden reward condition* (``num_reward_conditions == 2``), fixed per
    episode and re-drawn uniformly at :meth:`reset`. Visiting the **cue**
    location reveals the condition (a noisy signal of validity ``cue_validity``)
    but yields no reward and costs a timestep — this is the *probe*. The
    reward-maximising policy probes the cue, then commits to the revealed arm.

    Generative model (handed to the AIF agent), pymdp layout:
      Hidden factors: ``[location (5, controllable), reward_condition (2)]``.
      Modalities: ``[location-obs (5), reward-obs (3: none/win/lose),
      cue-obs (3: none/cue-left/cue-right)]``.
      ``A``/``B``/``D`` replicate pymdp's shipped adjacent T-maze, the structure
      under which an EFE planner (``policy_len >= 4``) provably visits the cue
      before an arm. The RL baseline indexes the *same* observations but has no
      belief over the hidden condition (:meth:`rl_obs_key`).

    Reward matching: the env's scalar reward is realised at the arms
    (``reward_correct`` / ``reward_wrong``) and as a small per-step ``step_cost``
    elsewhere (the cue's opportunity cost). The AIF preference ``C`` puts the
    same magnitudes on the reward-observation modality (win preferred, lose
    dispreferred), neutral elsewhere — the *value of the cue is purely
    epistemic*, which EFE prices and ε-greedy does not.
    """

    name: str = "tmaze_epistemic"
    # Default cue validity at which a policy_len=4 EFE planner robustly values
    # the probe over a direct gamble (the epistemic term must beat the ~0.5
    # direct-arm expected return). Lower validities are a documented sensitivity
    # axis: the value of epistemic action falls off as the cue becomes noisier,
    # and the benchmark can report that by sweeping this parameter.
    cue_validity: float = 0.98
    reward_correct: float = 1.0
    reward_wrong: float = -1.0
    step_cost: float = 0.0  # opportunity cost is the spent timestep; extra optional
    horizon: int = 4
    policy_len: int = 4
    obs_noise: float = 0.0  # location-observation corruption (kept clean by default)

    # location indices
    CENTRE: int = field(default=0, init=False)
    LEFT: int = field(default=1, init=False)
    RIGHT: int = field(default=2, init=False)
    CUE: int = field(default=3, init=False)
    MIDDLE: int = field(default=4, init=False)
    num_locations: int = field(default=5, init=False)
    num_reward_conditions: int = field(default=2, init=False)
    probe_action: Optional[int] = field(default=3, init=False)  # action == go-to-cue

    A: list[np.ndarray] = field(init=False)
    B: list[np.ndarray] = field(init=False)
    D: list[np.ndarray] = field(init=False)
    A_dependencies: list[list[int]] = field(init=False)

    def __post_init__(self) -> None:
        if not 0.5 < self.cue_validity <= 1.0:
            raise ValueError("cue_validity must be in (0.5, 1]")
        if self.horizon < 3:
            raise ValueError("T-maze needs horizon >= 3 (cue, then move to arm)")
        if self.policy_len < 2:
            raise ValueError("epistemic planning needs policy_len >= 2")
        self.A_dependencies = [[0, 1], [0, 1], [0, 1]]
        self.A = self._build_A()
        self.B = self._build_B()
        self.D = self._build_D()
        self._adjacency = self._valid_connections()
        self._reward_condition = 0
        self._location = self.CENTRE
        self._t = 0
        self._done = True

    # -- generative-model tensors -------------------------------------------

    def _build_A(self) -> list[np.ndarray]:
        nloc, nrc = self.num_locations, self.num_reward_conditions
        # Modality 0: location observation (near-identity over location).
        a_loc = np.zeros((nloc, nloc, nrc))
        for rc in range(nrc):
            base = np.full((nloc, nloc), self.obs_noise / max(nloc - 1, 1))
            np.fill_diagonal(base, 1.0 - self.obs_noise)
            a_loc[:, :, rc] = _normalize_columns(base)
        # Modality 1: reward observation (0 none, 1 win, 2 lose).
        a_rew = np.zeros((3, nloc, nrc))
        # Modality 2: cue observation (0 none, 1 cue-left, 2 cue-right).
        a_cue = np.zeros((3, nloc, nrc))
        for rc in range(nrc):
            for loc in range(nloc):
                if loc in (self.CENTRE, self.MIDDLE):
                    a_rew[0, loc, rc] = 1.0
                    a_cue[0, loc, rc] = 1.0
                elif loc == self.CUE:
                    a_rew[0, loc, rc] = 1.0
                    a_cue[rc + 1, loc, rc] = self.cue_validity
                    a_cue[(1 - rc) + 1, loc, rc] = 1.0 - self.cue_validity
                elif loc == self.LEFT:
                    a_rew[1 if rc == 0 else 2, loc, rc] = 1.0
                    a_cue[0, loc, rc] = 1.0
                elif loc == self.RIGHT:
                    a_rew[1 if rc == 1 else 2, loc, rc] = 1.0
                    a_cue[0, loc, rc] = 1.0
        return [a_loc, a_rew, a_cue]

    def _valid_connections(self) -> set[tuple[int, int]]:
        c, l, r, cue, m = (
            self.CENTRE,
            self.LEFT,
            self.RIGHT,
            self.CUE,
            self.MIDDLE,
        )
        return {
            (c, cue),
            (cue, c),
            (c, m),
            (m, c),
            (m, l),
            (l, m),
            (m, r),
            (r, m),
        }

    def _build_B(self) -> list[np.ndarray]:
        nloc, nrc = self.num_locations, self.num_reward_conditions
        # Factor 0: location, adjacent connectivity. Action a tries to move to
        # location a; if that move is not a valid adjacency, the agent stays put.
        b_loc = np.zeros((nloc, nloc, nloc))
        valid = self._valid_connections()
        for _from in range(nloc):
            for action in range(nloc):
                _to = action
                if (_from, _to) in valid or _from == _to:
                    b_loc[_to, _from, action] = 1.0
                else:
                    b_loc[_from, _from, action] = 1.0
        # Factor 1: reward condition is fixed within an episode.
        b_rew = np.eye(nrc).reshape(nrc, nrc, 1)
        return [b_loc, b_rew]

    def _build_D(self) -> list[np.ndarray]:
        d_loc = np.zeros(self.num_locations)
        d_loc[self.CENTRE] = 1.0
        d_rew = np.full(self.num_reward_conditions, 1.0 / self.num_reward_conditions)
        return [d_loc, d_rew]

    def preference_C(self) -> list[np.ndarray]:
        c_loc = np.zeros(self.num_locations)
        c_rew = np.array([0.0, self.reward_correct, self.reward_wrong], dtype=float)
        c_cue = np.zeros(3)
        # Scale the reward preference so EFE's pragmatic term is commensurate
        # with the epistemic term (a stronger preference makes the *certain*
        # post-cue reward decisively better than the 50/50 direct-arm gamble).
        c_rew = c_rew * 4.0
        return [c_loc, c_rew, c_cue]

    def reward_matching(self) -> dict[str, Any]:
        return {
            "scalar_reward": {
                "reach_correct_arm": self.reward_correct,
                "reach_wrong_arm": self.reward_wrong,
                "per_step (incl. cue)": -self.step_cost,
            },
            "preference_C": (
                "log-pref over the reward-obs modality: win "
                f"+{self.reward_correct * 4.0}, lose {self.reward_wrong * 4.0}, "
                "location/cue modalities neutral."
            ),
            "note": (
                "Same reward, two encodings: RL gets the scalar; AIF gets C plus "
                "the generative model (A/B/D). The cue's value is purely epistemic "
                "(it reveals the reward condition), which EFE prices via the "
                "info-gain term and epsilon-greedy does not."
            ),
        }

    def num_actions(self) -> int:
        return self.num_locations  # one move-to-location action per location

    def optimal_return(self) -> float:
        """Oracle: go to the cue, then to the revealed arm.

        With a clean cue this is ``reward_correct`` minus the chance the cue
        misleads (``1 - cue_validity``) times the win/lose swing, minus step
        cost for the (>=2) moves it takes.
        """
        hit = self.cue_validity * self.reward_correct + (1.0 - self.cue_validity) * self.reward_wrong
        return hit - 2.0 * self.step_cost

    # -- dynamics ------------------------------------------------------------

    def reset(self, rng: np.random.Generator) -> Obs:
        self._rng = rng
        self._reward_condition = int(rng.integers(0, self.num_reward_conditions))
        self._location = self.CENTRE
        self._t = 0
        self._done = False
        return self._emit_obs(reached_arm=False)

    def _emit_obs(self, reached_arm: bool) -> Obs:
        loc = self._location
        rc = self._reward_condition
        # location obs (optionally noisy)
        if self.obs_noise > 0.0 and self._rng.random() < self.obs_noise:
            choices = [o for o in range(self.num_locations) if o != loc]
            loc_obs = int(self._rng.choice(choices))
        else:
            loc_obs = loc
        # reward obs
        if loc == self.LEFT:
            rew_obs = 1 if rc == 0 else 2
        elif loc == self.RIGHT:
            rew_obs = 1 if rc == 1 else 2
        else:
            rew_obs = 0
        # cue obs (noisy at the cue location only)
        if loc == self.CUE:
            valid = self._rng.random() < self.cue_validity
            true_cue = rc + 1
            cue_obs = true_cue if valid else (1 - rc) + 1
        else:
            cue_obs = 0
        return (loc_obs, rew_obs, cue_obs)

    def step(self, action: int) -> tuple[Obs, float, bool, dict[str, Any]]:
        if self._done:
            raise RuntimeError("step() called on a finished episode; reset() first")
        action = int(action)
        self._t += 1
        prev_loc = self._location
        # Attempt the move; invalid adjacency = stay put (matches B).
        if (prev_loc, action) in self._adjacency or prev_loc == action:
            self._location = action
        # else: location unchanged.
        is_probe = self._location == self.CUE and prev_loc != self.CUE

        reward = -self.step_cost
        done = False
        reached_arm = self._location in (self.LEFT, self.RIGHT)
        if reached_arm:
            correct = (self._location == self.LEFT and self._reward_condition == 0) or (
                self._location == self.RIGHT and self._reward_condition == 1
            )
            reward += self.reward_correct if correct else self.reward_wrong
            done = True
        if self._t >= self.horizon:
            done = True
        self._done = done
        info = {
            "is_probe": is_probe,
            "at_cue": self._location == self.CUE,
            "reached_arm": reached_arm,
            "reward_condition": self._reward_condition,
            "location": self._location,
        }
        return self._emit_obs(reached_arm), reward, done, info

    def rl_obs_key(self, obs: Obs) -> int:
        """Flatten (location-obs, reward-obs, cue-obs) to a scalar Q-table key.

        The RL baseline acts on raw observations only — it has no belief over the
        hidden reward condition. It *can* see the cue observation once at the cue
        location (so it is not denied information the AIF agent uses); what it
        lacks is the model that carries that information forward into a belief.
        """
        loc_obs, rew_obs, cue_obs = obs
        return int(loc_obs * 9 + rew_obs * 3 + cue_obs)

    def rl_num_obs(self) -> int:
        return self.num_locations * 9


# ---------------------------------------------------------------------------
# Exploitation task — fully observed, fixed optimal mapping.
# ---------------------------------------------------------------------------


@dataclass
class ExploitationPOMDP:
    """Fully observed contextual task with a fixed optimal obs->action mapping.

    Each step a context ``s`` is drawn (uniform) and *directly observed* (the
    context observation is near-identity, noise ``obs_noise``). The optimal
    action is ``s`` itself: action == observed-context wins, anything else
    loses. There is no hidden state and no probing affordance, so info-seeking
    has no value here — model-free RL is expected to be competitive or better.
    Including this task guards the suite against being AIF-favourable by
    construction (design.md).

    Generative model (handed to the AIF agent), pymdp layout:
      Hidden factors: ``[context (n, observed, persistent), choice (n,
      controllable)]``. The context is the drawn, directly-observed situation;
      the choice is the agent's committed action. The context's transition is
      the identity (it persists through the one-step planning horizon — the env
      re-draws it only at the next :meth:`reset`); the choice's ``B`` is the
      one-slice-per-action selector, exactly as the Nous control factor works.
      Modalities: ``[context-obs (n, near-identity), reward-obs (2: lose/win)]``.
      The reward modality is ``win`` iff ``choice == context``. With a strong
      ``C`` on ``win`` and a clean context observation, a ``policy_len == 1`` EFE
      step selects the matching choice — the fixed optimal mapping, no probing.

    The episode is a single decision (``horizon == 1``); accuracy over many
    episodes is the decision-quality signal. The controllable factor is factor 0
    by convention (the AIF adapter reads action off factor 0), so ``choice`` is
    factor 0 and ``context`` is factor 1 here.
    """

    name: str = "exploitation"
    n: int = 3
    obs_noise: float = 0.05
    horizon: int = 1
    reward_correct: float = 1.0
    reward_wrong: float = -1.0
    policy_len: int = 1
    probe_action: Optional[int] = field(default=None, init=False)

    A: list[np.ndarray] = field(init=False)
    B: list[np.ndarray] = field(init=False)
    D: list[np.ndarray] = field(init=False)
    A_dependencies: list[list[int]] = field(init=False)

    def __post_init__(self) -> None:
        if self.n < 2:
            raise ValueError("exploitation task needs n >= 2 contexts")
        if not 0.0 <= self.obs_noise < 0.5:
            raise ValueError("obs_noise must be in [0, 0.5)")
        # Factor 0: choice (controllable). Factor 1: context (observed,
        # persistent within the one-step horizon). Modality 0 (context obs)
        # reads the context; modality 1 (reward) depends on both (win iff
        # choice == context). Both modalities depend on both factors.
        self.A_dependencies = [[0, 1], [0, 1]]
        self.A = self._build_A()
        self.B = self._build_B()
        d_choice = np.full(self.n, 1.0 / self.n)
        d_context = np.full(self.n, 1.0 / self.n)
        self.D = [d_choice, d_context]
        self._state = 0
        self._t = 0
        self._done = True

    def _build_A(self) -> list[np.ndarray]:
        # Modality 0: context observation (near-identity over context, factor 1;
        # invariant to the choice factor). Shape (n_obs, n_choice, n_context).
        off = self.obs_noise / max(self.n - 1, 1)
        ctx_like = np.full((self.n, self.n), off)
        np.fill_diagonal(ctx_like, 1.0 - self.obs_noise)
        ctx_like = _normalize_columns(ctx_like)
        a_ctx = np.zeros((self.n, self.n, self.n))
        for ch in range(self.n):
            a_ctx[:, ch, :] = ctx_like
        # Modality 1: reward (0 lose, 1 win) — win iff choice == context.
        a_rew = np.zeros((2, self.n, self.n))
        for ch in range(self.n):
            for ctx in range(self.n):
                a_rew[1 if ch == ctx else 0, ch, ctx] = 1.0
        return [a_ctx, a_rew]

    def _build_B(self) -> list[np.ndarray]:
        # Factor 0 (choice): controllable — action a moves the choice latent to
        # state a (one slice per action), mirroring the Nous control factor.
        b_choice = np.zeros((self.n, self.n, self.n))
        for a in range(self.n):
            b_choice[a, :, a] = 1.0
        # Factor 1 (context): persistent within the planning horizon (identity,
        # single slice). The env re-draws it only at the next reset.
        b_context = np.eye(self.n).reshape(self.n, self.n, 1)
        return [b_choice, b_context]

    def preference_C(self) -> list[np.ndarray]:
        # Modality 0 (context obs): neutral. Modality 1 (reward): win preferred.
        c_ctx = np.zeros(self.n)
        c_rew = np.array([self.reward_wrong, self.reward_correct], dtype=float) * 4.0
        return [c_ctx, c_rew]

    def reward_matching(self) -> dict[str, Any]:
        return {
            "scalar_reward": {
                "action == observed_context": self.reward_correct,
                "otherwise": self.reward_wrong,
            },
            "preference_C": (
                f"log-pref over reward-obs: win +{self.reward_correct * 4.0}, "
                f"lose {self.reward_wrong * 4.0}; context modality neutral."
            ),
            "note": (
                "Fully observed; optimal policy is a fixed obs->action map. No "
                "epistemic affordance — info-seeking has no value, so model-free "
                "RL is expected to be competitive."
            ),
        }

    def num_actions(self) -> int:
        return self.n

    def optimal_return(self) -> float:
        return (1.0 - self.obs_noise) * self.reward_correct + self.obs_noise * self.reward_wrong

    def reset(self, rng: np.random.Generator) -> Obs:
        self._rng = rng
        self._t = 0
        self._done = False
        self._state = int(rng.integers(0, self.n))
        return (self._emit_obs(), 0)

    def _emit_obs(self) -> int:
        if self.obs_noise > 0.0 and self._rng.random() < self.obs_noise and self.n > 1:
            choices = [o for o in range(self.n) if o != self._state]
            return int(self._rng.choice(choices))
        return self._state

    def step(self, action: int) -> tuple[Obs, float, bool, dict[str, Any]]:
        if self._done:
            raise RuntimeError("step() called on a finished episode; reset() first")
        action = int(action)
        win = action == self._state
        reward = self.reward_correct if win else self.reward_wrong
        info = {"is_probe": False, "context": self._state}
        self._t += 1
        done = self._t >= self.horizon
        self._done = done
        if not done:
            self._state = int(self._rng.integers(0, self.n))
        # reward-obs: 1 win, 0 lose (so the AIF model's reward modality is fed).
        return (self._emit_obs(), 1 if win else 0), reward, done, info

    def rl_obs_key(self, obs: Obs) -> int:
        # The baseline keys on the context observation only (the reward-obs is a
        # post-action consequence, not available when choosing).
        return int(obs[0])

    def rl_num_obs(self) -> int:
        return self.n


# ---------------------------------------------------------------------------
# Task registry — the default suite.
# ---------------------------------------------------------------------------


def default_suite() -> list[DiscretePOMDP]:
    """The default benchmark suite: one epistemic + one exploitation task."""
    return [TMazeEpistemicPOMDP(), ExploitationPOMDP()]


def is_epistemic(task: DiscretePOMDP) -> bool:
    """A task is epistemic if it exposes a costed probe affordance."""
    return getattr(task, "probe_action", None) is not None


__all__ = [
    "DiscretePOMDP",
    "TMazeEpistemicPOMDP",
    "ExploitationPOMDP",
    "default_suite",
    "is_epistemic",
]
