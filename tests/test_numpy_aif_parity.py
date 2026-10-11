# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Parity tests for the pure NumPy active-inference engine against pymdp golden fixtures."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from kaine.modules.nous.numpy_aif import NumpyAgent, dirichlet_expected_value

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "nous_golden"


def _load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _model_from_fixture(model_json: dict) -> dict:
    return {
        "A": [np.asarray(a, dtype=np.float64) for a in model_json["A"]],
        "B": [np.asarray(b, dtype=np.float64) for b in model_json["B"]],
        "C": [np.asarray(c, dtype=np.float64) for c in model_json["C"]],
        "D": [np.asarray(d, dtype=np.float64) for d in model_json["D"]],
        "pB": (
            [np.asarray(pb, dtype=np.float64) for pb in model_json["pB"]]
            if model_json.get("pB") is not None
            else None
        ),
        "A_dependencies": model_json["A_dependencies"],
        "B_action_dependencies": model_json.get("B_action_dependencies"),
        "num_states": model_json["num_states"],
        "num_obs": model_json["num_obs"],
        "actions": model_json.get("actions"),
        "transition_max_concentration": model_json.get(
            "transition_max_concentration"
        ),
    }


def _to_flat(arr):
    return np.asarray(arr, dtype=np.float64).reshape(-1)


def _make_agent(
    model: dict,
    policy_len: int,
    num_iter: int,
    learn_B: bool,
    use_param_info_gain: bool,
) -> NumpyAgent:
    kwargs = {
        "A": model["A"],
        "B": model["B"],
        "C": model["C"],
        "D": model["D"],
        "A_dependencies": model["A_dependencies"],
        "policy_len": policy_len,
        "num_iter": num_iter,
        "use_param_info_gain": use_param_info_gain,
        "learn_B": learn_B,
    }
    if model["pB"] is not None:
        kwargs["pB"] = model["pB"]
    if model["B_action_dependencies"] is not None:
        kwargs["B_action_dependencies"] = model["B_action_dependencies"]
        kwargs["num_controls"] = [len(model["actions"])]
    return NumpyAgent(**kwargs)


def _first_step_row(policies: np.ndarray, action_index: int) -> np.ndarray:
    first = policies[:, 0, 0]
    matches = np.flatnonzero(first == action_index)
    if matches.size == 0:
        raise RuntimeError(f"no policy begins with action {action_index}")
    return policies[matches[0], 0].copy()


def _per_action_efe(
    policies: np.ndarray, neg_efe: np.ndarray, n_actions: int
) -> tuple[list[float], int]:
    efe = -neg_efe
    per_action = [float("inf")] * n_actions
    for p_idx, action_first in enumerate(policies[:, 0, 0]):
        a = int(action_first)
        if 0 <= a < n_actions and efe[p_idx] < per_action[a]:
            per_action[a] = efe[p_idx]
    best = int(min(range(n_actions), key=lambda i: per_action[i]))
    return per_action, best


def _restore_action_factor(
    agent: NumpyAgent,
    orig_B0: np.ndarray,
    orig_pB0: np.ndarray | None,
) -> NumpyAgent:
    B = list(agent.B)
    pB = list(agent.pB) if agent.pB is not None else None
    B[0] = np.asarray(orig_B0, dtype=np.float64).copy()
    if pB is not None and orig_pB0 is not None:
        pB[0] = np.asarray(orig_pB0, dtype=np.float64).copy()
    return agent.with_state(B=B, pB=pB)


def _apply_evidence_cap(
    agent: NumpyAgent, cap: float | None, num_states: list[int]
) -> NumpyAgent:
    if cap is None or agent.pB is None:
        return agent
    B = list(agent.B)
    pB = list(agent.pB)
    for f in range(1, agent.num_factors):
        pb = pB[f]
        n_prev = pb.shape[1]
        n_a = pb.shape[-1]
        for s_prev in range(n_prev):
            for a in range(n_a):
                idx = (slice(None), s_prev) + (slice(None),) * (pb.ndim - 3) + (a,)
                col = pb[idx]
                col_sum = col.sum()
                if col_sum > cap:
                    pb_new = pb.copy()
                    pb_new[idx] = col * (cap / col_sum)
                    pB[f] = pb_new
                    pb = pB[f]
        B[f] = dirichlet_expected_value(pB[f])
    return agent.with_state(B=B, pB=pB)


