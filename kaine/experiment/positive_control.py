# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline verifier for the positive-control information-gain measure.

The live test runs only after the measure passes for every processor
(paper Appendix A.8). The check pools consecutive complete control runs:
when one run yields fewer than the required included reports, the effect is
taken over consecutive complete runs until the number is reached. The
verdict is re-derived from the recorded numbers; a result's own ``passed``
flag is never trusted.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kaine.experiment.run_records import DEFAULT_ROOT, load_run_records

#: Event type written by kaine.modules.positive_control.
RESULT_EVENT_TYPE = "positive_control.result"

#: Processors that participate in the positive control.
#: Kept equal to ``kaine.modules.positive_control.PROCESSORS``; a test checks they match.
PROCESSORS = ("vision", "audition", "interoception")

#: Mode value that marks a finished control verdict record.
CONTROL_MODE = "control"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_terminal_numbers(
    record: Mapping[str, Any], *, full_run: bool = False
) -> str | None:
    """Return a reason string if a terminal record's numbers are invalid."""
    for name in (
        "ig_with",
        "ig_without",
        "ig_noise",
        "effect",
        "noise_effect",
        "min_effect",
        "t_learn_s",
    ):
        value = record.get(name)
        if not _is_number(value) or not math.isfinite(value):
            return f"{name} is missing or not finite"

    for name in ("n_reports", "min_reports"):
        if not _is_int(record.get(name)):
            return f"{name} is missing"

    if not isinstance(record.get("settings_sha256"), str):
        return "settings_sha256 is missing or not a string"

    if record["min_effect"] <= 0:
        return "min_effect is not above 0"
    if record["min_reports"] < 1:
        return "min_reports is below 1"
    if record["t_learn_s"] < 0:
        return "t_learn_s is below 0"
    if full_run and record["n_reports"] < record["min_reports"]:
        return "n_reports is below min_reports"

    effect = record["effect"]
    noise_effect = record["noise_effect"]
    ig_with = record["ig_with"]
    ig_without = record["ig_without"]
    ig_noise = record["ig_noise"]

    if not math.isclose(
        effect, ig_with - ig_without, rel_tol=1e-9, abs_tol=1e-12
    ):
        return "effect does not match ig_with minus ig_without"
    if not math.isclose(
        noise_effect, ig_noise - ig_without, rel_tol=1e-9, abs_tol=1e-12
    ):
        return "noise_effect does not match ig_noise minus ig_without"

    return None


def terminal_record(
    records: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any] | None, str]:
    """Return a run's terminal control record for one processor and a status.

    The status is ``"complete"`` when a valid terminal record exists; otherwise
    it is a one-line reason the run cannot be pooled.
    """
    if any(record.get("failed") is True for record in records):
        return None, "the control failed"

    final_records = [record for record in records if record.get("final") is True]
    if not final_records:
        return None, "no terminal record"
    if len(final_records) > 1:
        return None, "more than one terminal record (the control restarted)"

    terminal_index = next(
        i for i, record in enumerate(records) if record.get("final") is True
    )
    if terminal_index != len(records) - 1:
        return None, "a record follows the terminal record"

    reason = _validate_terminal_numbers(records[terminal_index], full_run=False)
    if reason is not None:
        return None, reason

    return records[terminal_index], "complete"


def derive(record: Mapping[str, Any]) -> tuple[bool, str]:
    """Derive the verdict from a single positive-control record."""
    terminal, reason = terminal_record([record])
    if reason != "complete":
        return False, reason

    reason = _validate_terminal_numbers(record, full_run=True)
    if reason is not None:
        return False, reason

    if record["effect"] < record["min_effect"]:
        return False, "the informative component was not detected"
    if record["noise_effect"] >= record["min_effect"]:
        return False, "the non-informative component was detected"

    return True, "passed"


def _processor_control_records(
    records: Sequence[Mapping[str, Any]], processor: str
) -> list[Mapping[str, Any]]:
    """Filter one run's records to control results for a single processor."""
    return [
        record
        for record in records
        if record.get("event_type") == RESULT_EVENT_TYPE
        and record.get("processor") == processor
        and record.get("mode") == CONTROL_MODE
    ]


