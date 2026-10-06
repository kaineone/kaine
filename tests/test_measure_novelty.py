# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import importlib.util
import types
from pathlib import Path


def _load_measure_novelty():
    path = Path(__file__).resolve().parent.parent / "scripts" / "measure_novelty.py"
    spec = importlib.util.spec_from_file_location("measure_novelty", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mn = _load_measure_novelty()


def _event(source="src", type_="type", payload=None, **kwargs):
    ns = types.SimpleNamespace(source=source, type=type_, payload=payload or {})
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


def test_current_equals_kaine_fingerprint():
    from kaine.workspace.novelty import fingerprint as kaine_fingerprint

    ev = _event(payload={"x": 1.0, "label": "a"})
    assert mn.candidate_fingerprint(ev, "current") == kaine_fingerprint(ev)


def test_strip_ignores_latent_vector():
    latent_a = [0.1 + i * 0.0001 for i in range(768)]
    latent_b = [0.2 + i * 0.0001 for i in range(768)]
    ev1 = _event(payload={"latent": latent_a, "change": 0.5})
    ev2 = _event(payload={"latent": latent_b, "change": 0.5})

    assert mn.candidate_fingerprint(ev1, "strip") == mn.candidate_fingerprint(
        ev2, "strip"
    )
    assert mn.candidate_fingerprint(ev1, "current") != mn.candidate_fingerprint(
        ev2, "current"
    )


def test_quantisation_separates_by_resolution():
    ev1 = _event(payload={"prediction_error": 0.011})
    ev2 = _event(payload={"prediction_error": 0.0145})

    assert mn.candidate_fingerprint(ev1, "strip+q0.01") == mn.candidate_fingerprint(
        ev2, "strip+q0.01"
    )
    assert mn.candidate_fingerprint(ev1, "strip+q0.001") != mn.candidate_fingerprint(
        ev2, "strip+q0.001"
    )


def test_string_field_changes_all_candidates():
    ev1 = _event(payload={"label": "a", "x": 1.0})
    ev2 = _event(payload={"label": "b", "x": 1.0})

    for cand in ("current", "strip", "strip+q0.1", "strip+categorical"):
        assert mn.candidate_fingerprint(ev1, cand) != mn.candidate_fingerprint(
            ev2, cand
        )


def test_categorical_ignores_float_differences():
    ev1 = _event(payload={"a": 1.5, "b": True, "c": 2})
    ev2 = _event(payload={"a": 9.9, "b": True, "c": 2})

    assert mn.candidate_fingerprint(ev1, "strip+categorical") == mn.candidate_fingerprint(
        ev2, "strip+categorical"
    )
    assert mn.candidate_fingerprint(ev1, "current") != mn.candidate_fingerprint(
        ev2, "current"
    )
    assert mn.candidate_fingerprint(ev1, "strip") != mn.candidate_fingerprint(
        ev2, "strip"
    )


def test_novelty_series_repeated_event_habituates():
    ev = _event(payload={"x": 1.0})
    series = mn.novelty_series([ev, ev, ev], "strip", window=32)

    assert series[0] == 1.0
    assert all(series[i] >= series[i + 1] for i in range(len(series) - 1))


def test_summarise_reports_alert_means():
    ev_alert = _event(payload={"alert": True})
    ev_normal = _event(payload={"alert": False})
    events = [ev_alert, ev_normal]
    series = mn.novelty_series(events, "current")
    result = mn.summarise(series, events)

    assert "alert_true_mean" in result
    assert "alert_false_mean" in result
    assert result["alert_true_mean"] == 1.0
    assert result["alert_false_mean"] == 1.0


def test_quantisation_keeps_non_finite_values():
    ev = _event(payload={"time_since_last_interaction_s": float("inf")})
    assert mn.candidate_fingerprint(ev, "strip+q0.01") == mn.candidate_fingerprint(ev, "strip+q0.01")
