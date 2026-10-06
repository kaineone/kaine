# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline novelty measurement for the content-fingerprint design (novelty-content-fingerprint, task 1.1).

The script replays the seeded perception feed through the real Topos, Audition
and Soma modules on an in-memory fakeredis bus, then feeds the collected events
to Chronos in 0.1 s workspace snapshots.  It reports per-source novelty under
today's fingerprint and under several content-stripping/quantisation candidates,
plus per-field value statistics.

This is a dry probe: no entity boot, no workspace persistence, no raw audio,
frames or vectors are written to the report.

Run: .venv/bin/python scripts/measure_novelty.py
     .venv/bin/python scripts/measure_novelty.py --seconds 100 --seed 42
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from kaine.privacy_filter import VECTOR_FIELDS, _scrub
from kaine.workspace.novelty import fingerprint


class _EventLike(Protocol):
    source: str
    type: str
    payload: Any


class _Record:
    __slots__ = ("id", "source", "type", "payload", "timestamp", "salience", "fingerprint")

    def __init__(
        self,
        id_: Optional[str],
        source: str,
        type_: str,
        payload: Any,
        timestamp: Optional[float],
        salience: Optional[float],
    ) -> None:
        self.id = id_
        self.source = source
        self.type = type_
        self.payload = payload
        self.timestamp = float(timestamp) if timestamp is not None else 0.0
        self.salience = float(salience) if salience is not None else 0.0
        self.fingerprint: Optional[str] = None


def _is_float(value: Any) -> bool:
    return isinstance(value, float) and not isinstance(value, bool)


def _hash_event(source: str, type_: str, payload: Any) -> str:
    body = json.dumps(
        {"source": source, "type": type_, "payload": payload},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.blake2b(body.encode("utf-8"), digest_size=8).hexdigest()


def _strip_payload(payload: Any) -> Any:
    return _scrub(payload, frozenset(), vector_fields=VECTOR_FIELDS)


def _quantize_value(value: Any, resolution: float) -> Any:
    if isinstance(value, dict):
        return {k: _quantize_value(v, resolution) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_quantize_value(v, resolution) for v in value]
    if _is_float(value):
        if not math.isfinite(value):
            # inf/nan carry categorical meaning (e.g. "no interaction yet").
            return repr(value)
        quantized = round(value / resolution) * resolution
        return repr(round(quantized, 10))
    return value


def _categorical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _categorical_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_categorical_value(v) for v in value]
    if _is_float(value):
        return "<float>"
    return value


def _content_payload(payload: Any, candidate: str) -> Any:
    if candidate == "strip":
        return _strip_payload(payload)
    if candidate.startswith("strip+q"):
        resolution = float(candidate.split("+q", 1)[1])
        return _quantize_value(_strip_payload(payload), resolution)
    if candidate == "strip+categorical":
        return _categorical_value(_strip_payload(payload))
    raise ValueError(f"unknown content candidate {candidate!r}")


def candidate_fingerprint(event: _EventLike, candidate: str) -> str:
    """Return the candidate fingerprint for ``event``."""
    if candidate == "current":
        return fingerprint(event)
    payload = _content_payload(event.payload, candidate)
    return _hash_event(event.source, event.type, payload)


def novelty_series(events: Iterable[_EventLike], candidate: str, window: int = 32) -> list[float]:
    """Novelty values for ``events`` under ``candidate`` with a fixed window."""
    fps: deque[str] = deque(maxlen=window)
    counts: Counter[str] = Counter()
    series: list[float] = []
    for ev in events:
        fp = candidate_fingerprint(ev, candidate)
        try:
            ev.fingerprint = fp  # type: ignore[attr-defined]
        except AttributeError:
            pass
        prior = counts.get(fp, 0)
        if len(fps) == window:
            evicted = fps.popleft()
            counts[evicted] -= 1
            if counts[evicted] == 0:
                del counts[evicted]
        fps.append(fp)
        counts[fp] += 1
        series.append(max(0.0, 1.0 - prior / window))
    return series


def _payload_alert(ev: _EventLike) -> Optional[bool]:
    payload = getattr(ev, "payload", None)
    if isinstance(payload, dict):
        alert = payload.get("alert")
        if isinstance(alert, bool):
            return alert
    return None


