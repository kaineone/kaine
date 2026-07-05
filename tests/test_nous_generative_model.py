# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Generative-model tests — uses the REAL pymdp 1.0 JAX API.

Skipped automatically if the `reasoning` extra (inferactively-pymdp + jax) is
not installed, so a green build never *requires* pymdp. The compact model is
small (factors=4, max states=4), so these are fast.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from kaine.modules.nous.generative_model import (
    ACTION_SPACE,
    build_generative_model,
    encode_snapshot,
)

pytest.importorskip("pymdp")
pytest.importorskip("jax")


@dataclass
class _Ev:
    source: str
    payload: dict
    salience: float


class _Snap:
    def __init__(self, events):
        self.selected_events = [(str(i), e) for i, e in enumerate(events)]


def test_action_space_is_four_canonical_actions():
    assert ACTION_SPACE == (
        "no_op",
        "request_think",
        "request_speak",
        "request_maintenance",
    )


def test_b_matrix_has_four_action_dimensions():
    gm = build_generative_model()
    # Factor 0 is the controllable action latent; its B last dim == action count.
    b0 = gm.B[0]
    assert b0.shape[-1] == len(ACTION_SPACE) == 4
    # Uncontrollable factors have a single action slice.
    for f in range(1, gm.num_factors):
        assert gm.B[f].shape[-1] == 1


def _build_agent(gm):
    """Build a pymdp Agent from a GenerativeModel, suppressing the benign
    equinox 'JAX array set as static' warning from the constructor."""
    import warnings

    import jax.numpy as jnp
    from pymdp.agent import Agent

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Agent(
            A=[jnp.array(a) for a in gm.A],
            B=[jnp.array(b) for b in gm.B],
            C=[jnp.array(c) for c in gm.C],
            D=[jnp.array(d) for d in gm.D],
            A_dependencies=gm.A_dependencies,
            policy_len=1,
        )


def test_model_builds_a_valid_pymdp_agent_with_four_policies():
    gm = build_generative_model()
    agent = _build_agent(gm)
    dims = agent.get_model_dimensions()
    assert dims["num_factors"] == gm.num_factors == 4
    assert dims["num_modalities"] == gm.num_modalities == 4
    # Exactly one control factor of size 4 => four policies at horizon 1.
    assert dims["num_policies"] == 4
    assert dims["num_controls"][0] == 4


def test_infer_states_returns_per_factor_posterior():
    import jax.numpy as jnp

    gm = build_generative_model()
    agent = _build_agent(gm)
    obs = [jnp.array([0]), jnp.array([2]), jnp.array([1]), jnp.array([1])]
    qs = agent.infer_states(obs, empirical_prior=agent.D)
    assert len(qs) == gm.num_factors
    # A clear salience observation (band 2) concentrates that factor's posterior.
    import numpy as np

    salience_post = np.asarray(qs[1]).reshape(-1)
    assert int(np.argmax(salience_post)) == 2


def test_encode_snapshot_maps_salience_and_source():
    gm = build_generative_model()
    snap = _Snap(
        [
            _Ev("soma", {}, 0.95),  # high salience, perception cluster
            _Ev("thymos", {"state": {"valence": 0.5, "arousal": 0.8}}, 0.3),
        ]
    )
    obs = encode_snapshot(snap, gm)
    assert len(obs) == gm.num_modalities
    # action latent always starts at no_op.
    assert obs[0] == 0
    # high salience -> top band.
    assert obs[1] == len(gm.salience_bands) - 1
    # dominant event is soma -> perception cluster.
    assert obs[3] == gm.event_clusters.index("cluster_perception")
    # every index within its modality's range.
    for o, n in zip(obs, gm.num_obs):
        assert 0 <= o < n


def test_encode_snapshot_handles_missing_factors_gracefully():
    gm = build_generative_model()
    # No events at all.
    obs_empty = encode_snapshot(_Snap([]), gm)
    assert obs_empty == [0, 0, 0, 0]

    # Event from an unmapped source with no payload -> cluster_other (0),
    # neutral affect (0).
    obs_unknown = encode_snapshot(_Snap([_Ev("mystery_module", {}, 0.2)]), gm)
    assert obs_unknown[3] == 0
    assert obs_unknown[2] == 0
    for o, n in zip(obs_unknown, gm.num_obs):
        assert 0 <= o < n


def test_max_states_per_factor_cap_is_enforced():
    with pytest.raises(ValueError):
        build_generative_model(max_states_per_factor=2)  # affect has 4 states


def test_factor_growth_seam_documented():
    from kaine.modules.nous.generative_model import (
        DEFAULT_EVENT_CLUSTERS,
        register_event_cluster,
    )

    grown = register_event_cluster(
        DEFAULT_EVENT_CLUSTERS, source="praxis", label="cluster_action"
    )
    assert "cluster_action" in grown
    # The model can be rebuilt over the grown cluster set.
    gm = build_generative_model(event_clusters=grown)
    assert gm.num_states[3] == len(grown)
