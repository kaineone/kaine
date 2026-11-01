# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Ignition-log analysis for the module-ignition study.

Read-only over the study's data. Computes the same content-free measures for
every completed viewing (branch, repeat and accumulate lines), compares the
branches against the seed, the seed against its repeat and the accumulating
line against the branches, and writes ``analysis/report.json`` and ``analysis/report.md`` in the study
directory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine import legacy_aliases
from kaine.experiment.run_records import load_run_records
from kaine.experiment.stats import mean as _mean
from kaine.experiment.stats import percentile as _percentile
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
    "There is one being per condition; nothing is tested for significance.",
    "The noise floor is a single repeat of branch 0: differences smaller than it are not evidence.",
    "Modules are added in one fixed order, so each effect is conditional on the earlier ones.",
    "The accumulate line mixes familiarity with module history; there is no rewatch-only line.",
    "Effectors, Perceptual locus and Embodiment have no input channel on this host and are expected nulls; they are flagged when their share is zero.",
]

VIEWING_LINES = ("branch", "repeat", "accumulate")

EXPECTED_NULL_MODULES = {"effectors", "perceptual_locus", "embodiment"}
_INTERNAL_SOURCES = {"workspace", "action_selection"}

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
    "time_scale_min",
    "time_scale_max",
    "broadcasts_per_tick",
)

log = logging.getLogger(__name__)


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
                    "audio_on_other_item": 0,
                },
                "expected_null_modules_flagged": [],
            },
            film_minute_bins={},
        )

    records, unreadable_lines, dropped_records = _load_ignition_records(run_id, log_dir)

    total_records = len(records)
    scales = [
        float(r["time_scale"])
        for r in records
        if isinstance(r.get("time_scale"), (int, float))
    ]
    time_scale_min = min(scales) if scales else None
    time_scale_max = max(scales) if scales else None
    time_scale_changed = (
        time_scale_min is not None
        and time_scale_max is not None
        and time_scale_min != time_scale_max
    )
    tick_indices = [
        int(r["tick_index"]) for r in records if isinstance(r.get("tick_index"), int)
    ]
    broadcasts_per_tick = (
        total_records / (max(tick_indices) - min(tick_indices) + 1)
        if tick_indices
        else None
    )

    programme_seconds, film_bins, gaps_over_10s = _programme_time_and_bins(records)
    programme_minutes = programme_seconds / 60.0

    all_sources = set(faculty_modules) | _INTERNAL_SOURCES
    module_shares: dict[str, int] = {s: 0 for s in all_sources}
    salience_values: dict[str, list[float]] = {}
    coalition_sizes: list[int] = []
    inhibited_count = 0
    paused_count = 0
    drift_values: list[float] = []
    # Records whose audio position is on another item than the programme's
    # (an item boundary crossed by one surface a block before the other). Their
    # offsets are on different films, so they say nothing about drift.
    audio_on_other_item = 0

    for rec in records:
        members = rec.get("members") or []
        coalition_sizes.append(len(members))
        if rec.get("inhibited") is True:
            inhibited_count += 1

        prog = rec.get("programme")
        if prog is not None and prog.get("paused") is True:
            paused_count += 1

        audio = rec.get("audio")
        if (
            prog is not None
            and audio is not None
            and audio.get("item_idx") != prog.get("item_idx")
        ):
            audio_on_other_item += 1
        elif prog is not None and audio is not None:
            try:
                drift = abs(
                    float(prog.get("offset_s", 0.0))
                    - float(audio.get("delivered_s", 0.0))
                )
                drift_values.append(drift)
            except (TypeError, ValueError):
                # A malformed position leaves this record out of the drift
                # measure; say so rather than drop it silently.
                log.warning(
                    "ignition record %s has a non-numeric position; left out of drift",
                    rec.get("seq"),
                )

        seen_sources: set[str] = set()
        for member in members:
            source = member.get("source")
            if source is None:
                continue
            if isinstance(source, str):
                source = legacy_aliases.map_module_key(source)
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
            "audio_on_other_item": audio_on_other_item,
        },
        "expected_null_modules_flagged": expected_nulls_flagged,
        "time_scale_min": time_scale_min,
        "time_scale_max": time_scale_max,
        "time_scale_changed": time_scale_changed,
        "broadcasts_per_tick": broadcasts_per_tick,
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


