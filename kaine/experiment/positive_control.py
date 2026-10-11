# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline verifier for the positive-control information-gain measure.

The paper's rule is that the live test runs only after the measure passes for
every processor. No boot gate enforces that yet, so the study runner or
operator runs this check against a finished run.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from kaine.experiment.run_records import DEFAULT_ROOT, load_run_records

#: Event type written by kaine.modules.positive_control.
RESULT_EVENT_TYPE = "positive_control.result"

#: Processors that participate in the positive control.
#: Kept equal to ``kaine.modules.positive_control.PROCESSORS``; a test checks they match.
PROCESSORS = ("topos", "audition", "soma")


def verdict_from_records(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the cumulative positive-control verdict across ``records``."""
    last_by_processor: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if record.get("event_type") != RESULT_EVENT_TYPE:
            continue
        processor = record.get("processor")
        if processor not in PROCESSORS:
            continue
        last_by_processor[processor] = record
    processors = {processor: last_by_processor.get(processor) for processor in PROCESSORS}
    missing = [processor for processor in PROCESSORS if processors[processor] is None]
    not_passed = [
        processor
        for processor in PROCESSORS
        if processors[processor] is not None and processors[processor].get("passed") is not True
    ]
    return {
        "passed": not missing and not not_passed,
        "processors": processors,
        "missing": missing,
        "not_passed": not_passed,
    }


def run_verdict(run_id: str, *, root: Path | str = DEFAULT_ROOT) -> dict[str, Any]:
    """Load records for ``run_id`` and return the positive-control verdict."""
    verdict = verdict_from_records(
        rec for _, rec in load_run_records(run_id, root=root).all_records()
    )
    verdict["run_id"] = run_id
    return verdict


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point for the offline verdict check."""
    parser = argparse.ArgumentParser(
        prog="python -m kaine.experiment.positive_control",
        description="Check the positive-control information-gain verdict for a run.",
    )
    parser.add_argument("run_id", help="Run identifier to check")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Evaluation root directory")
    parser.add_argument("--json", action="store_true", help="Print the verdict as JSON")
    args = parser.parse_args(argv)

    verdict = run_verdict(args.run_id, root=args.root)
    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True, default=str))
    else:
        for processor in PROCESSORS:
            record = verdict["processors"][processor]
            if record is None:
                print(f"{processor}: no result")
            else:
                print(
                    f"{processor}: "
                    f"passed={record.get('passed')} "
                    f"n_reports={record.get('n_reports')} "
                    f"effect={record.get('effect')} "
                    f"noise_effect={record.get('noise_effect')} "
                    f"min_effect={record.get('min_effect')} "
                    f"snr={record.get('snr')}"
                )
        print(f"all processors pass: {'yes' if verdict['passed'] else 'no'}")
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