def _replay(name: str, horizon: bool = False) -> None:
    fx = _load_fixture(name)
    model = _model_from_fixture(fx["model"])
    agent = _make_agent(
        model,
        policy_len=fx["model"]["policy_len"],
        num_iter=fx["model"]["num_iter"],
        learn_B=True,
        use_param_info_gain=True,
    )
    expected_policies = np.asarray(fx["policies"], dtype=np.int64)
    np.testing.assert_array_equal(agent.policies, expected_policies)

    orig_B0 = model["B"][0].copy()
    orig_pB0 = model["pB"][0].copy() if model["pB"] is not None else None
    prior = [d.copy() for d in model["D"]]
    prev_qs = None
    prev_action = None

    for step in fx["steps"]:
        obs = step["obs"]
        qs = agent.infer_states(obs, prior)
        q_pi, neg_efe = agent.infer_policies(qs)

        expected_neg = np.asarray(step["per_policy_neg_efe"], dtype=np.float64)
        np.testing.assert_allclose(neg_efe, expected_neg, atol=1e-4)

        expected_posterior = [
            np.asarray(np.asarray(p).reshape(-1), dtype=np.float64)
            for p in step["posterior"]
        ]
        for got, exp in zip(qs, expected_posterior):
            np.testing.assert_allclose(_to_flat(got), exp, atol=1e-4)

        n_actions = len(model["actions"])
        per_action, best = _per_action_efe(agent.policies, neg_efe, n_actions)
        expected_efe = [float(x) for x in step["policy_efe"]]
        for got, exp in zip(per_action, expected_efe):
            assert (np.isinf(got) and np.isinf(exp)) or abs(got - exp) < 1e-4
        assert best == int(step["action_index"])

        if prev_qs is not None and prev_action is not None:
            row = _first_step_row(agent.policies, prev_action)
            agent = agent.infer_parameters(prev_qs, qs, row)
            agent = _restore_action_factor(agent, orig_B0, orig_pB0)
            agent = _apply_evidence_cap(
                agent, model["transition_max_concentration"], model["num_states"]
            )

        row_a = _first_step_row(agent.policies, best)
        prior = agent.update_empirical_prior(row_a, qs)

        if "pB_after" in step and step["pB_after"] is not None:
            for got, exp in zip(agent.pB, step["pB_after"]):
                np.testing.assert_allclose(
                    np.asarray(got, dtype=np.float64),
                    np.asarray(exp, dtype=np.float64),
                    rtol=1e-4,
                    atol=1e-4,
                )

        if "carried_prior_after" in step and step["carried_prior_after"] is not None:
            for got, exp in zip(prior, step["carried_prior_after"]):
                np.testing.assert_allclose(
                    _to_flat(got),
                    _to_flat(exp),
                    atol=1e-4,
                )

        prev_qs = qs
        prev_action = best


def test_live_learning_replay():
    _replay("live_learning.json")


def test_live_horizon2_replay():
    _replay("live_horizon2.json")


def _benchmark_task(task_json: dict, name: str) -> None:
    model = _model_from_fixture(task_json["model"])
    agent = _make_agent(
        model,
        policy_len=task_json["model"]["policy_len"],
        num_iter=task_json["model"]["num_iter"],
        learn_B=False,
        use_param_info_gain=False,
    )
    expected_policies = np.asarray(task_json["policies"], dtype=np.int64)
    np.testing.assert_array_equal(agent.policies, expected_policies)

    n_actions = (
        len(model["actions"])
        if model.get("actions")
        else int(agent.policies[:, 0, 0].max()) + 1
    )

    for sample in task_json["samples"]:
        prior = [d.copy() for d in model["D"]]
        qs = agent.infer_states(sample["obs"], prior)
        q_pi, neg_efe = agent.infer_policies(qs)

        expected_neg = np.asarray(sample["per_policy_neg_efe"], dtype=np.float64)
        np.testing.assert_allclose(neg_efe, expected_neg, atol=1e-4)

        expected_posterior = [
            np.asarray(np.asarray(p).reshape(-1), dtype=np.float64)
            for p in sample["posterior"]
        ]
        for got, exp in zip(qs, expected_posterior):
            np.testing.assert_allclose(_to_flat(got), exp, atol=1e-4)

        per_action, best = _per_action_efe(agent.policies, neg_efe, n_actions)
        assert best == int(sample["action_index"])


def test_benchmark_exploitation():
    fx = _load_fixture("benchmark_tasks.json")
    _benchmark_task(fx["tasks"]["exploitation"], "exploitation")


def test_benchmark_tmaze():
    fx = _load_fixture("benchmark_tasks.json")
    _benchmark_task(fx["tasks"]["tmaze_epistemic"], "tmaze_epistemic")


def test_no_jax_import():
    code = textwrap.dedent(
        r"""
        import sys

        class Blocker:
            blocked = {"jax", "jaxlib", "pymdp", "equinox"}
            def find_module(self, fullname, path=None):
                top = fullname.split(".")[0]
                if top in self.blocked:
                    raise ImportError(f"import of {fullname} blocked")
                return None
            def find_spec(self, fullname, path=None, target=None):
                top = fullname.split(".")[0]
                if top in self.blocked:
                    raise ImportError(f"import of {fullname} blocked")
                return None

        sys.meta_path.insert(0, Blocker())

        import json
        import pathlib
        import numpy as np

        from kaine.modules.nous.numpy_aif import NumpyAgent

        fx_path = pathlib.Path("tests/fixtures/nous_golden/live_learning.json")
        with open(fx_path, "r") as f:
            fx = json.load(f)

        model = fx["model"]
        A = [np.asarray(a, dtype=np.float64) for a in model["A"]]
        B = [np.asarray(b, dtype=np.float64) for b in model["B"]]
        C = [np.asarray(c, dtype=np.float64) for c in model["C"]]
        D = [np.asarray(d, dtype=np.float64) for d in model["D"]]
        pB = [np.asarray(pb, dtype=np.float64) for pb in model["pB"]]

        agent = NumpyAgent(
            A=A,
            B=B,
            C=C,
            D=D,
            A_dependencies=model["A_dependencies"],
            pB=pB,
            B_action_dependencies=model["B_action_dependencies"],
            num_controls=[len(model["actions"])],
            policy_len=model["policy_len"],
            num_iter=model["num_iter"],
            use_param_info_gain=True,
            learn_B=True,
        )

        prior = D
        for step in fx["steps"][:3]:
            qs = agent.infer_states(step["obs"], prior)
            q_pi, neg = agent.infer_policies(qs)
            row = agent.policies[0, 0]
            prior = agent.update_empirical_prior(row, qs)

        print("success")
        """
    )
    repo_root = str(pathlib.Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert result.returncode == 0, result.stderr
    assert "success" in result.stdout
