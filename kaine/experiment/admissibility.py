# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Run completeness gating — is a finished run admissible for analysis?

A run is *admissible* only when its durable record is provably complete:

* **Contiguous cycle ticks.** ``cycle.tick`` carries a monotonic ``tick_index``
  that runs ``0, 1, 2, ...`` for the life of the cycle. A gap means ticks (and
  the records they produced) went missing.
* **Contiguous per-sink ``seq``.** Every record written through
  ``AsyncJsonlSink`` while a run context is set carries a per-sink monotonic
  ``seq`` from 0. A gap in a stream's ``seq`` means records were silently
  dropped (e.g. queue backpressure) — invisible from timestamps alone.
* **All expected streams present.** The caller passes the set of streams the
  run's configuration was expected to produce; a stream with zero records is a
  silent-failure signal (an observer that never wrote).
* **No parse errors.** A line that could not be decrypted/parsed is itself
  evidence of corruption.
* **No restart / multi-process signature.** A sink's ``seq`` is a single
  process's monotonic counter — it must never go backwards. If a stream's raw
  ``seq`` sequence drops (typically back toward 0) that is a fresh sink
  instance stamping again, i.e. the process restarted mid-run. This is
  invisible to the contiguity check above, which treats ``seq`` as a *set* and
  tolerates duplicates. Separately, a caller MAY declare that several distinct
  ``run_id``\\ s are one operator-defined logical run (a crash/resume where the
  new process minted a fresh ``run_id`` — see ``kaine.experiment.run_context``,
  which never reuses one); scanning them together is itself a restart signal.

This module is boundary-neutral: it reads records through
``kaine.experiment.run_records`` and takes ``expected_streams`` as data, so it
never imports ``kaine.evaluation``. ``build_research_bundle`` (in
``kaine.research``, which *may* couple to evaluation) is the place that supplies
the expected-stream list and surfaces the verdict in the bundle manifest.

CLI: ``python -m kaine.experiment.admissibility <run_id>`` prints the report and
exits non-zero when the run is inadmissible.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from kaine.experiment.run_records import DEFAULT_ROOT, RunRecords, load_run_records

#: The cycle's tick stream. Its records carry ``tick_index`` (0..N contiguous).
TICK_STREAM = "cycle.tick"
#: The payload field on a tick record holding the monotonic tick number.
TICK_FIELD = "tick_index"
#: The per-sink monotonic record counter stamped by ``AsyncJsonlSink``.
SEQ_FIELD = "seq"


