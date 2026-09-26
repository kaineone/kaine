# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Ignition-log analysis for the module-ignition study.

Read-only over the study's data. Computes the same content-free measures for
every completed viewing, compares main against control and step against step,
and writes ``analysis/report.json`` and ``analysis/report.md`` in the study
directory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.experiment.run_records import load_run_records
from kaine.research.ignition_study.plan import load_plan
from kaine.security.crypto import (
    CryptoConfig,
    CryptoConfigError,
    StateEncryptor,
    get_state_encryptor,
    install_from_section,
    set_state_encryptor,
)

SCHEMA_VERSION = "1.0.0"
_LOGGER = logging.getLogger(__name__)

LIMITS = [
    "Modules are added in one fixed order, so each effect is conditional on the earlier ones and on the being's history.",
    "Control removes familiarity, not order.",
    "Modules with no input channel on this host (Praxis, Perception, the Mundus stub) are expected nulls and are flagged when their share is zero.",
    "The design has one being per line; nothing is tested for significance.",
]

EXPECTED_NULL_MODULES = {"praxis", "perception", "mundus"}
_INTERNAL_SOURCES = {"syneidesis", "volition"}

_SCALAR_DIFF_KEYS = (
    "broadcast_rate_per_minute",
    "programme_time_minutes",
    "paused_broadcasts",
    "coalition_size_mean",
    "coalition_size_median",
    "coalition_size_p90",
    "module_shares",
    "member_salience",
    "inhibited_share",
    "drift_median",
    "drift_max",
    "data_quality",
)


@dataclass
class PerFilmBins:
    title: str
    bins: dict[int, int] = field(default_factory=dict)
    coverage: set[int] = field(default_factory=set)


@dataclass
class ViewingResult:
    line: str
    step: int
    run_id: str | None
    modules: list[str]
    measures: dict[str, Any]
    film_minute_bins: dict[str, PerFilmBins]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    d = k - f
    return float(s[f] * (1.0 - d) + s[c] * d)


