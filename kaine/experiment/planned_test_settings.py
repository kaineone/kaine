# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The planned test's settings record.

This module implements the one versioned JSON record that the calibration tool
writes from the preliminary and pilot runs (paper Appendix A.8), its loader, and
the boot check that refuses a live planned-test run without a valid record.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from kaine.experiment import calibration_rules as rules
from kaine.experiment.principal_component import (
    canonical_bytes,
    file_sha256,
)
from kaine.storage import resolve

SCHEMA = "kaine.planned_test_settings"
SCHEMA_VERSION = 1
PROCESSORS = ("topos", "audition", "soma")
CONTROLS = ("matched", "pooled")
STUDY_PREFIX = "workspace_mediation_"
ROLES = ("preliminary", "pilot", "test", "positive_control")
RECORD_ROLES = ("test", "positive_control")
DEFAULT_RECORD_PATH = "config/studies/workspace_mediation_settings.json"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PlannedTestSettingsError(ValueError):
    """A planned-test settings record failed validation."""


STUDY_ROLES = {
    "workspace_mediation_competitive": "test",
    "workspace_mediation_matched": "test",
    "workspace_mediation_pooled": "test",
    "workspace_mediation_pilot_competitive": "pilot",
    "workspace_mediation_pilot_matched": "pilot",
    "workspace_mediation_pilot_pooled": "pilot",
    "workspace_mediation_preliminary": "preliminary",
    "workspace_mediation_positive_control": "positive_control",
}


def record_digest(record: Mapping[str, Any]) -> str:
    """Return the hex sha256 of ``record`` without its ``record_sha256`` key."""
    stripped = dict(record)
    stripped.pop("record_sha256", None)
    return hashlib.sha256(canonical_bytes(stripped)).hexdigest()


def write_settings_record(record: dict[str, Any], path: Path) -> str:
    """Write ``record`` to ``path`` and return its digest.

    The record is written atomically via a sibling temporary file and
    ``os.replace``. The digest is stored under ``record_sha256`` before writing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record["record_sha256"] = record_digest(record)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return record["record_sha256"]


@dataclass(frozen=True)
class PcRef:
    """A reference to a principal-component file used by the planned test."""

    path: str
    sha256: str


@dataclass(frozen=True)
class PlannedTestSettings:
    """Validated settings derived from a record on disk."""

    path: str
    record_sha256: str
    t_learn_s: float
    theta_eff: Mapping[str, float]
    min_effect: float
    min_reports: int
    snr: Mapping[str, float]
    principal_components: Mapping[str, PcRef]
    excluded_seeds: frozenset[int]


def _check_constant(
    path: Path,
    constants: Mapping[str, Any],
    key: str,
    expected: Any,
) -> None:
    """Fail if ``constants[key]`` does not equal the paper's ``expected``."""
    actual = constants.get(key)
    if actual != expected:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} constants.{key} is {actual!r}; "
            f"the paper's value is {expected!r}"
        )


def _check_constant_float(
    path: Path,
    constants: Mapping[str, Any],
    key: str,
    expected: float,
) -> None:
    """Fail if ``constants[key]`` is not the expected finite number."""
    actual = constants.get(key)
    if (
        isinstance(actual, bool)
        or not isinstance(actual, (int, float))
        or not math.isfinite(actual)
    ):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} constants.{key} is {actual!r}; "
            f"the paper's value is {expected!r}"
        )
    if float(actual) != expected:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} constants.{key} is {actual!r}; "
            f"the paper's value is {expected!r}"
        )


