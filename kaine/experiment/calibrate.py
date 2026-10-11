# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The calibration tool of the planned test.

``python -m kaine.experiment.calibrate PLAN --out PATH [--root data/evaluation]``

reads the preliminary run and the pilot runs named in PLAN and writes one
settings record. It applies the rules from the paper's Appendix A.8,
"Settings from the pilot runs":

* pilot classification (not-exercised replacement and r_NE)
* learning period via MSER-5 over ensemble-averaged processor gains
* minimum effects from the on-versus-control contrasts
* the tone bins and both tone minimum effects from the tone-variant pilot runs
* positive-control SNR and report count from the competitive ladder; s2_j
  is the larger of the two components' variances at the two ladder rungs
  that bracket SNR_j, which approximates the variance at SNR_j itself
* contrast-at-threshold bandwidth, age bins, per-pilot contrast and minimum
  effect from the competitive pilots
* nothing is always blocked any more

A rule that cannot be applied fails closed: its value is null, ``blocked``
gives the reason, ``complete`` is ``False``, and the boot check refuses a live
run with it.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kaine
from kaine.experiment import calibration_rules as rules
from kaine.experiment.calibration_rules import (
    ALPHA_PC,
    ALPHA_TEST,
    BETA_PC,
    C_EFF,
    MSER_BATCH,
    N_BINS,
    N_CAL,
    POWER_HORIZON,
    Q_POW,
    SNR_LADDER,
    TARGET_POWER,
    UCL_LEVEL,
    CalibrationError,
    browne_ucl_factor,
    control_min_reports,
    detection_z,
    ensemble_average,
    interpolate_snr,
    minimum_effect,
    mser_truncation,
    planned_run_count,
    quintile_edges,
    sample_sd,
    sign_test_critical_count,
    sign_test_power,
    stable_run_count,
)
from kaine.experiment.planned_test_settings import (
    SCHEMA,
    SCHEMA_VERSION,
    records_digest,
    write_settings_record,
)
from kaine.experiment.principal_component import (
    file_sha256,
    load_principal_component,
    principal_component_path,
)
from kaine.experiment.rd_robust import RDError, mse_bandwidths
from kaine.experiment.run_context import compute_git_sha
from kaine.experiment.run_records import DEFAULT_ROOT, RunRecords, load_records_for_runs
from kaine.experiment.threshold_contrast import (
    ThresholdContrastError,
    bandwidth_observations,
    near_threshold_ages,
    run_contrast,
)
from kaine.experiment.tone_analysis import (
    ToneAnalysisError,
    ToneEvent,
    adjusted_statistic,
    run_statistic,
    tone_events,
)
from kaine.storage import resolve

TOOL_NAME = "kaine.experiment.calibrate"
TOOL_VERSION = "1"
ARMS = ("competitive", "matched", "pooled")
CONTROLS = ("matched", "pooled")
TONE = "tone"
PROCESSORS = ("topos", "audition", "soma")
REPORT_TYPES = {
    "topos": "topos.report",
    "audition": "audition.perception",
    "soma": "soma.report",
}
PRELIMINARY_STUDY = "workspace_mediation_preliminary"
PILOT_STUDIES = {
    "competitive": "workspace_mediation_pilot_competitive",
    "matched": "workspace_mediation_pilot_matched",
    "pooled": "workspace_mediation_pilot_pooled",
    "tone": "workspace_mediation_pilot_tone",
}

_DEFAULT = object()


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _flatten_records(run_records: RunRecords) -> Iterable[dict[str, Any]]:
    for records in run_records.by_stream.values():
        for record in records:
            yield record


def included_reports(
    records: Iterable[Mapping[str, Any]],
    processor: str,
    *,
    run_id: str,
) -> list[tuple[float, float]]:
    """Return included (entity_time_s, context_gain) reports for ``processor``.

    Reports are sorted by ``entity_time_s``. Raises ``CalibrationError`` when any
    report record of that type lacks a finite ``entity_time_s`` or a bool
    ``awake``.
    """
    report_type = REPORT_TYPES[processor]
    kept: list[tuple[float, float]] = []

    for record in records:
        if record.get("event_type") != report_type:
            continue

        ets = record.get("entity_time_s")
        if isinstance(ets, bool) or not isinstance(ets, (int, float)) or not math.isfinite(ets):
            raise CalibrationError(
                f"run {run_id!r} has a {processor} report with a missing or "
                "non-finite entity_time_s"
            )

        awake = record.get("awake")
        if not isinstance(awake, bool):
            raise CalibrationError(
                f"run {run_id!r} has a {processor} report with a missing or "
                "non-bool awake"
            )

        gain = record.get("context_gain")
        if awake and _is_finite_number(gain):
            kept.append((float(ets), float(gain)))

    kept.sort(key=lambda item: item[0])
    return kept


def information_gain(
    reports: Mapping[str, Sequence[tuple[float, float]]],
    t_learn_s: float,
) -> dict[str, float | None]:
    """Mean context gain strictly after ``t_learn_s`` per processor.

    Returns ``None`` for a processor with no reports after the learning period.
    """
    result: dict[str, float | None] = {}
    for processor in PROCESSORS:
        after = [gain for time_s, gain in reports.get(processor, ()) if time_s > t_learn_s]
        result[processor] = sum(after) / len(after) if after else None
    return result