def pooled_verdict(
    runs: Sequence[tuple[str, Sequence[Mapping[str, Any]]]]
) -> dict[str, Any]:
    """Pool consecutive complete control runs and return a verdict.

    ``runs`` is an ordered list of ``(run_id, records)`` tuples. For each
    processor the terminal record of each run is checked; complete runs are
    pooled until ``min_reports`` included reports are reached. The final
    effect and noise effect are report-weighted means over the pooled runs.
    """
    processor_results: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}
    not_passed: list[str] = []

    for processor in PROCESSORS:
        runs_used: list[str] = []
        n = 0
        s_with = 0.0
        s_without = 0.0
        s_noise = 0.0
        baseline: Mapping[str, Any] | None = None
        min_effect: float | None = None
        min_reports: int | None = None
        t_learn_s: float | None = None
        settings_sha256: str | None = None
        reason = "no result"

        for run_id, records in runs:
            proc_records = _processor_control_records(records, processor)
            terminal, term_reason = terminal_record(proc_records)
            if terminal is None:
                # No records for this processor means there was no result.
                # Keep the reason plain for single runs, prefix it for pooled runs.
                if not proc_records:
                    term_reason = "no result"
                if len(runs) == 1:
                    reason = term_reason
                else:
                    reason = f"run {run_id}: {term_reason}"
                break

            if baseline is None:
                baseline = terminal
                min_effect = terminal["min_effect"]
                min_reports = terminal["min_reports"]
                t_learn_s = terminal["t_learn_s"]
                settings_sha256 = terminal["settings_sha256"]
            else:
                if (
                    terminal["min_effect"] != baseline["min_effect"]
                    or terminal["min_reports"] != baseline["min_reports"]
                    or terminal["t_learn_s"] != baseline["t_learn_s"]
                    or terminal["settings_sha256"] != baseline["settings_sha256"]
                ):
                    reason = "runs carry different settings"
                    break

            n_reports = terminal["n_reports"]
            if n_reports > 0:
                runs_used.append(run_id)
                n += n_reports
                s_with += terminal["ig_with"] * n_reports
                s_without += terminal["ig_without"] * n_reports
                s_noise += terminal["ig_noise"] * n_reports

            if n >= min_reports:
                break
        else:
            if baseline is None:
                reason = "no result"
            elif len(runs) == 1 and n < min_reports:
                reason = "n_reports is below min_reports"
            else:
                reason = "fewer than min_reports included reports over the given runs"

        if baseline is not None and n >= min_reports:
            effect = (s_with - s_without) / n
            noise_effect = (s_noise - s_without) / n
            if effect < min_effect:
                reason = "the informative component was not detected"
            elif noise_effect >= min_effect:
                reason = "the non-informative component was detected"
            else:
                reason = "passed"
            processor_results[processor] = {
                "runs_used": runs_used,
                "n_reports": n,
                "effect": effect,
                "noise_effect": noise_effect,
                "min_effect": min_effect,
                "min_reports": min_reports,
                "t_learn_s": t_learn_s,
                "settings_sha256": settings_sha256,
                "reason": reason,
            }
        else:
            processor_results[processor] = {
                "runs_used": runs_used,
                "n_reports": n,
                "effect": None,
                "noise_effect": None,
                "min_effect": baseline["min_effect"] if baseline else None,
                "min_reports": baseline["min_reports"] if baseline else None,
                "t_learn_s": baseline["t_learn_s"] if baseline else None,
                "settings_sha256": baseline["settings_sha256"] if baseline else None,
                "reason": reason,
            }

        reasons[processor] = reason
        if reason != "passed":
            not_passed.append(processor)

    return {
        "passed": not not_passed,
        "processors": processor_results,
        "not_passed": not_passed,
        "reasons": reasons,
    }


def verdict_from_records(
    records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Return the positive-control verdict for a single run's records."""
    run_records_list = list(records)
    verdict = pooled_verdict([("run", run_records_list)])
    missing = [
        processor
        for processor in PROCESSORS
        if not any(
            record.get("event_type") == RESULT_EVENT_TYPE
            and record.get("processor") == processor
            and record.get("mode") == CONTROL_MODE
            for record in run_records_list
        )
    ]
    if missing:
        verdict["passed"] = False
    verdict["missing"] = missing
    return verdict


def run_verdict(
    run_ids: Sequence[str] | str, *, root: Path | str = DEFAULT_ROOT
) -> dict[str, Any]:
    """Load records for ``run_ids`` and return the pooled positive-control verdict."""
    if isinstance(run_ids, str):
        run_ids = (run_ids,)

    parsed_runs: list[tuple[str, list[Mapping[str, Any]]]] = []
    parse_errors = 0
    for run_id in run_ids:
        records = load_run_records(run_id, root=root)
        parse_errors += records.parse_errors
        parsed_runs.append((run_id, [rec for _, rec in records.all_records()]))

    verdict = pooled_verdict(parsed_runs)
    verdict["run_ids"] = list(run_ids)
    verdict["parse_errors"] = parse_errors
    if parse_errors > 0:
        verdict["passed"] = False
    verdict["missing"] = []
    return verdict


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point for the offline verdict check."""
    parser = argparse.ArgumentParser(
        prog="python -m kaine.experiment.positive_control",
        description="Check the positive-control information-gain verdict for one or more runs.",
    )
    parser.add_argument(
        "run_ids",
        nargs="+",
        help="run ids of consecutive complete control runs, in order",
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Evaluation root directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the verdict as JSON",
    )
    args = parser.parse_args(argv)

    verdict = run_verdict(args.run_ids, root=args.root)
    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True, default=str))
    else:
        for processor in PROCESSORS:
            proc = verdict["processors"][processor]
            print(
                f"{processor}: "
                f"runs_used={proc.get('runs_used')} "
                f"n_reports={proc.get('n_reports')} "
                f"min_reports={proc.get('min_reports')} "
                f"effect={proc.get('effect')} "
                f"noise_effect={proc.get('noise_effect')} "
                f"min_effect={proc.get('min_effect')} "
                f"reason={verdict['reasons'][processor]}"
            )
        print(f"parse_errors: {verdict['parse_errors']}")
        print(f"all processors pass: {'yes' if verdict['passed'] else 'no'}")
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