def summarise(series: list[float], events: Iterable[_EventLike]) -> dict[str, Any]:
    """Summary statistics for a novelty ``series`` and its events."""
    event_list = list(events)
    count = len(series)
    if count == 0:
        return {
            "count": 0,
            "mean_novelty": 0.0,
            "fraction_one": 0.0,
            "distinct_fingerprints": 0,
        }
    mean = statistics.mean(series)
    fraction_one = sum(1.0 for n in series if n == 1.0) / count
    distinct = len({getattr(ev, "fingerprint", id(ev)) for ev in event_list})
    result: dict[str, Any] = {
        "count": count,
        "mean_novelty": mean,
        "fraction_one": fraction_one,
        "distinct_fingerprints": distinct,
    }
    alert_true = [n for n, ev in zip(series, event_list) if _payload_alert(ev) is True]
    alert_false = [n for n, ev in zip(series, event_list) if _payload_alert(ev) is False]
    if alert_true or alert_false:
        result["alert_true_mean"] = statistics.mean(alert_true) if alert_true else None
        result["alert_false_mean"] = statistics.mean(alert_false) if alert_false else None
    return result


def _numeric_leaves(payload: Any, prefix: str = "") -> Iterable[tuple[str, float, str]]:
    """Yield ``(dotted_key, value, kind)`` for every numeric leaf (not bool) in
    the vector-stripped payload; ``kind`` is ``"float"`` or ``"int"``."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            dotted = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                yield from _numeric_leaves(v, dotted)
            elif isinstance(v, bool):
                continue
            elif isinstance(v, int):
                yield dotted, float(v), "int"
            elif _is_float(v) and math.isfinite(v):
                yield dotted, float(v), "float"


def _field_stats(records: list[_Record]) -> dict[str, Any]:
    """Per numeric field (nested keys dotted, ints and floats, vectors stripped):
    range, median absolute step between consecutive events, and how often the
    value changes from one event to the next. A field that changes on nearly
    every event while carrying no perceptual content (a counter, a clock) is a
    candidate for the per-source bookkeeping exclusion list."""
    values: dict[str, list[float]] = {}
    kinds: dict[str, str] = {}
    for rec in records:
        for k, v, kind in _numeric_leaves(_strip_payload(rec.payload)):
            values.setdefault(k, []).append(v)
            kinds[k] = kind
    stats: dict[str, Any] = {}
    for k, vals in values.items():
        steps = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
        changes = sum(1 for d in steps if d != 0.0)
        monotone = all(vals[i] >= vals[i - 1] for i in range(1, len(vals)))
        stats[k] = {
            "kind": kinds[k],
            "n": len(vals),
            "min": min(vals),
            "median": statistics.median(vals),
            "max": max(vals),
            "median_abs_step": statistics.median(steps) if steps else 0.0,
            "change_rate": changes / len(steps) if steps else 0.0,
            "monotone_nondecreasing": monotone,
        }
    return stats


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--models-dir",
        default=os.path.join(os.getcwd(), "state", "models"),
        help="real model weights directory, linked read-only into the throwaway data root",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=100.0,
        help="seconds to let each perception module run (default: 100)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="override the seeded perception feed RNG seed",
    )
    parser.add_argument(
        "--resolutions",
        type=str,
        default="0.1,0.05,0.01,0.001",
        help="comma-separated float quantisation resolutions to test",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="JSON output path (default: a file under a fresh temp directory)",
    )
    parser.add_argument(
        "--modules",
        type=str,
        default="topos,audition,soma",
        help="comma-separated perception modules to replay",
    )
    return parser.parse_args(argv)


def _is_module_enabled(kaine_config: dict[str, Any], name: str) -> bool:
    modules = kaine_config.get("modules")
    if isinstance(modules, dict) and name in modules:
        return bool(modules[name])
    section = kaine_config.get(name)
    return bool(isinstance(section, dict) and section.get("enabled"))


def _make_record(
    id_: Optional[str],
    source: str,
    type_: str,
    payload: Any,
    timestamp: Optional[float],
    salience: Optional[float],
) -> _Record:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            pass
    rec = _Record(id_, source, type_, payload, timestamp, salience)
    if isinstance(payload, dict):
        if rec.timestamp == 0.0 and isinstance(payload.get("timestamp"), (int, float)):
            rec.timestamp = float(payload["timestamp"])
        if rec.salience == 0.0 and isinstance(payload.get("salience"), (int, float)):
            rec.salience = float(payload["salience"])
    return rec


async def _read_stream(bus: Any, stream: str) -> list[_Record]:
    """Read every decoded event on ``stream`` in order.

    ``AsyncBus.read_entries`` returns ``(entries, last_scanned)`` where each entry
    is ``(entry_id, Event)``; the cursor advances to ``last_scanned`` so an
    undecodable batch cannot stall the read.
    """
    records: list[_Record] = []
    last_id = "0"
    while True:
        entries, last_scanned = await bus.read_entries(stream, last_id=last_id, count=10000)
        if last_scanned is None:
            break
        for entry_id, event in entries:
            records.append(
                _make_record(
                    entry_id,
                    event.source,
                    event.type,
                    event.payload,
                    event.timestamp.timestamp(),
                    event.salience,
                )
            )
        last_id = last_scanned
    return records


async def _run_modules(
    selected_modules: list[str],
    kaine_config: dict[str, Any],
    bus: Any,
    seconds: float,
    unmeasured: dict[str, str],
) -> list[str]:
    from kaine.boot.registry import construct_module
    from kaine.modules.registry import ModuleRegistry

    registry = ModuleRegistry()
    constructed: dict[str, Any] = {}

    for name in selected_modules:
        if not _is_module_enabled(kaine_config, name):
            unmeasured[name] = "not enabled in selected profile"
            continue
        try:
            module = construct_module(name, bus, kaine_config, registry=registry)
        except Exception as exc:
            unmeasured[name] = f"construction failed: {type(exc).__name__}: {exc}"
            continue
        if module is None:
            unmeasured[name] = "factory returned None (backend could not load)"
            continue
        if hasattr(registry, "register") and callable(getattr(registry, "register")):
            registry.register(module)
        else:
            registry[name] = module
        constructed[name] = module

    if not constructed:
        return []

    async def _init(name: str, module: Any) -> tuple[str, Optional[Exception]]:
        try:
            await module.initialize()
            return (name, None)
        except Exception as exc:
            return (name, exc)

    init_results = await asyncio.gather(
        *(_init(n, m) for n, m in constructed.items())
    )
    for name, err in init_results:
        if err is not None:
            unmeasured[name] = f"initialization failed: {type(err).__name__}: {err}"
            del constructed[name]

    if constructed:
        await asyncio.sleep(seconds)

    async def _shutdown(name: str, module: Any) -> None:
        try:
            await module.shutdown()
        except Exception as exc:
            print(f"warning: shutdown of {name} failed: {exc}", file=sys.stderr)

    await asyncio.gather(*(_shutdown(n, m) for n, m in constructed.items()))
    return list(constructed.keys())


async def _replay_chronos(
    bus: Any, records_by_source: dict[str, list[_Record]]
) -> list[_Record]:
    from kaine.bus.schema import Event
    from kaine.cycle.types import WorkspaceSnapshot
    from kaine.modules.chronos.featurizer import SnapshotFeaturizer
    from kaine.modules.chronos.module import Chronos

    all_events = sorted(
        (rec for recs in records_by_source.values() for rec in recs),
        key=lambda r: r.timestamp,
    )
    if not all_events:
        return []

    t0 = all_events[0].timestamp
    t1 = all_events[-1].timestamp
    bin_width = 0.1
    n_bins = max(0, int(math.floor((t1 - t0) / bin_width)))

    current_time: list[float] = [t0]

    def clock() -> float:
        return current_time[0]

    chronos = Chronos(
        bus,
        forward_prediction=True,
        reservoir_seed=0,
        clock=clock,
        featurizer=SnapshotFeaturizer(clock=clock),
    )
    await chronos.initialize()

    chronos_records: list[_Record] = []
    try:
        for i in range(n_bins + 1):
            bin_start = t0 + i * bin_width
            bin_end = bin_start + bin_width
            bin_events = [
                ev for ev in all_events if bin_start <= ev.timestamp < bin_end
            ]
            bin_events.sort(key=lambda ev: ev.salience, reverse=True)
            selected = [
                (
                    ev.id,
                    Event(
                        source=ev.source,
                        type=ev.type,
                        payload=ev.payload if isinstance(ev.payload, dict) else {},
                        salience=min(1.0, max(0.0, ev.salience)),
                        timestamp=datetime.fromtimestamp(ev.timestamp, tz=timezone.utc),
                    ),
                )
                for ev in bin_events[:4]
                if ev.id is not None
            ]
            snapshot = WorkspaceSnapshot(
                tick_index=i,
                selected_events=selected,
                inhibited=False,
            )
            current_time[0] = bin_start
            try:
                await chronos.on_workspace(snapshot)
            except Exception as exc:
                print(f"warning: chronos snapshot {i} failed: {exc}", file=sys.stderr)

        chronos_records.extend(await _read_stream(bus, "chronos.out"))
    finally:
        try:
            await chronos.shutdown()
        except Exception as exc:
            print(f"warning: chronos shutdown failed: {exc}", file=sys.stderr)

    return chronos_records


def _build_report(
    records_by_source: dict[str, list[_Record]],
    chronos_records: list[_Record],
    resolutions: list[float],
    unmeasured: dict[str, str],
    config_meta: dict[str, Any],
) -> dict[str, Any]:
    candidates = (
        ["current", "strip"]
        + [f"strip+q{r}" for r in resolutions]
        + ["strip+categorical"]
    )
    report: dict[str, Any] = {
        "config": config_meta,
        "unmeasured": unmeasured,
        "sources": {},
    }

    all_sources: dict[str, list[_Record]] = {
        **records_by_source,
        "chronos": chronos_records,
    }
    for source, records in all_sources.items():
        if not records:
            report["sources"][source] = {
                "events": 0,
                "candidates": {},
                "fields": {},
            }
            continue

        src_report: dict[str, Any] = {
            "events": len(records),
            "candidates": {},
            "fields": _field_stats(records),
        }
        for candidate in candidates:
            series = novelty_series(records, candidate, window=32)
            src_report["candidates"][candidate] = summarise(series, records)
        report["sources"][source] = src_report

    return report


def _print_table(report: dict[str, Any]) -> None:
    print("\nNovelty measurement (no entity boot)")
    print(
        f"{'source':<12} {'candidate':<20} {'count':>6} "
        f"{'mean':>6} {'frac_1':>6} {'distinct':>8}"
    )
    print("-" * 64)
    for source, data in report["sources"].items():
        for candidate, stats in data["candidates"].items():
            print(
                f"{source:<12} {candidate:<20} {stats['count']:>6} "
                f"{stats['mean_novelty']:>6.3f} {stats['fraction_one']:>6.3f} "
                f"{stats['distinct_fingerprints']:>8}"
            )
    if report["unmeasured"]:
        print("\nUnmeasured sources:")
        for name, reason in report["unmeasured"].items():
            print(f"  {name}: {reason}")


async def _main(args: argparse.Namespace) -> int:
    try:
        import fakeredis.aioredis as _fakeredis
    except Exception as exc:
        print(
            "ERROR: fakeredis is required for the in-memory replay bus "
            f"but could not be imported: {exc}",
            file=sys.stderr,
        )
        return 2

    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.config import load_kaine_config

    with tempfile.TemporaryDirectory() as tmpdir:
        operator_path = os.path.join(tmpdir, "operator.toml")
        kaine_config = load_kaine_config(
            profile="thesis_test",
            operator_path=operator_path,
        )

    pf = kaine_config.setdefault("perception_feed", {})
    pf["mode"] = "seeded"
    if args.seed is not None:
        pf["seed"] = args.seed

    # Run inside a throwaway data root so nothing this replay writes (the
    # perception desired-state the capture supervisors read, any module scratch)
    # can land in the host's real state tree. The real model weights are linked
    # in read-only use. The config was loaded above, from the repository.
    models_src = Path(args.models_dir).resolve()
    work = Path(tempfile.mkdtemp(prefix="kaine-novelty-"))
    (work / "state").mkdir()
    if models_src.is_dir():
        (work / "state" / "models").symlink_to(models_src, target_is_directory=True)
    os.chdir(work)
    from kaine.storage import set_data_root

    set_data_root(work)
    from kaine import perception_state

    perception_state.select_virtual_feed()

    selected_modules = [m.strip() for m in args.modules.split(",") if m.strip()]
    resolutions = [float(r.strip()) for r in args.resolutions.split(",") if r.strip()]

    client = _fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    unmeasured: dict[str, str] = {}
    records_by_source: dict[str, list[_Record]] = {}

    try:
        measured = await _run_modules(
            selected_modules,
            kaine_config,
            bus,
            args.seconds,
            unmeasured,
        )

        for name in measured:
            records = await _read_stream(bus, f"{name}.out")
            records_by_source[name] = records

        chronos_records = await _replay_chronos(bus, records_by_source)

        config_meta = {
            "profile": "thesis_test",
            "mode": "seeded",
            "seed": pf.get("seed"),
            "seconds": args.seconds,
            "modules": selected_modules,
            "resolutions": resolutions,
        }
        report = _build_report(
            records_by_source,
            chronos_records,
            resolutions,
            unmeasured,
            config_meta,
        )

        if args.out is None:
            out_dir = tempfile.mkdtemp(prefix="kaine_novelty_")
            out_path = os.path.join(out_dir, "report.json")
        else:
            out_path = args.out

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nFull report written to: {out_path}")
        _print_table(report)

    finally:
        try:
            await bus.close()
        except Exception:
            pass

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