def headline(ig: Mapping[str, float | None]) -> float | None:
    """Mean of the three processor information gains.

    Returns ``None`` when any processor is undefined so that a processor that
    reports often does not outweigh one that reports rarely.
    """
    values = [ig.get(p) for p in PROCESSORS]
    if any(value is None for value in values):
        return None
    return sum(values) / len(values)  # type: ignore[arg-type]


def not_exercised_reason(broadcasts: Sequence[Mapping[str, Any]]) -> str | None:
    """Classify whether the competitive arm's broadcasts actually exercised it.

    Returns ``None`` when competition both operated and was accessed. Raises
    ``CalibrationError`` for malformed broadcast records.
    """
    operated = False
    accessed = False

    for record in broadcasts:
        capacity = record.get("coalition_capacity")
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise CalibrationError(
                "broadcast record has a missing or non-int coalition_capacity"
            )

        scores = record.get("salience_scores")
        if not isinstance(scores, dict):
            raise CalibrationError(
                "broadcast record has a missing or non-dict salience_scores"
            )

        inhibited = record.get("inhibited")
        if not isinstance(inhibited, bool):
            raise CalibrationError(
                "broadcast record has a missing or non-bool inhibited"
            )

        if len(scores) > capacity:
            operated = True
        if not inhibited:
            accessed = True

    if not operated:
        return "competition never operated"
    if not accessed:
        return "no accessed broadcast"
    return None


def learning_period(
    per_arm_reports: Mapping[
        str, Sequence[Mapping[str, Sequence[tuple[float, float]]]]
    ],
    *,
    ignore_end: int | None,
) -> tuple[int | None, dict[str, Any], str | None]:
    """Return the learning period T_learn in entity seconds.

    ``per_arm_reports[arm]`` is a list over the counted pilots of
    ``{processor: included reports}``. The MSER-5 search runs over
    0 <= d <= b - ignore_end (paper Appendix A.8). When any arm or processor
    has too few batch means for the search to reach the second half, or when
    the truncation point lies in the second half, the pilot runs are too short.
    """
    if ignore_end is None:
        return (
            None,
            {},
            (
                "The MSER-5 search range is not set (ignore_end is None). "
                "The learning period, and every setting that counts reports after it, "
                "is blocked until ignore_end is configured."
            ),
        )

    import statistics

    details: dict[str, Any] = {}
    max_time = 0.0
    failures: list[str] = []

    try:
        for arm in ARMS:
            arm_details: dict[str, Any] = {}
            pilots = per_arm_reports[arm]

            for processor in PROCESSORS:
                series = [
                    [gain for _time_s, gain in pilot[processor]]
                    for pilot in pilots
                ]
                averaged = ensemble_average(series, batch=MSER_BATCH)
                result = mser_truncation(
                    averaged,
                    ignore_end=ignore_end,
                    min_batches=rules.MSER_MIN_BATCHES,
                )

                proc_details: dict[str, Any] = {
                    "n_values": result.n_values,
                    "n_batches": result.n_batches,
                    "d_star": result.d_star,
                    "truncated_report": result.truncated_report,
                }

                if result.truncated_report == 0:
                    median_time = 0.0
                else:
                    idx = result.truncated_report - 1
                    times = [
                        pilot[processor][idx][0]
                        for pilot in pilots
                        if len(pilot[processor]) > idx
                    ]
                    if len(times) != len(pilots):
                        raise CalibrationError(
                            f"truncation report index {result.truncated_report} "
                            f"exceeds available reports for {arm}/{processor}"
                        )
                    median_time = statistics.median(times)

                proc_details["median_time_s"] = median_time
                arm_details[processor] = proc_details

                if not result.long_enough:
                    failures.append(
                        f"fewer than {rules.MSER_MIN_BATCHES} batch means for "
                        f"{arm}/{processor} (b = {result.n_batches})"
                    )
                elif not result.first_half:
                    failures.append(f"d* > b/2 for {arm}/{processor}")

                if median_time > max_time:
                    max_time = median_time

            details[arm] = arm_details
    except CalibrationError as exc:
        return None, details, str(exc)

    if failures:
        return (
            None,
            details,
            "; ".join(failures) + ": the pilot runs are too short (paper A.8)",
        )

    return math.ceil(max_time), details, None