def load_settings_record(path: str | Path) -> PlannedTestSettings:
    """Load and validate a planned-test settings record.

    Fails closed with ``PlannedTestSettingsError`` and a message that names
    ``path`` and the failed check.
    """
    path = Path(path)
    if not path.is_file():
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} is missing or not a regular file"
        )

    try:
        with path.open("r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} cannot be read: {exc}"
        ) from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} must be a JSON object"
        )

    if payload.get("schema") != SCHEMA:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} has an unexpected schema"
        )

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} has an unexpected schema version"
        )

    record_sha256 = payload.get("record_sha256")
    if not isinstance(record_sha256, str) or record_sha256 != record_digest(payload):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} was edited after it was written "
            "(digest mismatch)"
        )

    blocked = payload.get("blocked")
    if not isinstance(blocked, dict) or blocked:
        keys = sorted(blocked.keys()) if isinstance(blocked, dict) else []
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} is blocked: "
            + ", ".join(f"{k}={blocked[k]!r}" for k in keys)
        )

    if payload.get("complete") is not True:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} is not marked complete"
        )

    raw_constants = payload.get("constants")
    if not isinstance(raw_constants, dict):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} must contain a 'constants' object"
        )

    _check_constant(path, raw_constants, "n_cal", rules.N_CAL)
    _check_constant(path, raw_constants, "c_eff", rules.C_EFF)
    _check_constant_float(path, raw_constants, "q_pow", float(rules.Q_POW))
    _check_constant_float(path, raw_constants, "target_power", float(rules.TARGET_POWER))
    _check_constant_float(path, raw_constants, "alpha_test", float(rules.ALPHA_TEST))
    _check_constant(path, raw_constants, "mser_batch", rules.MSER_BATCH)
    _check_constant(path, raw_constants, "mser_min_batches", rules.MSER_MIN_BATCHES)
    _check_constant(path, raw_constants, "n_bins", rules.N_BINS)

    raw_snr_ladder = raw_constants.get("snr_ladder")
    expected_snr_ladder = list(rules.SNR_LADDER)
    if raw_snr_ladder != expected_snr_ladder:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} constants.snr_ladder is "
            f"{raw_snr_ladder!r}; the paper's value is {expected_snr_ladder!r}"
        )

    raw_mser_ignore_end = raw_constants.get("mser_ignore_end")
    if (
        raw_mser_ignore_end is None
        or isinstance(raw_mser_ignore_end, bool)
        or not isinstance(raw_mser_ignore_end, int)
    ):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} constants.mser_ignore_end is "
            f"{raw_mser_ignore_end!r}; the learning-period rule is not fixed"
        )
    if raw_mser_ignore_end != rules.MSER_IGNORE_END:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} constants.mser_ignore_end is "
            f"{raw_mser_ignore_end!r}; the paper's value is {rules.MSER_IGNORE_END!r}"
        )

    values = payload.get("values")
    if not isinstance(values, dict):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} has no values object"
        )

    n_counted = values.get("n_counted")
    if n_counted != rules.N_CAL:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} values.n_counted is {n_counted!r}; "
            f"the paper's value is {rules.N_CAL!r}"
        )

    n_exact = values.get("n_exact")
    if n_exact != rules.N_EXACT:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} values.n_exact is {n_exact!r}; "
            f"the paper's value is {rules.N_EXACT!r}"
        )

    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} has no inputs object"
        )

    # t_learn_s
    raw_t = values.get("t_learn_s")
    if (
        isinstance(raw_t, bool)
        or not isinstance(raw_t, (int, float))
        or not math.isfinite(raw_t)
        or raw_t < 0
    ):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} value 't_learn_s' must be a "
            "non-negative finite number"
        )
    t_learn_s = float(raw_t)

    # theta_eff
    raw_theta = values.get("theta_eff")
    if not isinstance(raw_theta, dict):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} value 'theta_eff' must be an object"
        )
    theta_eff: dict[str, float] = {}
    for ctl in CONTROLS:
        v = raw_theta.get(ctl)
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v <= 0
        ):
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} value 'theta_eff.{ctl}' must be "
                "a positive finite number"
            )
        theta_eff[ctl] = float(v)

    # min_effect
    raw_min_effect = values.get("min_effect")
    if (
        isinstance(raw_min_effect, bool)
        or not isinstance(raw_min_effect, (int, float))
        or not math.isfinite(raw_min_effect)
        or raw_min_effect <= 0
    ):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} value 'min_effect' must be a "
            "positive finite number"
        )
    min_effect = float(raw_min_effect)
    if theta_eff:
        smallest_theta_eff = min(theta_eff.values())
        if not math.isclose(min_effect, smallest_theta_eff / 2.0, rel_tol=1e-12):
            raise PlannedTestSettingsError(
                "min_effect is not half the smaller theta_eff (paper A.8: theta_PC / 2)"
            )

    # min_reports
    raw_min_reports = values.get("min_reports")
    if isinstance(raw_min_reports, bool) or not isinstance(raw_min_reports, int) or raw_min_reports < 1:
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} value 'min_reports' must be an "
            "integer >= 1"
        )
    min_reports = raw_min_reports

    # snr
    raw_snr = values.get("snr")
    if not isinstance(raw_snr, dict):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} value 'snr' must be an object"
        )
    snr: dict[str, float] = {}
    for proc in PROCESSORS:
        v = raw_snr.get(proc)
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v <= 0
        ):
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} value 'snr.{proc}' must be a "
                "positive finite number"
            )
        snr[proc] = float(v)

    # principal_components
    raw_pcs = values.get("principal_components")
    if not isinstance(raw_pcs, dict):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} value 'principal_components' must be "
            "an object"
        )
    principal_components: dict[str, PcRef] = {}
    for proc in PROCESSORS:
        ref = raw_pcs.get(proc)
        if not isinstance(ref, dict):
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} value 'principal_components."
                f"{proc}' must be an object"
            )
        p = ref.get("path")
        sha = ref.get("sha256")
        if not isinstance(p, str) or not p:
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} value 'principal_components."
                f"{proc}.path' must be a non-empty string"
            )
        if not isinstance(sha, str) or not _HEX64.fullmatch(sha):
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} value 'principal_components."
                f"{proc}.sha256' must be 64 lowercase hex characters"
            )
        pc_path = resolve(p)
        if not pc_path.is_file():
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} references a missing principal-"
                f"component file {p!r}"
            )
        if file_sha256(pc_path) != sha:
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} references principal-component "
                f"file {p!r} whose sha256 does not match the recorded value"
            )
        principal_components[proc] = PcRef(path=p, sha256=sha)

    # excluded_seeds
    prelim = inputs.get("preliminary")
    if not isinstance(prelim, dict) or not isinstance(prelim.get("seed"), int) or isinstance(prelim.get("seed"), bool):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} inputs.preliminary.seed must be an "
            "integer"
        )
    seeds: set[int] = {prelim["seed"]}
    pilot_inputs = inputs.get("pilots")
    if not isinstance(pilot_inputs, list):
        raise PlannedTestSettingsError(
            f"settings record {str(path)!r} inputs.pilots must be a list"
        )
    for pilot in pilot_inputs:
        if not isinstance(pilot, dict) or not isinstance(pilot.get("seed"), int) or isinstance(pilot.get("seed"), bool):
            raise PlannedTestSettingsError(
                f"settings record {str(path)!r} every inputs.pilots entry must "
                "have an integer seed"
            )
        seeds.add(pilot["seed"])

    return PlannedTestSettings(
        path=str(path),
        record_sha256=record_sha256,
        t_learn_s=t_learn_s,
        theta_eff=theta_eff,
        min_effect=min_effect,
        min_reports=min_reports,
        snr=snr,
        principal_components=principal_components,
        excluded_seeds=frozenset(seeds),
    )