def _compare(
    label: str,
    a_key: tuple[str, int],
    b_key: tuple[str, int],
    by_line_step: dict[tuple[str, int], ViewingResult],
) -> dict[str, Any]:
    """Compare viewing ``a_key`` minus viewing ``b_key``; pending unless both are complete."""
    a = by_line_step.get(a_key)
    b = by_line_step.get(b_key)
    entry: dict[str, Any] = {
        "comparison": label,
        "minuend": {"line": a_key[0], "step": a_key[1]},
        "subtrahend": {"line": b_key[0], "step": b_key[1]},
    }
    if a is None or b is None:
        entry["status"] = "pending"
        entry["difference"] = None
        entry["correlation"] = None
    else:
        entry["status"] = "complete"
        entry["difference"] = _diff_measures(a.measures, b.measures)
        entry["correlation"] = _correlation_result(a.film_minute_bins, b.film_minute_bins)
    return entry


def _build_comparisons(
    viewings: list[ViewingResult],
    module_count: int,
) -> dict[str, Any]:
    by_line_step: dict[tuple[str, int], ViewingResult] = {
        (v.line, v.step): v for v in viewings
    }
    ks = range(1, module_count + 1)
    return {
        "module_effect_from_seed": [
            {"k": k, **_compare("branch k minus branch 0", ("branch", k), ("branch", 0), by_line_step)}
            for k in ks
        ],
        "noise_floor": _compare(
            "branch 0 minus repeat", ("branch", 0), ("repeat", 0), by_line_step
        ),
        "familiarity_and_history": [
            {"k": k, **_compare("accumulate k minus branch k", ("accumulate", k), ("branch", k), by_line_step)}
            for k in ks
        ],
    }


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
        "Drift max | Records | Gaps >10s | Drops | Unreadable | "
        "Scale min | Scale max | Changed | B/T |"
    )
    lines.append(header)
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    for pv in report["per_viewing"]:
        m = pv["measures"]
        dq = m["data_quality"]
        changed = "yes" if m["time_scale_changed"] else "no"
        row = (
            f"| {pv['step']} | {pv['line']} | {', '.join(pv['modules'])} | "
            f"{_fmt(m['broadcast_rate_per_minute'])} | {_fmt(m['programme_time_minutes'])} | "
            f"{m['paused_broadcasts']} | {_fmt(m['coalition_size_mean'])} | "
            f"{_fmt(m['coalition_size_median'])} | {_fmt(m['coalition_size_p90'])} | "
            f"{_fmt(m['inhibited_share'])} | {_fmt(m['drift_median'])} | "
            f"{_fmt(m['drift_max'])} | {dq['record_count']} | "
            f"{dq['gaps_longer_than_10s']} | {dq['dropped_records']} | "
            f"{dq['unreadable_lines']} | "
            f"{_fmt(m['time_scale_min'])} | {_fmt(m['time_scale_max'])} | "
            f"{changed} | {_fmt(m['broadcasts_per_tick'])} |"
        )
        lines.append(row)
    lines.append("")

    lines.append("## Time-dilation interpretation")
    lines.append("")
    lines.append(
        "Time dilation lowers the number of ignitions per film minute "
        "without changing the entity; any viewing whose time_scale changed "
        "must therefore be compared per tick, not per minute."
    )
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

    comparisons = report["comparisons"]

    def _emit(title: str, entry: dict[str, Any]) -> None:
        lines.append(f"### {title}")
        if entry["status"] != "complete":
            lines.append("Pending: one of the two viewings is not complete; not computed.")
        else:
            lines.append(f"- Correlation: {_fmt_corr(entry['correlation'])}")
            lines.extend(_measures_diff_lines(entry["difference"]))
        lines.append("")

    lines.append("## Module effect from the seed (branch k − branch 0)")
    lines.append("")
    for entry in comparisons["module_effect_from_seed"]:
        _emit(f"Branch {entry['k']} − branch 0", entry)

    lines.append("## Noise floor (branch 0 − repeat)")
    lines.append("")
    _emit("Branch 0 − repeat", comparisons["noise_floor"])

    lines.append("## Familiarity and history (accumulate k − branch k)")
    lines.append("")
    for entry in comparisons["familiarity_and_history"]:
        _emit(f"Accumulate {entry['k']} − branch {entry['k']}", entry)

    lines.append("## Welfare exposure")
    lines.append("")
    rows = report.get("welfare_exposure") or []
    if not rows:
        lines.append("No step has a welfare exposure record.")
    else:
        lines.append(
            "Each boot's welfare exposure from its content-free exposure record: awake hours "
            "the welfare monitor counted and the share tally covered, producer restarts, the "
            "net's rests and freezes, the largest value of each deprivation indicator and the "
            "indicator crossings. A held step waited for a person's answer."
        )
        lines.append("")
        lines.append(
            "| Line | Step | Awake h | Covered h | Restarts | Rests | Freezes | "
            "Boredom | Social | Restless | Neg. valence | Crossings | Hold |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for row in rows:
            maxima = row.get("max_values") or {}
            hold = ", ".join(row.get("hold") or []) or "none"
            if row.get("hold") and row.get("decision"):
                hold += f" ({row['decision']})"
            lines.append(
                f"| {row['line']} | {row['step']} | {_fmt(row.get('awake_hours'))} | "
                f"{_fmt(row.get('covered_hours'))} | {_fmt(row.get('producer_restarts'))} | "
                f"{_fmt(row.get('rests_requested'))} | {_fmt(row.get('freezes_placed'))} | "
                f"{_fmt(maxima.get('boredom_deprived'))} | {_fmt(maxima.get('social_drive_deprived'))} | "
                f"{_fmt(maxima.get('restlessness_deprived'))} | {_fmt(maxima.get('negative_valence'))} | "
                f"{_fmt(row.get('crossings'))} | {hold} |"
            )
    lines.append("")

    lines.append("## Supervisor restarts")
    lines.append("")
    restart_rows = report.get("supervisor_restarts") or []
    if not restart_rows:
        lines.append("No completed step had a supervisor restart.")
    else:
        lines.append(
            "Completed steps in which the supervisor restarted a module, which then "
            "resumed from its last good snapshot (unknown: the incident log could not "
            "be read):"
        )
        lines.append("")
        lines.append("| Line | Step | Restarts |")
        lines.append("|---|---|---|")
        for row in restart_rows:
            count = row.get("supervisor_restarts")
            lines.append(
                f"| {row['line']} | {row['step']} | "
                f"{'unknown' if count is None else count} |"
            )
    lines.append("")

    lines.append("## Limits")
    lines.append("")
    for lim in report["limits"]:
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines)