def ladder_effects(
    records: Iterable[Mapping[str, Any]],
    processor: str,
    t_learn_s: float,
    *,
    run_id: str,
    pc_sha256: str,
) -> tuple[list[float], list[float], int]:
    """Return informative and uninformative effects per SNR rung.

    Effects are means over the ladder records of ``processor`` with
    ``entity_time_s > t_learn_s``. Raises ``CalibrationError`` for malformed
    ladder records or a ladder that did not finish cleanly.
    """
    records = list(records)
    informative: list[list[float]] = [[] for _ in SNR_LADDER]
    uninformative: list[list[float]] = [[] for _ in SNR_LADDER]
    n_records = 0

    for record in records:
        if (
            record.get("event_type") != "positive_control.ladder"
            or record.get("processor") != processor
        ):
            continue

        time_s = record.get("entity_time_s")
        if (
            isinstance(time_s, bool)
            or not isinstance(time_s, (int, float))
            or not math.isfinite(time_s)
        ):
            raise CalibrationError(
                f"run {run_id!r} processor {processor} ladder record has a "
                "missing or non-finite entity_time_s"
            )

        snr = record.get("snr")
        if snr != list(SNR_LADDER):
            raise CalibrationError(
                f"run {run_id!r} processor {processor} ladder record has an "
                "unexpected snr list"
            )

        gain = record.get("gain")
        if not _is_finite_number(gain):
            raise CalibrationError(
                f"run {run_id!r} processor {processor} ladder record has a "
                "non-finite gain"
            )

        gain_with = record.get("gain_with")
        gain_noise = record.get("gain_noise")
        if (
            not isinstance(gain_with, list)
            or len(gain_with) != len(SNR_LADDER)
            or not isinstance(gain_noise, list)
            or len(gain_noise) != len(SNR_LADDER)
        ):
            raise CalibrationError(
                f"run {run_id!r} processor {processor} ladder record must "
                "contain 7-element gain_with and gain_noise lists"
            )

        for value in gain_with:
            if not _is_finite_number(value):
                raise CalibrationError(
                    f"run {run_id!r} processor {processor} ladder record has a "
                    "non-finite gain_with value"
                )

        for value in gain_noise:
            if not _is_finite_number(value):
                raise CalibrationError(
                    f"run {run_id!r} processor {processor} ladder record has a "
                    "non-finite gain_noise value"
                )

        if record.get("pc_sha256") != pc_sha256:
            raise CalibrationError(
                f"run {run_id!r} processor {processor} ladder record uses a "
                "different principal component"
            )

        if time_s <= t_learn_s:
            continue

        for i, value in enumerate(gain_with):
            informative[i].append(float(value) - float(gain))

        for i, value in enumerate(gain_noise):
            uninformative[i].append(float(value) - float(gain))

        n_records += 1

    if n_records == 0:
        raise CalibrationError(
            f"run {run_id!r} processor {processor} has no ladder records after "
            "the learning period"
        )

    results = [
        record
        for record in records
        if record.get("event_type") == "positive_control.result"
        and record.get("processor") == processor
        and record.get("mode") == "ladder"
    ]

    failed = any(record.get("failed") is True for record in results)
    finals = [record for record in results if record.get("final") is True]
    if (
        failed
        or len(finals) != 1
        or not results
        or results[-1].get("final") is not True
    ):
        raise CalibrationError(
            f"the ladder of run {run_id!r} for processor {processor} did not "
            "finish cleanly"
        )

    informative_means = [
        sum(vals) / len(vals) if vals else 0.0 for vals in informative
    ]
    uninformative_means = [
        sum(vals) / len(vals) if vals else 0.0 for vals in uninformative
    ]
    return informative_means, uninformative_means, n_records