def _mean(values: list[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def _film_key(programme: dict[str, Any] | None) -> str:
    if programme is None:
        return "unknown"
    title = programme.get("title")
    if title:
        return str(title)
    return f"item_{programme.get('item_idx', 'x')}"


def _install_encryptor() -> None:
    try:
        install_from_section({"enabled": True})
    except CryptoConfigError:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _load_steps(study_dir: Path) -> list[dict[str, Any]]:
    steps_path = study_dir / "steps.jsonl"
    if not steps_path.exists():
        return []
    steps: list[dict[str, Any]] = []
    for raw_line in steps_path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            steps.append(json.loads(line))
        except json.JSONDecodeError:
            _LOGGER.warning("Ignoring malformed steps.jsonl line: %s", line)
    return steps


def _count_unreadable_lines(log_dir: Path) -> int:
    """Count lines (and whole unreadable files) that cannot be decrypted/parsed.

    This is a second pass over the sink files using the same decrypt call as
    ``load_run_records``. A blank line is not a record and is not counted.
    """
    encryptor = get_state_encryptor()
    unreadable = 0
    for path in sorted(Path(log_dir).rglob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    if not raw.strip():
                        continue
                    try:
                        plain = encryptor.decrypt_text(raw.rstrip("\n"))
                        json.loads(plain)
                    except Exception:
                        unreadable += 1
        except OSError:
            unreadable += 1
    return unreadable


def _load_ignition_records(
    run_id: str,
    log_dir: Path,
) -> tuple[list[dict[str, Any]], int, int]:
    run_records = load_run_records(run_id, root=log_dir)
    records: list[dict[str, Any]] = []
    for stream_recs in run_records.by_stream.values():
        records.extend(stream_recs)
    records.sort(key=lambda r: (r.get("seq") or 0, r.get("mono_ts") or 0.0))

    unreadable = _count_unreadable_lines(log_dir)

    seqs = [int(r["seq"]) for r in records if isinstance(r.get("seq"), int)]
    expected = max(seqs) - min(seqs) + 1 if seqs else 0
    dropped = max(0, expected - len(seqs))

    return records, unreadable, dropped


def _programme_time_and_bins(
    records: list[dict[str, Any]],
) -> tuple[float, dict[str, PerFilmBins], int]:
    bins: dict[str, PerFilmBins] = {}
    total_seconds = 0.0
    gaps_over_10s = 0

    by_film: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        prog = rec.get("programme")
        if prog is None:
            continue
        key = _film_key(prog)
        by_film.setdefault(key, []).append(rec)

    for key, film_records in by_film.items():
        per = PerFilmBins(title=key)
        prev_offset: float | None = None
        for rec in film_records:
            prog = rec.get("programme")
            if prog is None:
                continue
            offset = float(prog.get("offset_s", 0.0))
            minute = int(offset // 60)

            # A broadcast with a programme position belongs to a film-minute bin.
            per.bins[minute] = per.bins.get(minute, 0) + 1

            paused = bool(prog.get("paused", False))
            if not paused:
                per.coverage.add(minute)
                if prev_offset is not None:
                    diff = offset - prev_offset
                    if diff > 0:
                        total_seconds += diff
                        prev_min = int(prev_offset // 60)
                        for m in range(prev_min + 1, minute + 1):
                            per.coverage.add(m)
                        if diff > 10.0:
                            gaps_over_10s += 1
                prev_offset = offset

        if per.coverage or per.bins:
            bins[key] = per

    return total_seconds, bins, gaps_over_10s


def _analyse_viewing(
    step: dict[str, Any],
    faculty_modules: list[str],
) -> ViewingResult:
    run_id = step.get("run_id")
    log_dir = Path(step.get("ignition_log_dir") or "")
    if not log_dir.is_absolute():
        log_dir = step.get("_study_dir", Path(".")) / log_dir

    modules = sorted(step.get("modules", []))

    if run_id is None or not log_dir.exists():
        return ViewingResult(
            line=step["line"],
            step=step["step"],
            run_id=run_id,
            modules=modules,
            measures={
                "broadcast_rate_per_minute": 0.0,
                "programme_time_minutes": 0.0,
                "paused_broadcasts": 0,
                "coalition_size_mean": 0.0,
                "coalition_size_median": 0.0,
                "coalition_size_p90": 0.0,
                "module_shares": {},
                "member_salience": {},
                "inhibited_share": 0.0,
                "drift_median": None,
                "drift_max": None,
                "data_quality": {
                    "record_count": 0,
                    "gaps_longer_than_10s": 0,
                    "dropped_records": 0,
                    "unreadable_lines": 0,
                },
                "expected_null_modules_flagged": [],
            },
            film_minute_bins={},
        )

    records, unreadable_lines, dropped_records = _load_ignition_records(run_id, log_dir)

    total_records = len(records)
    programme_seconds, film_bins, gaps_over_10s = _programme_time_and_bins(records)
    programme_minutes = programme_seconds / 60.0

    all_sources = set(faculty_modules) | _INTERNAL_SOURCES
    module_shares: dict[str, int] = {s: 0 for s in all_sources}
    salience_values: dict[str, list[float]] = {}
    coalition_sizes: list[int] = []
    inhibited_count = 0
    paused_count = 0
    drift_values: list[float] = []

    for rec in records:
        members = rec.get("members") or []
        coalition_sizes.append(len(members))
        if rec.get("inhibited") is True:
            inhibited_count += 1

        prog = rec.get("programme")
        if prog is not None and prog.get("paused") is True:
            paused_count += 1

        audio = rec.get("audio")
        if prog is not None and audio is not None:
            try:
                drift = abs(
                    float(prog.get("offset_s", 0.0))
                    - float(audio.get("delivered_s", 0.0))
                )
                drift_values.append(drift)
            except (TypeError, ValueError):
                pass

        seen_sources: set[str] = set()
        for member in members:
            source = member.get("source")
            if source is None:
                continue
            seen_sources.add(source)
            salience = member.get("salience")
            if isinstance(salience, (int, float)):
                salience_values.setdefault(source, []).append(float(salience))

        for source in seen_sources:
            if source in module_shares:
                module_shares[source] += 1

    share_values = {
        s: (cnt / total_records if total_records else 0.0)
        for s, cnt in module_shares.items()
    }

    member_salience: dict[str, dict[str, float]] = {}
    for source, vals in salience_values.items():
        member_salience[source] = {
            "mean": _mean(vals),
            "median": _percentile(vals, 50.0),
            "p90": _percentile(vals, 90.0),
        }
    for source in all_sources:
        if source not in member_salience:
            member_salience[source] = {
                "mean": 0.0,
                "median": 0.0,
                "p90": 0.0,
            }

    inhibited_share = inhibited_count / total_records if total_records else 0.0
    # Broadcasts made while the programme was paused (a replay window, a
    # freeze) are reported as paused_broadcasts and kept out of the rate.
    unpaused_records = total_records - paused_count
    broadcast_rate = unpaused_records / programme_minutes if programme_minutes > 0 else 0.0

    expected_nulls_flagged = [
        m
        for m in faculty_modules
        if m.lower() in EXPECTED_NULL_MODULES and share_values.get(m, 0.0) == 0.0
    ]

    measures: dict[str, Any] = {
        "broadcast_rate_per_minute": broadcast_rate,
        "programme_time_minutes": programme_minutes,
        "paused_broadcasts": paused_count,
        "coalition_size_mean": _mean([float(x) for x in coalition_sizes]),
        "coalition_size_median": _percentile([float(x) for x in coalition_sizes], 50.0),
        "coalition_size_p90": _percentile([float(x) for x in coalition_sizes], 90.0),
        "module_shares": {k: share_values[k] for k in sorted(share_values)},
        "member_salience": {k: member_salience[k] for k in sorted(member_salience)},
        "inhibited_share": inhibited_share,
        "drift_median": _percentile(drift_values, 50.0) if drift_values else None,
        "drift_max": max(drift_values) if drift_values else None,
        "data_quality": {
            "record_count": total_records,
            "gaps_longer_than_10s": gaps_over_10s,
            "dropped_records": dropped_records,
            "unreadable_lines": unreadable_lines,
        },
        "expected_null_modules_flagged": expected_nulls_flagged,
    }

    return ViewingResult(
        line=step["line"],
        step=step["step"],
        run_id=run_id,
        modules=modules,
        measures=measures,
        film_minute_bins=film_bins,
    )


def _numeric_diff_dict(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in set(a) | set(b):
        av = a.get(key)
        bv = b.get(key)
        if isinstance(av, dict) or isinstance(bv, dict):
            result[key] = _numeric_diff_dict(av or {}, bv or {})
        else:
            avn = float(av) if isinstance(av, (int, float)) else 0.0
            bvn = float(bv) if isinstance(bv, (int, float)) else 0.0
            result[key] = avn - bvn
    return result


def _diff_measures(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in _SCALAR_DIFF_KEYS:
        av = a.get(key)
        bv = b.get(key)
        if key in ("module_shares", "member_salience", "data_quality"):
            result[key] = _numeric_diff_dict(av or {}, bv or {})
        elif key in ("drift_median", "drift_max"):
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                result[key] = av - bv
            else:
                result[key] = None
        else:
            avn = float(av) if isinstance(av, (int, float)) else 0.0
            bvn = float(bv) if isinstance(bv, (int, float)) else 0.0
            result[key] = avn - bvn
    return result


def _profile_vectors(
    a: dict[str, PerFilmBins],
    b: dict[str, PerFilmBins],
) -> tuple[list[int], list[int], int]:
    xs: list[int] = []
    ys: list[int] = []
    for title in set(a) & set(b):
        coverage = a[title].coverage & b[title].coverage
        for minute in sorted(coverage):
            xs.append(a[title].bins.get(minute, 0))
            ys.append(b[title].bins.get(minute, 0))
    return xs, ys, len(xs)


def _pearson(xs: list[int], ys: list[int]) -> float | None:
    n = len(xs)
    if n == 0:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    dxs = [x - mx for x in xs]
    dys = [y - my for y in ys]
    num = sum(d * e for d, e in zip(dxs, dys))
    den = math.sqrt(sum(d * d for d in dxs)) * math.sqrt(sum(e * e for e in dys))
    if den == 0.0:
        # A constant profile has no variance: the correlation is undefined,
        # and reporting 0.0 would invent a finding.
        return None
    return num / den


def _correlation_result(
    a_bins: dict[str, PerFilmBins],
    b_bins: dict[str, PerFilmBins],
) -> dict[str, Any]:
    xs, ys, shared = _profile_vectors(a_bins, b_bins)
    if shared < 30:
        return {"correlation": "not_computed", "shared_bins": shared}
    r = _pearson(xs, ys)
    if r is None:
        return {"correlation": "undefined_constant_profile", "shared_bins": shared}
    return {"correlation": r, "shared_bins": shared}


def _build_per_step(
    viewings: list[ViewingResult],
    viewings_per_line: int,
) -> list[dict[str, Any]]:
    by_line_step: dict[tuple[str, int], ViewingResult] = {
        (v.line, v.step): v for v in viewings
    }
    steps: list[dict[str, Any]] = []
    for k in range(viewings_per_line):
        main = by_line_step.get(("main", k))
        ctrl = by_line_step.get(("control", k))
        entry: dict[str, Any] = {"step": k}
        if main is not None and ctrl is not None:
            entry["main_minus_control"] = _diff_measures(main.measures, ctrl.measures)
            entry["main_vs_control_correlation"] = _correlation_result(
                main.film_minute_bins, ctrl.film_minute_bins
            )
        else:
            entry["main_minus_control"] = None
            entry["main_vs_control_correlation"] = None

        for line in ("main", "control"):
            prev = by_line_step.get((line, k - 1))
            cur = by_line_step.get((line, k))
            if cur is None or k == 0 or prev is None:
                entry[f"{line}_delta_from_previous"] = None
                entry[f"{line}_to_previous_correlation"] = None
            else:
                entry[f"{line}_delta_from_previous"] = _diff_measures(
                    cur.measures, prev.measures
                )
                entry[f"{line}_to_previous_correlation"] = _correlation_result(
                    cur.film_minute_bins, prev.film_minute_bins
                )
        steps.append(entry)
    return steps


def _viewing_to_dict(v: ViewingResult) -> dict[str, Any]:
    film_bins_out: dict[str, dict[str, int]] = {}
    for title, per in v.film_minute_bins.items():
        film_bins_out[title] = {
            str(m): c for m, c in sorted(per.bins.items()) if c != 0
        }
    return {
        "line": v.line,
        "step": v.step,
        "run_id": v.run_id,
        "modules": v.modules,
        "measures": v.measures,
        "film_minute_bins": film_bins_out,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        return f"{value:.4f}"
    return str(value)


def _fmt_corr(corr: dict[str, Any] | None) -> str:
    if corr is None:
        return "—"
    if corr.get("correlation") == "not_computed":
        return f"not computed (shared bins: {corr['shared_bins']})"
    if corr.get("correlation") == "undefined_constant_profile":
        return f"undefined, a profile is constant (shared bins: {corr['shared_bins']})"
    return f"{_fmt(corr.get('correlation'))} (shared bins: {corr['shared_bins']})"


def _measures_diff_lines(diff: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in _SCALAR_DIFF_KEYS:
        value = diff.get(key)
        if isinstance(value, dict):
            lines.append(f"- **{key}**: " + json.dumps(value, sort_keys=True))
        elif value is not None:
            lines.append(f"- **{key}**: {_fmt(value)}")
    return lines


def _build_markdown(report: dict[str, Any], viewings: list[ViewingResult]) -> str:
    lines: list[str] = [
        f"# Module-ignition study report: {report['study_id']}",
        "",
        f"- Schema version: {report['schema_version']}",
        f"- Plan hash: `{report['plan_hash']}`",
        f"- Generated at: {report['generated_at']}",
        f"- Completed viewings: {len(report['per_viewing'])}",
        "",
        "## Per-viewing summary",
        "",
    ]

    header = (
        "| Step | Line | Modules | Rate/min | Prog min | Paused | "
        "Coal mean | Coal median | Coal p90 | Inhibited | Drift median | "
        "Drift max | Records | Gaps >10s | Drops | Unreadable |"
    )
    lines.append(header)
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    for pv in report["per_viewing"]:
        m = pv["measures"]
        dq = m["data_quality"]
        row = (
            f"| {pv['step']} | {pv['line']} | {', '.join(pv['modules'])} | "
            f"{_fmt(m['broadcast_rate_per_minute'])} | {_fmt(m['programme_time_minutes'])} | "
            f"{m['paused_broadcasts']} | {_fmt(m['coalition_size_mean'])} | "
            f"{_fmt(m['coalition_size_median'])} | {_fmt(m['coalition_size_p90'])} | "
            f"{_fmt(m['inhibited_share'])} | {_fmt(m['drift_median'])} | "
            f"{_fmt(m['drift_max'])} | {dq['record_count']} | "
            f"{dq['gaps_longer_than_10s']} | {dq['dropped_records']} | "
            f"{dq['unreadable_lines']} |"
        )
        lines.append(row)
    lines.append("")

    lines.append("## Module shares")
    lines.append("")
    cols = [f"{pv['line']} {pv['step']}" for pv in report["per_viewing"]]
    lines.append("| Module | " + " | ".join(cols) + " |")
    lines.append(
        "|-" + "-|".join(["" for _ in range(len(cols) + 1)]) + "-|"
    )
    all_modules = sorted(
        {m for pv in report["per_viewing"] for m in pv["measures"]["module_shares"]}
    )
    for mod in all_modules:
        cells = [mod] + [
            _fmt(pv["measures"]["module_shares"].get(mod, 0.0))
            for pv in report["per_viewing"]
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Film-minute bins")
    lines.append("")
    for v, vr in zip(report["per_viewing"], viewings):
        lines.append(f"### {v['line']} step {v['step']}")
        for title, per in vr.film_minute_bins.items():
            non_empty = sum(1 for c in per.bins.values() if c)
            lines.append(
                f"- **{title}**: {len(per.coverage)} covered minutes, "
                f"{non_empty} non-empty bins"
            )
        lines.append("")

    lines.append("## Per-step comparisons")
    lines.append("")
    for entry in report["per_step"]:
        k = entry["step"]
        lines.append(f"### Step {k}")
        if entry["main_minus_control"] is not None:
            lines.append("**Main − control**")
            lines.append(f"- Correlation: {_fmt_corr(entry['main_vs_control_correlation'])}")
            lines.extend(_measures_diff_lines(entry["main_minus_control"]))
        else:
            lines.append("Main or control viewing missing; no comparison.")
        lines.append("")

        for line in ("main", "control"):
            delta = entry.get(f"{line}_delta_from_previous")
            corr = entry.get(f"{line}_to_previous_correlation")
            if delta is not None:
                lines.append(f"**{line.title()} delta from previous step**")
                lines.append(f"- Correlation: {_fmt_corr(corr)}")
                lines.extend(_measures_diff_lines(delta))
            else:
                lines.append(
                    f"**{line.title()} delta from previous step**: no previous step."
                )
            lines.append("")

    lines.append("## Limits")
    lines.append("")
    for lim in report["limits"]:
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines)


def run_analysis(study_dir: Path | str) -> tuple[Path, Path]:
    """Analyse every completed viewing in ``study_dir`` and write the report."""
    study_dir = Path(study_dir).resolve()
    plan = load_plan(study_dir)
    plan_hash = hashlib.sha256((study_dir / "study.json").read_bytes()).hexdigest()
    steps = _load_steps(study_dir)

    faculty_modules = list(plan.get("base_modules", [])) + list(plan.get("order", []))
    viewings_per_line = int(plan.get("viewings_per_line", 12))

    _install_encryptor()

    viewings: list[ViewingResult] = []
    for step in steps:
        if step.get("outcome") != "complete":
            continue
        line = step.get("line")
        if line not in ("main", "control"):
            continue
        if not step.get("run_id"):
            continue
        log_dir = Path(step.get("ignition_log_dir") or "")
        if not log_dir.is_absolute():
            log_dir = study_dir / log_dir
        if not log_dir.exists():
            _LOGGER.warning(
                "Skipping %s step %s: ignition log dir not found: %s",
                line,
                step.get("step"),
                log_dir,
            )
            continue
        step["_study_dir"] = study_dir
        viewings.append(_analyse_viewing(step, faculty_modules))
        step.pop("_study_dir", None)

    per_step = _build_per_step(viewings, viewings_per_line)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "study_id": plan.get("study_id"),
        "plan_hash": plan_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "viewings_per_line": viewings_per_line,
        "faculty_modules": faculty_modules,
        "per_viewing": [_viewing_to_dict(v) for v in viewings],
        "per_step": per_step,
        "limits": LIMITS,
    }

    analysis_dir = study_dir / "analysis"
    json_path = analysis_dir / "report.json"
    md_path = analysis_dir / "report.md"

    _atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True))
    _atomic_write_text(md_path, _build_markdown(report, viewings))
    return json_path, md_path