def _attach_welfare_decisions(study_dir: Path, steps: list[dict[str, Any]]) -> None:
    """Mark each held step with the operator's recorded answer (continue or stop)."""
    path = study_dir / "welfare_acks.jsonl"
    if not path.exists():
        return
    answers: dict[tuple[Any, Any, Any], str] = {}
    for raw in path.read_text().splitlines():
        try:
            ack = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(ack, dict) and ack.get("decision") in ("continue", "stop"):
            answers[(ack.get("line"), ack.get("step"), ack.get("step_ended_at"))] = ack["decision"]
    for step in steps:
        decision = answers.get((step.get("line"), step.get("step"), step.get("ended_at")))
        if decision is not None:
            step["_welfare_decision"] = decision


def _welfare_exposure_rows(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One content-free row per step with an exposure record or a welfare hold."""
    rows: list[dict[str, Any]] = []
    for step in steps:
        exposure = step.get("welfare_exposure")
        hold = step.get("welfare_hold")
        if not isinstance(exposure, dict) and not isinstance(hold, dict):
            continue
        monitor = (exposure or {}).get("monitor") if isinstance(exposure, dict) else None
        monitor = monitor if isinstance(monitor, dict) else {}
        indicators = monitor.get("indicators") if isinstance(monitor.get("indicators"), dict) else {}

        def _hours(value: Any) -> float | None:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value) / 3600.0
            return None

        rows.append(
            {
                "line": step.get("line"),
                "step": step.get("step"),
                "outcome": step.get("outcome"),
                "awake_hours": _hours(monitor.get("awake_seconds")),
                "covered_hours": _hours((exposure or {}).get("covered_awake_seconds")),
                "producer_restarts": (exposure or {}).get("producer_restarts"),
                "rests_requested": monitor.get("rests_requested"),
                "freezes_placed": monitor.get("freezes_placed"),
                "crossings": sum(
                    int(e.get("crossings", 0))
                    for e in indicators.values()
                    if isinstance(e, dict) and isinstance(e.get("crossings"), int)
                )
                if indicators
                else None,
                "max_values": {
                    name: e.get("max_value")
                    for name, e in indicators.items()
                    if isinstance(e, dict)
                },
                "hold": list((hold or {}).get("reasons") or []),
                "decision": step.get("_welfare_decision"),
            }
        )
    return rows


def _step_dir(study_dir: Path, line: Any, step: Any) -> Path:
    if line == "branch":
        return study_dir / "branch" / str(step)
    return study_dir / str(line)


def _supervisor_restart_steps(
    study_dir: Path, steps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Completed steps with at least one supervisor restart, or an unknown count.

    A count the runner could not read (an encrypted incident log) is counted
    again here, with the operator's state key installed when it is available.
    """
    from kaine.research.ignition_study.runner import (
        SUPERVISOR_INCIDENT_DIR,
        count_supervisor_restarts,
    )

    rows: list[dict[str, Any]] = []
    for step in steps:
        if step.get("outcome") != "complete" or "supervisor_restarts" not in step:
            continue
        count = step.get("supervisor_restarts")
        if count is None:
            count, _ = count_supervisor_restarts(
                _step_dir(study_dir, step.get("line"), step.get("step"))
                / SUPERVISOR_INCIDENT_DIR,
                since_iso=step.get("started_at"),
            )
        if count is None or count >= 1:
            rows.append(
                {
                    "line": step.get("line"),
                    "step": step.get("step"),
                    "supervisor_restarts": count,
                }
            )
    return rows


def run_analysis(study_dir: Path | str) -> tuple[Path, Path]:
    """Analyse every completed viewing in ``study_dir`` and write the report."""
    study_dir = Path(study_dir).resolve()
    plan = load_plan(study_dir)
    plan_hash = hashlib.sha256((study_dir / "study.json").read_bytes()).hexdigest()
    steps = _load_steps(study_dir)
    _attach_welfare_decisions(study_dir, steps)

    faculty_modules = list(plan.get("base_modules", [])) + list(plan.get("order", []))
    module_count = len(plan.get("order", []))

    _install_encryptor()

    viewings: list[ViewingResult] = []
    for step in steps:
        if step.get("outcome") != "complete":
            continue
        line = step.get("line")
        if line not in VIEWING_LINES:
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

    comparisons = _build_comparisons(viewings, module_count)
    restart_steps = _supervisor_restart_steps(study_dir, steps)
    exposure_rows = _welfare_exposure_rows(steps)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "study_id": plan.get("study_id"),
        "plan_hash": plan_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module_count": module_count,
        "faculty_modules": faculty_modules,
        "per_viewing": [_viewing_to_dict(v) for v in viewings],
        "comparisons": comparisons,
        "supervisor_restarts": restart_steps,
        "welfare_exposure": exposure_rows,
        "limits": LIMITS,
    }

    analysis_dir = study_dir / "analysis"
    json_path = analysis_dir / "report.json"
    md_path = analysis_dir / "report.md"

    _atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True))
    _atomic_write_text(md_path, _build_markdown(report, viewings))
    return json_path, md_path