def calibrate(
    plan: Mapping[str, Any],
    *,
    root: Path | str = DEFAULT_ROOT,
    n_cal: int = N_CAL,
    mser_ignore_end: int | None | object = _DEFAULT,
    now: str | None = None,
) -> dict[str, Any]:
    """Build the planned-test settings record from ``plan`` without its digest."""
    # Read MSER_IGNORE_END at call time from the rules module.
    if mser_ignore_end is _DEFAULT:
        mser_ignore_end = rules.MSER_IGNORE_END

    # The record stores the principal-component paths as given (relative to the
    # data root), so no operator path enters the committed record.
    given_root = Path(root)
    root = resolve(given_root)

    # ------------------------------------------------------------------
    # a. Validate the plan and load all runs once
    # ------------------------------------------------------------------
    # Reject lists or strings before calling .get() so the CLI exits cleanly.
    if not isinstance(plan, dict):
        raise CalibrationError(
            "the plan must be a JSON object with preliminary_run and pilots"
        )
    preliminary_run = plan.get("preliminary_run")
    if not isinstance(preliminary_run, str) or not preliminary_run:
        raise CalibrationError("plan preliminary_run must be a non-empty string")

    pilots = plan.get("pilots")
    if not isinstance(pilots, list) or not pilots:
        raise CalibrationError("plan pilots must be a non-empty list")

    seen: set[str] = {preliminary_run}
    has_tone = isinstance(pilots[0], dict) and TONE in pilots[0]
    pilot_keys = ARMS + ((TONE,) if has_tone else ())
    for index, pilot in enumerate(pilots):
        if (
            not isinstance(pilot, dict)
            or set(pilot.keys()) != set(pilot_keys)
        ):
            raise CalibrationError(
                f"pilot {index} must contain exactly the arms {ARMS!r}, "
                "and the tone variant in every pilot or in none"
            )
        for key, run_id in pilot.items():
            if not isinstance(run_id, str) or not run_id or run_id in seen:
                raise CalibrationError(
                    f"duplicate or invalid run id {run_id!r} in pilot {index}"
                )
            seen.add(run_id)

    run_ids = [preliminary_run] + [
        pilot[key] for pilot in pilots for key in pilot_keys
    ]
    records_by_run = load_records_for_runs(run_ids, root=root)

    for run_id in run_ids:
        run_records = records_by_run[run_id]
        total = sum(len(records) for records in run_records.by_stream.values())
        if total == 0 or run_records.parse_errors > 0:
            raise CalibrationError(
                f"run {run_id!r} has no records or parse errors"
            )

    manifests: dict[str, dict[str, Any]] = {}
    manifest_sha: dict[str, str] = {}
    for run_id in run_ids:
        manifest_path = root / "runs" / run_id / "manifest.json"
        try:
            manifest_sha[run_id] = file_sha256(manifest_path)
            with manifest_path.open("r", encoding="utf-8") as fh:
                manifests[run_id] = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationError(
                f"run {run_id!r} manifest is missing or invalid: {exc}"
            ) from exc

    pre_manifest = manifests[preliminary_run]
    if pre_manifest.get("study") != PRELIMINARY_STUDY:
        raise CalibrationError(
            f"preliminary run {preliminary_run!r} has study "
            f"{pre_manifest.get('study')!r}, expected {PRELIMINARY_STUDY!r}"
        )

    pre_seed = pre_manifest.get("seed")
    if isinstance(pre_seed, bool) or not isinstance(pre_seed, int):
        raise CalibrationError(
            f"preliminary run {preliminary_run!r} manifest seed must be an int"
        )

    for index, pilot in enumerate(pilots):
        for key in pilot_keys:
            run_id = pilot[key]
            manifest = manifests[run_id]
            actual_study = manifest.get("study")
            expected_study = PILOT_STUDIES[key]
            if actual_study != expected_study:
                raise CalibrationError(
                    f"run {run_id!r} has study {actual_study!r}, "
                    f"expected {expected_study!r}"
                )

            seed = manifest.get("seed")
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise CalibrationError(
                    f"run {run_id!r} manifest seed must be an int"
                )

    pilot_seeds: list[int] = []
    for index, pilot in enumerate(pilots):
        seeds = {manifests[pilot[key]].get("seed") for key in pilot_keys}
        if len(seeds) != 1:
            raise CalibrationError(
                f"pilot {index} runs do not share a single seed"
            )
        pilot_seeds.append(next(iter(seeds)))

    if len(set(pilot_seeds)) != len(pilot_seeds):
        raise CalibrationError("two pilots share a seed")

    if pre_seed in pilot_seeds:
        raise CalibrationError(
            "the preliminary seed must differ from every pilot seed"
        )

    perception_feed = pre_manifest.get("perception_feed")
    for run_id in run_ids:
        if manifests[run_id].get("perception_feed") != perception_feed:
            raise CalibrationError(
                f"run {run_id!r} does not use the same perception_feed as the "
                "preliminary run"
            )

    pilot_arm_for_run: dict[str, str] = {}
    pilot_key_for_run: dict[str, str] = {}
    for pilot in pilots:
        for key, run_id in pilot.items():
            pilot_arm_for_run[run_id] = "competitive" if key == TONE else key
            pilot_key_for_run[run_id] = key

    for run_id, arm in pilot_arm_for_run.items():
        key = pilot_key_for_run[run_id]
        for record in _flatten_records(records_by_run[run_id]):
            if record.get("event_type") == "workspace.broadcast":
                if record.get("arm") != arm:
                    raise CalibrationError(
                        f"run {run_id!r} has a broadcast with arm "
                        f"{record.get('arm')!r}, expected {arm!r}"
                    )
            # The three arms run the categorical tone rule (paper A.2); only the
            # tone variant runs A.8's rule.
            if (
                record.get("event_type") == "audition.emotion"
                and key != TONE
                and record.get("tone_rule") == "error_ratio"
            ):
                raise CalibrationError(
                    f"run {run_id!r} is a {key} pilot but its tone events "
                    "carry tone_rule 'error_ratio', the tone variant's rule"
                )

    inputs: dict[str, Any] = {
        "preliminary": {
            "run_id": preliminary_run,
            "seed": pre_seed,
            "manifest_sha256": manifest_sha[preliminary_run],
            "records_sha256": records_digest(records_by_run[preliminary_run]),
        },
        "pilots": [],
    }
    for index, pilot in enumerate(pilots):
        entry: dict[str, Any] = {
            "seed": pilot_seeds[index],
            "counted": None,
            "not_exercised_reason": None,
            "runs": {},
        }
        for key in pilot_keys:
            run_id = pilot[key]
            entry["runs"][key] = {
                "run_id": run_id,
                "manifest_sha256": manifest_sha[run_id],
                "records_sha256": records_digest(records_by_run[run_id]),
            }
        inputs["pilots"].append(entry)

    # ------------------------------------------------------------------
    # b. Principal components from the preliminary run
    # ------------------------------------------------------------------
    principal_components: dict[str, Any] = {}
    for processor in PROCESSORS:
        pc_path = principal_component_path(
            root / "positive_control", preliminary_run, processor
        )
        record_path = principal_component_path(
            given_root / "positive_control", preliminary_run, processor
        )
        try:
            pc = load_principal_component(pc_path)
        except Exception as exc:
            raise CalibrationError(
                f"cannot load principal component for {processor}: {exc}"
            ) from exc

        if pc.run_id != preliminary_run or pc.processor != processor:
            raise CalibrationError(
                f"principal component for {processor} does not match the "
                "preliminary run"
            )

        principal_components[processor] = {
            "path": str(record_path),
            "sha256": file_sha256(pc_path),
            "dim": pc.dim,
            "n_inputs": pc.n_inputs,
            "variance": pc.variance,
        }

    # ------------------------------------------------------------------
    # c. Classification of pilots
    # ------------------------------------------------------------------
    pilot_arm_reports: list[dict[str, dict[str, list[tuple[float, float]]]]] = []
    n_counted = 0
    n_not_exercised = 0
    counted_indices: list[int] = []

    for index, pilot in enumerate(pilots):
        arm_reports: dict[str, dict[str, list[tuple[float, float]]]] = {}
        for arm in ARMS:
            arm_reports[arm] = {}
            run_id = pilot[arm]
            for processor in PROCESSORS:
                arm_reports[arm][processor] = included_reports(
                    _flatten_records(records_by_run[run_id]),
                    processor,
                    run_id=run_id,
                )

        competitive_run_id = pilot["competitive"]
        broadcasts = [
            record
            for record in _flatten_records(records_by_run[competitive_run_id])
            if record.get("event_type") == "workspace.broadcast"
        ]
        ne_reason = not_exercised_reason(broadcasts)

        all_gains = {
            arm: headline(information_gain(arm_reports[arm], float("-inf")))
            for arm in ARMS
        }
        if any(value is None for value in all_gains.values()):
            if ne_reason is None:
                ne_reason = "the gain is undefined"

        inputs["pilots"][index]["not_exercised_reason"] = ne_reason
        inputs["pilots"][index]["counted"] = ne_reason is None

        if ne_reason is None:
            n_counted += 1
            counted_indices.append(index)
        else:
            n_not_exercised += 1

        pilot_arm_reports.append(arm_reports)

        if n_counted >= n_cal and index < len(pilots) - 1:
            raise CalibrationError(
                "the plan lists a pilot after the counted pilots were already "
                "selected"
            )

    n_attempted = len(pilots)
    r_ne = n_not_exercised / n_attempted if n_attempted else 0.0
    n_exact = stable_run_count(
        q=Q_POW, target=TARGET_POWER, alpha=ALPHA_TEST, horizon=POWER_HORIZON
    )
    k_n_exact = sign_test_critical_count(n_exact)
    power_at_n_exact = float(sign_test_power(n_exact))

    try:
        n_run_planned = planned_run_count(n_exact, n_not_exercised, n_attempted)
    except CalibrationError as exc:
        n_run_planned = None
        blocked_n_run_planned = str(exc)
    else:
        blocked_n_run_planned = None

    # ------------------------------------------------------------------
    # Report-rate check (recorded for inspection only; the paper has no
    # rule on report rates and nothing is blocked on them).  It lets a
    # reader see whether the on arm's pilots, which also carry the
    # positive control's ladder, reported at another cadence
    # (paper §6.3: "Three arms run on the same film program with the
    # same seeds and calibration").
    # ------------------------------------------------------------------
    report_rates: dict[str, dict[str, list[float]]] | None = None
    report_rate_check: dict[str, dict[str, dict[str, Any]]] | None = None

    if n_counted >= n_cal:
        report_rates = {
            arm: {processor: [] for processor in PROCESSORS} for arm in ARMS
        }

        for index in counted_indices:
            for arm in ARMS:
                run_id = pilots[index][arm]
                for processor in PROCESSORS:
                    times: list[float] = []
                    for record in _flatten_records(records_by_run[run_id]):
                        if record.get("event_type") != REPORT_TYPES[processor]:
                            continue
                        ets = record.get("entity_time_s")
                        if (
                            isinstance(ets, bool)
                            or not isinstance(ets, (int, float))
                            or not math.isfinite(ets)
                        ):
                            raise CalibrationError(
                                f"run {run_id!r} has a {processor} report with a "
                                "missing or non-finite entity_time_s"
                            )
                        times.append(float(ets))
                    times.sort()
                    if len(times) < 2:
                        raise CalibrationError(
                            f"run {run_id!r} processor {processor} has fewer "
                            "than 2 reports"
                        )
                    span = times[-1] - times[0]
                    if span <= 0:
                        raise CalibrationError(
                            f"run {run_id!r} processor {processor} report span "
                            "is not above 0"
                        )
                    report_rates[arm][processor].append((len(times) - 1) / span)

        report_rate_check = {processor: {} for processor in PROCESSORS}

        for processor in PROCESSORS:
            on_rates = report_rates["competitive"][processor]
            for ctl in CONTROLS:
                ctl_rates = report_rates[ctl][processor]
                mean_on = sum(on_rates) / len(on_rates)
                mean_ctl = sum(ctl_rates) / len(ctl_rates)
                sd_ctl = sample_sd(ctl_rates)
                report_rate_check[processor][ctl] = {
                    "mean_on": mean_on,
                    "mean_ctl": mean_ctl,
                    "sd_ctl": sd_ctl,
                    "exceeds_control_sd": abs(mean_on - mean_ctl) > sd_ctl,
                }

    # ------------------------------------------------------------------
    # d. Learning period over the counted pilots
    # ------------------------------------------------------------------
    t_learn_s: int | None = None
    mser_details: dict[str, Any] | None = None

    if n_counted >= n_cal:
        per_arm_reports = {
            arm: [pilot_arm_reports[i][arm] for i in counted_indices]
            for arm in ARMS
        }
        t_learn_s, mser_details, learn_reason = learning_period(
            per_arm_reports, ignore_end=mser_ignore_end
        )
    else:
        learn_reason = None

    # ------------------------------------------------------------------
    # e. Minimum effects
    # ------------------------------------------------------------------
    dig: dict[str, list[float]] | None = None
    s_cal: dict[str, float] | None = None
    theta_eff: dict[str, float] | None = None
    theta_pc: float | None = None
    min_effect: float | None = None
    min_effect_error_key: str | None = None
    min_effect_error_msg: str | None = None

    if n_counted >= n_cal and t_learn_s is not None:
        dig = {ctl: [] for ctl in CONTROLS}
        contrast_missing = False

        for index in counted_indices:
            on_ig = information_gain(
                pilot_arm_reports[index]["competitive"], t_learn_s
            )
            on_head = headline(on_ig)
            if on_head is None:
                contrast_missing = True
                break

            for ctl in CONTROLS:
                ctl_ig = information_gain(pilot_arm_reports[index][ctl], t_learn_s)
                ctl_head = headline(ctl_ig)
                if ctl_head is None:
                    contrast_missing = True
                    break
                dig[ctl].append(on_head - ctl_head)

            if contrast_missing:
                break

        if contrast_missing:
            dig = None

    if dig is not None:
        s_cal = {}
        theta_eff = {}
        for ctl in CONTROLS:
            try:
                sd = sample_sd(dig[ctl])
            except CalibrationError as exc:
                if min_effect_error_key is None:
                    min_effect_error_key = "s_cal"
                    min_effect_error_msg = str(exc)
                continue
            try:
                theta = minimum_effect(sd)
            except CalibrationError as exc:
                if min_effect_error_key is None:
                    min_effect_error_key = "theta_eff"
                    min_effect_error_msg = str(exc)
                continue
            s_cal[ctl] = sd
            theta_eff[ctl] = theta

        if min_effect_error_key is None:
            theta_pc = min(theta_eff.values())
            min_effect = theta_pc / 2.0
        else:
            s_cal = None
            theta_eff = None

    # ------------------------------------------------------------------
    # Tone analysis minimum effect
    # ------------------------------------------------------------------
    tone_statistics: list[float | None] | None = None
    min_effect_tone: float | None = None
    tone_error: str | None = None

    if not has_tone:
        tone_error = "the plan names no tone-variant pilot runs (paper A.8)"
    elif n_counted < n_cal:
        tone_error = "depends on pilots"
    else:
        stats: list[float | None] = []
        events_by_pilot: list[list[ToneEvent]] = []
        for index in counted_indices:
            run_id = pilots[index][TONE]
            try:
                events = tone_events(_flatten_records(records_by_run[run_id]))
                events_by_pilot.append(events)
                stats.append(run_statistic(events))
            except ToneAnalysisError as exc:
                tone_error = f"run {run_id!r}: {exc}"
                break
        if tone_error is None:
            tone_statistics = stats
            defined = [s for s in stats if s is not None]
            try:
                min_effect_tone = minimum_effect(sample_sd(defined))
            except CalibrationError as exc:
                tone_error = (
                    f"the tone statistic is defined in {len(defined)} "
                    f"counted pilots: {exc}"
                )

    tone_bins: list[float] | None = None
    tone_bins_error: str | None = None
    if tone_error is not None:
        tone_bins_error = tone_error
    else:
        try:
            tone_bins = quintile_edges(
                [e.error_ratio for events in events_by_pilot for e in events]
            )
        except CalibrationError as exc:
            tone_bins_error = f"tone bins: {exc}"

    tone_adjusted_statistics: list[float | None] | None = None
    min_effect_tone_adjusted: float | None = None
    tone_adjusted_error: str | None = None
    if tone_bins_error is not None:
        tone_adjusted_error = tone_bins_error
    else:
        tone_adjusted_statistics = [
            adjusted_statistic(events, tone_bins) for events in events_by_pilot
        ]
        defined_adjusted = [s for s in tone_adjusted_statistics if s is not None]
        try:
            min_effect_tone_adjusted = minimum_effect(sample_sd(defined_adjusted))
        except CalibrationError as exc:
            tone_adjusted_error = (
                f"the adjusted tone statistic is defined in {len(defined_adjusted)} "
                f"counted pilots: {exc}"
            )

    # ------------------------------------------------------------------
    # Contrast at threshold
    # ------------------------------------------------------------------
    theta_band: float | None = None
    b_band: float | None = None
    bandwidth_details: dict[str, Any] | None = None
    age_bins: list[float] | None = None
    threshold_contrasts: list[float | None] | None = None
    min_effect_threshold_contrast: float | None = None
    band_error: str | None = None
    age_bins_error: str | None = None
    contrast_error: str | None = None

    if n_counted < n_cal:
        band_error = "depends on pilots"
        age_bins_error = "depends on pilots"
        contrast_error = "depends on pilots"
    elif t_learn_s is None:
        band_error = "depends on t_learn_s"
        age_bins_error = "depends on t_learn_s"
        contrast_error = "depends on t_learn_s"
    else:
        x_all: list[float] = []
        y_all: list[float] = []
        try:
            for index in counted_indices:
                run_id = pilots[index]["competitive"]
                x, y = bandwidth_observations(
                    _flatten_records(records_by_run[run_id]), t_learn_s
                )
                x_all.extend(x)
                y_all.extend(y)
            sel = mse_bandwidths(x_all, y_all)
        except (RDError, ThresholdContrastError) as exc:
            band_error = f"theta_band: {exc}"
            age_bins_error = "depends on theta_band"
            contrast_error = "depends on theta_band"
        else:
            theta_band = sel.h
            b_band = sel.b
            bandwidth_details = {"v": sel.v, "c": sel.c, "n": sel.n}
            try:
                ages: list[float] = []
                for index in counted_indices:
                    run_id = pilots[index]["competitive"]
                    ages.extend(
                        near_threshold_ages(
                            _flatten_records(records_by_run[run_id]),
                            t_learn_s,
                            theta_band,
                        )
                    )
                age_bins = quintile_edges(ages)
            except (CalibrationError, ThresholdContrastError) as exc:
                age_bins_error = str(exc)
                contrast_error = "depends on age_bins"
            else:
                threshold_contrasts = []
                for index in counted_indices:
                    run_id = pilots[index]["competitive"]
                    threshold_contrasts.append(
                        run_contrast(
                            _flatten_records(records_by_run[run_id]),
                            t_learn_s,
                            theta_band,
                            b_band,
                            age_bins,
                        ).contrast
                    )
                defined = [c for c in threshold_contrasts if c is not None]
                try:
                    min_effect_threshold_contrast = minimum_effect(sample_sd(defined))
                except CalibrationError as exc:
                    contrast_error = (
                        f"the threshold contrast is defined in {len(defined)} "
                        f"counted pilots: {exc}"
                    )

    # ------------------------------------------------------------------
    # f. Positive control and report count
    # s2_j is the larger of the two components' variances at the two ladder
    # rungs that bracket SNR_j; this approximates the variance at SNR_j itself,
    # because run-level variances are measured only on the ladder's rungs.
    # ------------------------------------------------------------------
    ladder_mean_effect: dict[str, Any] | None = None
    snr: dict[str, float] | None = None
    s2: dict[str, float] | None = None
    n_bar: dict[str, float] | None = None
    n_pc: dict[str, int] | None = None
    min_reports: int | None = None
    ucl_factor: float | None = None
    detection_z_value: float | None = None
    snr_error: str | None = None

    if theta_pc is not None:
        local_ladder_mean_effect: dict[str, Any] = {}
        local_snr: dict[str, float] = {}
        local_s2: dict[str, float] = {}
        local_n_bar: dict[str, float] = {}
        local_n_pc: dict[str, int] = {}

        for processor in PROCESSORS:
            informative_series: list[list[float]] = []
            uninformative_series: list[list[float]] = []
            counts: list[int] = []

            for index in counted_indices:
                run_id = pilots[index]["competitive"]
                try:
                    informative, uninformative, count = ladder_effects(
                        _flatten_records(records_by_run[run_id]),
                        processor,
                        t_learn_s,  # type: ignore[arg-type]
                        run_id=run_id,
                        pc_sha256=principal_components[processor]["sha256"],
                    )
                except CalibrationError as exc:
                    snr_error = f"{processor}: {exc}"
                    break
                informative_series.append(informative)
                uninformative_series.append(uninformative)
                counts.append(count)

            if snr_error is not None:
                break

            mean_informative = [
                sum(pilot[i] for pilot in informative_series) / len(informative_series)
                for i in range(len(SNR_LADDER))
            ]
            mean_uninformative = [
                sum(pilot[i] for pilot in uninformative_series) / len(uninformative_series)
                for i in range(len(SNR_LADDER))
            ]

            local_ladder_mean_effect[processor] = {
                "informative": mean_informative,
                "uninformative": mean_uninformative,
            }
            local_n_bar[processor] = sum(counts) / len(counts)

            try:
                choice = interpolate_snr(SNR_LADDER, mean_informative, theta_pc)
                local_snr[processor] = choice.snr

                variances = []
                for idx in (choice.lower_index, choice.upper_index):
                    inf_values = [pilot[idx] for pilot in informative_series]
                    noise_values = [pilot[idx] for pilot in uninformative_series]
                    variances.append(sample_sd(inf_values) ** 2)
                    variances.append(sample_sd(noise_values) ** 2)

                local_s2[processor] = max(variances)
                local_n_pc[processor] = control_min_reports(
                    local_n_bar[processor], local_s2[processor], theta_pc, n_cal=n_cal
                )
            except CalibrationError as exc:
                snr_error = f"{processor}: {exc}"
                break

        if snr_error is None:
            ladder_mean_effect = local_ladder_mean_effect
            snr = local_snr
            s2 = local_s2
            n_bar = local_n_bar
            n_pc = local_n_pc
            min_reports = max(n_pc.values())
            ucl_factor = browne_ucl_factor(n_cal)
            detection_z_value = detection_z()
        else:
            ladder_mean_effect = local_ladder_mean_effect
            n_bar = local_n_bar

    # ------------------------------------------------------------------
    # g. Always-blocked values and blocked-chain bookkeeping
    # ------------------------------------------------------------------
    blocked: dict[str, str] = {}

    def _chain_after(first_key: str) -> None:
        order = [
            "pilots",
            "t_learn_s",
            "s_cal",
            "theta_eff",
            "theta_pc",
            "min_effect",
            "snr",
            "min_reports",
        ]
        idx = order.index(first_key)
        for later in order[idx + 1 :]:
            blocked[later] = f"depends on {first_key}"

    if n_counted < n_cal:
        blocked["pilots"] = f"{n_counted} of {n_cal} pilot runs count"
        _chain_after("pilots")
    elif learn_reason is not None:
        blocked["t_learn_s"] = learn_reason
        _chain_after("t_learn_s")
    elif dig is None:
        blocked["s_cal"] = (
            "a counted pilot's contrast is undefined after T_learn; more pilots "
            "are needed"
        )
        _chain_after("s_cal")
    elif min_effect_error_key is not None:
        blocked[min_effect_error_key] = min_effect_error_msg
        _chain_after(min_effect_error_key)
    elif snr_error is not None:
        blocked["snr"] = snr_error
        blocked["min_reports"] = "depends on snr"

    if blocked_n_run_planned is not None:
        blocked["n_run_planned"] = blocked_n_run_planned

    if band_error is not None:
        blocked["theta_band"] = band_error
        blocked["b_band"] = band_error
    if age_bins_error is not None:
        blocked["age_bins"] = age_bins_error
    if contrast_error is not None:
        blocked["min_effect_threshold_contrast"] = contrast_error
    if tone_bins_error is not None:
        blocked["tone_bins"] = tone_bins_error
    if tone_adjusted_error is not None:
        blocked["min_effect_tone_adjusted"] = tone_adjusted_error
    if tone_error is not None:
        blocked["min_effect_tone"] = tone_error

    values: dict[str, Any] = {
        "principal_components": principal_components,
        "n_attempted": n_attempted,
        "n_not_exercised": n_not_exercised,
        "n_counted": n_counted,
        "r_ne": r_ne,
        "n_exact": n_exact,
        "k_n_exact": k_n_exact,
        "power_at_n_exact": power_at_n_exact,
        "n_run_planned": n_run_planned,
        "report_rates": report_rates,
        "report_rate_check": report_rate_check,
        "t_learn_s": t_learn_s,
        "mser": mser_details,
        "dig": dig,
        "s_cal": s_cal,
        "theta_eff": theta_eff,
        "theta_pc": theta_pc,
        "min_effect": min_effect,
        "ladder_mean_effect": ladder_mean_effect,
        "snr": snr,
        "s2": s2,
        "n_bar": n_bar,
        "n_pc": n_pc,
        "min_reports": min_reports,
        "ucl_factor": ucl_factor,
        "detection_z": detection_z_value,
        "theta_band": theta_band,
        "b_band": b_band,
        "bandwidth_selection": bandwidth_details,
        "age_bins": age_bins,
        "threshold_contrasts": threshold_contrasts,
        "min_effect_threshold_contrast": min_effect_threshold_contrast,
        "tone_bins": tone_bins,
        "tone_statistics": tone_statistics,
        "min_effect_tone": min_effect_tone,
        "tone_adjusted_statistics": tone_adjusted_statistics,
        "min_effect_tone_adjusted": min_effect_tone_adjusted,
    }

    created_at = now or datetime.now(timezone.utc).isoformat()

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "tool": {
            "name": TOOL_NAME,
            "version": TOOL_VERSION,
            "kaine_version": getattr(kaine, "__version__", ""),
            "git_sha": compute_git_sha(),
        },
        "created_at": created_at,
        "complete": not blocked,
        "blocked": blocked,
        "constants": {
            "c_eff": C_EFF,
            "n_cal": n_cal,
            "q_pow": float(Q_POW),
            "target_power": float(TARGET_POWER),
            "alpha_test": float(ALPHA_TEST),
            "alpha_pc": ALPHA_PC,
            "beta_pc": BETA_PC,
            "ucl_level": UCL_LEVEL,
            "mser_batch": MSER_BATCH,
            "mser_ignore_end": mser_ignore_end,
            "mser_min_batches": rules.MSER_MIN_BATCHES,
            "n_bins": N_BINS,
            "snr_ladder": list(SNR_LADDER),
            "power_horizon": POWER_HORIZON,
        },
        "inputs": inputs,
        "values": values,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Calibrate the planned test from pilot runs."
    )
    parser.add_argument("plan", type=Path, help="path to the plan JSON file")
    parser.add_argument("--out", required=True, type=Path, help="output record path")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        type=Path,
        help="evaluation root directory",
    )
    args = parser.parse_args(argv)

    try:
        with args.plan.open("r", encoding="utf-8") as fh:
            plan = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"calibration failed: {exc}", file=sys.stderr)
        return 2

    try:
        record = calibrate(plan, root=args.root)
    except CalibrationError as exc:
        print(f"calibration failed: {exc}", file=sys.stderr)
        return 2

    digest = write_settings_record(record, args.out)
    print(f"wrote {args.out}")
    print(f"record_sha256 {digest}")
    print("put this record_sha256 in the preregistration")

    values = record["values"]
    print(f"t_learn_s={values.get('t_learn_s')}")
    print(f"theta_eff={values.get('theta_eff')}")
    print(f"theta_pc={values.get('theta_pc')}")
    print(f"min_effect={values.get('min_effect')}")
    print(f"snr={values.get('snr')}")
    print(f"min_reports={values.get('min_reports')}")
    print(f"n_run_planned={values.get('n_run_planned')}")
    print(f"tone_bins={values.get('tone_bins')}")
    print(f"min_effect_tone={values.get('min_effect_tone')}")
    print(f"min_effect_tone_adjusted={values.get('min_effect_tone_adjusted')}")
    print(f"theta_band={values.get('theta_band')}")
    print(f"b_band={values.get('b_band')}")
    print(f"age_bins={values.get('age_bins')}")
    print(f"min_effect_threshold_contrast={values.get('min_effect_threshold_contrast')}")
    for key, reason in record.get("blocked", {}).items():
        print(f"blocked {key}: {reason}")

    return 0 if record.get("complete") else 1


if __name__ == "__main__":
    sys.exit(main())