@dataclass
class AdmissibilityReport:
    """Verdict + evidence for one run's completeness scan."""

    run_id: str
    admissible: bool
    tick_gaps: list[int] = field(default_factory=list)
    seq_gaps: dict[str, list[int]] = field(default_factory=dict)
    missing_streams: list[str] = field(default_factory=list)
    parse_errors: int = 0
    # Restart / multi-process detection (run-admissibility: restart handling).
    # ``restart_seq_resets`` maps a stream to the seq values observed AFTER a
    # backward jump (a fresh sink instance stamping from 0 again mid-run).
    # ``related_run_ids`` echoes any additional run_ids the caller declared as
    # part of this logical run (see ``scan_run``'s ``related_run_ids`` param);
    # a non-empty list here means the scan itself spans more than one run_id.
    restart_seq_resets: dict[str, list[int]] = field(default_factory=dict)
    related_run_ids: list[str] = field(default_factory=list)

    def restart_detected(self) -> bool:
        """True when either a seq reset or a declared multi-run-id span was seen."""
        return bool(self.restart_seq_resets) or bool(self.related_run_ids)

    def reasons(self) -> list[str]:
        """Human-readable reasons the run is inadmissible (empty when clean)."""
        out: list[str] = []
        if self.tick_gaps:
            out.append(f"tick_index gaps: {self.tick_gaps}")
        if self.seq_gaps:
            out.append(f"seq gaps: {self.seq_gaps}")
        if self.missing_streams:
            out.append(f"missing streams: {self.missing_streams}")
        if self.parse_errors:
            out.append(f"parse errors: {self.parse_errors}")
        if self.restart_seq_resets:
            out.append(
                "restart/multi-process detected (seq reset): "
                f"{self.restart_seq_resets}"
            )
        if self.related_run_ids:
            out.append(
                "restart/multi-process detected (multiple run_ids scanned as one "
                f"logical run): {[self.run_id, *self.related_run_ids]}"
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        """Stable serialization for the bundle manifest / CLI JSON output."""
        d = asdict(self)
        d["reasons"] = self.reasons()
        return d


def _contiguous_gaps(values: Iterable[int]) -> list[int]:
    """Return the missing integers in the contiguous range ``min..max``.

    The sequence is treated as a set that *should* be ``min, min+1, ..., max``.
    Duplicates are tolerated (they are not gaps). An empty input has no gaps.
    The expected floor is the minimum observed value, so a stream whose ``seq``
    starts at 0 and a tick sequence that starts at 0 are both checked from their
    own first element (no assumption that 0 is present — only contiguity).
    """
    seen = {int(v) for v in values}
    if not seen:
        return []
    lo, hi = min(seen), max(seen)
    return [n for n in range(lo, hi + 1) if n not in seen]


def _extract_int_field(records: Sequence[dict[str, Any]], field_name: str) -> list[int]:
    """Extract integer values of ``field_name`` from records, in order.

    Records lacking an integer-valued field are skipped (they cannot be placed
    in the sequence); a record carrying it is the source of truth. ``bool`` is an
    ``int`` subclass and is excluded; an integer-valued ``float`` is coerced.
    Used for both ``tick_index`` (tick contiguity) and ``seq`` (per-sink
    contiguity).
    """
    out: list[int] = []
    for rec in records:
        val = rec.get(field_name)
        if isinstance(val, bool):  # bool is an int subclass — exclude it
            continue
        if isinstance(val, int):
            out.append(val)
        elif isinstance(val, float) and val.is_integer():
            out.append(int(val))
    return out


def _seq_resets(values: Iterable[int]) -> list[int]:
    """Return the seq values observed after a backward jump, in encounter order.

    ``values`` is the raw per-stream ``seq`` sequence in file/write order (NOT
    sorted). A per-sink ``seq`` is minted by a single process's monotonic
    counter, so under normal single-process operation it can only increase. A
    later value that drops back below the running maximum — typically back to
    0 — means a fresh ``AsyncJsonlSink`` instance started stamping again: the
    process restarted mid-run without a new ``run_id`` (or two processes wrote
    the same ``run_id``). This is the literal "seq reset" restart signature,
    and it is invisible to :func:`_contiguous_gaps`, which treats the sequence
    as a set and tolerates duplicates as *not* gaps.

    KNOWN BLIND SPOT: if the pre-crash stream reached only ``seq = 0`` (a single
    record) and the restart also begins at ``seq = 0``, the second ``0`` is not
    below the running max (``0 < 0`` is False) so it is not flagged here. This
    is narrow, and it is not the primary defence: the intended detector for a
    crash/resume is a NEW ``run_id`` (``run_context`` mints a fresh one every
    process) surfaced via ``related_run_ids`` / auto-discovery of >1 run in the
    logs, both of which make the run inadmissible regardless of seq depth. See
    ``test_seq_reset_undetected_when_pre_crash_stream_has_single_record``.
    """
    out: list[int] = []
    running_max: Optional[int] = None
    for raw in values:
        v = int(raw)
        if running_max is not None and v < running_max:
            out.append(v)
        else:
            running_max = v if running_max is None else max(running_max, v)
    return out


def _load_combined(
    run_id: str, related_run_ids: Iterable[str], *, root: Path | str
) -> RunRecords:
    """Load ``run_id`` plus each of ``related_run_ids``, merged by stream.

    Records are concatenated in the order the run_ids are given (the primary
    run first), which the caller is expected to supply in chronological order
    (e.g. the original run, then the resumed run after a crash) so the merged
    per-stream ``seq`` sequences stay meaningful for :func:`_seq_resets`.
    """
    combined = RunRecords(run_id=run_id)
    for rid in [run_id, *related_run_ids]:
        recs = load_run_records(rid, root=root)
        for stream, stream_recs in recs.by_stream.items():
            combined.by_stream.setdefault(stream, []).extend(stream_recs)
        combined.parse_errors += recs.parse_errors
    return combined


def scan_run(
    run_id: str,
    *,
    root: Path | str = DEFAULT_ROOT,
    expected_streams: Iterable[str] = (),
    related_run_ids: Iterable[str] = (),
) -> AdmissibilityReport:
    """Scan a finished run for completeness and return an admissibility report.

    Parameters
    ----------
    run_id:
        The run to scan (matched against each record's ``run_id``).
    root:
        Evaluation root holding the JSONL sink files (default
        ``data/evaluation``).
    expected_streams:
        Stream names the run's configuration was expected to produce. Any of
        these with zero records this run is reported in ``missing_streams``.
        Passed in as data so this module stays decoupled from the evaluation
        package.
    related_run_ids:
        Additional run_ids the OPERATOR treats as a continuation of this same
        logical run (e.g. a crash/resume where the resumed process minted a
        fresh ``run_id`` — ``kaine.experiment.run_context`` never reuses one).
        Their records are merged into the scan by stream. Declaring more than
        one run_id here is itself a restart/multi-process signal, so a
        non-empty ``related_run_ids`` always makes the run inadmissible.

    The run is ``admissible`` only when there are no tick gaps, no per-sink seq
    gaps, no missing expected streams, no parse errors, no per-sink seq reset,
    and no declared ``related_run_ids``.
    """
    related = [str(r) for r in related_run_ids]
    records: RunRecords = _load_combined(run_id, related, root=root)
    expected = [str(s) for s in expected_streams]

    # 1) Cycle tick contiguity.
    tick_records = records.by_stream.get(TICK_STREAM, [])
    tick_gaps = _contiguous_gaps(_extract_int_field(tick_records, TICK_FIELD))

    # 2) Per-sink seq contiguity (every stream that produced records) +
    #    restart detection (a backward jump in the raw, un-sorted sequence).
    seq_gaps: dict[str, list[int]] = {}
    restart_seq_resets: dict[str, list[int]] = {}
    for stream, recs in records.by_stream.items():
        seq_values = _extract_int_field(recs, SEQ_FIELD)
        gaps = _contiguous_gaps(seq_values)
        if gaps:
            seq_gaps[stream] = gaps
        resets = _seq_resets(seq_values)
        if resets:
            restart_seq_resets[stream] = resets

    # 3) Expected streams that produced zero records.
    present = records.streams()
    missing_streams = [s for s in expected if s not in present]

    parse_errors = records.parse_errors

    admissible = (
        not tick_gaps
        and not seq_gaps
        and not missing_streams
        and parse_errors == 0
        and not restart_seq_resets
        and not related
    )

    return AdmissibilityReport(
        run_id=run_id,
        admissible=admissible,
        tick_gaps=tick_gaps,
        seq_gaps=seq_gaps,
        missing_streams=sorted(missing_streams),
        parse_errors=parse_errors,
        restart_seq_resets=restart_seq_resets,
        related_run_ids=related,
    )


def _format_report(report: AdmissibilityReport) -> str:
    lines = [
        f"run_id:     {report.run_id}",
        f"admissible: {report.admissible}",
    ]
    if report.admissible:
        lines.append("(no completeness violations)")
    else:
        lines.append("reasons:")
        for reason in report.reasons():
            lines.append(f"  - {reason}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.experiment.admissibility",
        description="Scan a finished run for completeness (admissibility).",
    )
    parser.add_argument("run_id", help="the run id to scan")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="evaluation root holding the JSONL sink files (default data/evaluation)",
    )
    parser.add_argument(
        "--expected-stream",
        action="append",
        default=[],
        dest="expected_streams",
        metavar="NAME",
        help="a stream name the run was expected to produce (repeatable)",
    )
    parser.add_argument(
        "--related-run-id",
        action="append",
        default=[],
        dest="related_run_ids",
        metavar="RUN_ID",
        help=(
            "an additional run_id the operator treats as a continuation of "
            "this logical run, e.g. after a crash/resume (repeatable)"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of text",
    )
    args = parser.parse_args(argv)

    report = scan_run(
        args.run_id,
        root=args.root,
        related_run_ids=args.related_run_ids,
        expected_streams=args.expected_streams,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_report(report))
    return 0 if report.admissible else 1


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    sys.exit(main())


__all__ = ["AdmissibilityReport", "scan_run", "main"]