def planned_test_gate(
    study: str | None,
    config: Mapping[str, Any],
    seed: int,
) -> tuple[str | None, str | None]:
    """Return a refusal reason and the settings digest, or ``(None, None)``.

    A live run of the planned test needs the settings derived from the pilot
    runs (paper Appendix A.8). This function checks the study name, the role,
    the settings record, and the seed before the boot proceeds.
    """
    planned_test = config.get("planned_test")
    role = None
    if planned_test is not None:
        if not isinstance(planned_test, dict):
            return (
                f"[planned_test] must be a table, got {type(planned_test).__name__!r}",
                None,
            )
        role = planned_test.get("role")

    if study is not None and study.startswith(STUDY_PREFIX):
        if study not in STUDY_ROLES:
            known = ", ".join(sorted(STUDY_ROLES))
            return (
                f"unknown workspace-mediation study {study!r}; known studies are {known}",
                None,
            )
        expected_role = STUDY_ROLES[study]
        if role != expected_role:
            return (
                f"study {study!r} must set [planned_test].role = {expected_role!r}, got {role!r}",
                None,
            )

    if role is not None and role not in ROLES:
        return (
            f"planned_test role {role!r} is not one of {ROLES!r}",
            None,
        )

    if role is None:
        return (None, None)

    if role in ("preliminary", "pilot"):
        return (None, None)

    settings_record = (
        planned_test.get("settings_record") if isinstance(planned_test, dict) else None
    )
    if not isinstance(settings_record, str) or not settings_record:
        return (
            f"study {study!r} with role {role!r} needs the settings record "
            "derived from the pilot runs (paper Appendix A.8); run "
            "python -m kaine.experiment.calibrate",
            None,
        )

    try:
        settings = load_settings_record(settings_record)
    except PlannedTestSettingsError as exc:
        return (
            f"study {study!r} cannot start without a valid planned-test "
            f"settings record: {exc}",
            None,
        )

    if seed in settings.excluded_seeds:
        return (
            f"seed {seed} was used by the preliminary or a pilot run and is not "
            "used again (paper A.8)",
            None,
        )

    if role == "test":
        pc = config.get("positive_control")
        if (
            isinstance(pc, dict)
            and pc.get("enabled") is True
            and pc.get("mode") != "control"
        ):
            mode = pc.get("mode")
            return (
                f"a live test run may not carry the positive control in mode {mode!r}; "
                "only mode control",
                None,
            )

    if role == "positive_control":
        pc = config.get("positive_control")
        if (
            not isinstance(pc, dict)
            or pc.get("enabled") is not True
            or pc.get("mode") != "control"
            or pc.get("settings_record") != settings_record
        ):
            return (
                f"study {study!r} [positive_control] must enable control mode "
                "and use the same settings_record as [planned_test]",
                None,
            )

    return (None, settings.record_sha256)


def planned_test_refusal(
    study: str | None,
    config: Mapping[str, Any],
    seed: int,
) -> str | None:
    """Return a one-line refusal reason, or ``None`` if the boot may proceed."""
    return planned_test_gate(study, config, seed)[0]
