# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import argparse
import asyncio
import functools
import io
import json
import multiprocessing
import platform
import resource
import sys
import urllib.parse
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil

import kaine
from kaine.config import load_runtime_config
from kaine.residency import (
    SPEECH_LADDERS,
    Demand,
    FootprintEntry,
    Rung,
    fit_report,
    load_catalogue,
    probe_budget,
    save_catalogue,
)
from kaine.residency.budget import ResidencyBudget
from kaine.residency.catalogue import CatalogueError
from kaine.setup.speech_models import DEFAULT_STT, DEFAULT_TTS, model_dir

_GiB = 1 << 30
_MiB = 1 << 20


def host_class(budget: ResidencyBudget) -> str:
    """Format a host class string from a residency budget."""
    total = budget.system.total_bytes
    if total is None:
        size = "unknown"
    else:
        size = f"{round(total / _GiB)}g"
    return f"{budget.topology}-{size}-{platform.machine()}"


@dataclass(frozen=True)
class ComponentInfo:
    """A component selected for calibration."""

    name: str
    kind: str  # "in_process", "external", or "not_measured"
    rung: Rung
    url: str | None = None
    message: str | None = None
    config_section: dict[str, Any] | None = None


def _is_enabled(modules: dict[str, Any], name: str) -> bool:
    return bool(modules.get(name, False))


def _select_components(
    config: dict[str, Any], *, only: set[str] | None = None
) -> list[ComponentInfo]:
    """Select components to calibrate from the runtime config."""
    modules = config.get("modules", {})
    components: list[ComponentInfo] = []

    if _is_enabled(modules, "lingua"):
        section = config.get("lingua", {})
        backend = section.get("backend")
        model_id = section.get("model_id") or ""
        if backend == "llama_cpp":
            components.append(
                ComponentInfo(
                    name="lingua",
                    kind="not_measured",
                    rung=Rung("llama_cpp", model_id),
                    message="not measured: in-process llama_cpp organ calibration is not implemented yet",
                )
            )
        else:
            components.append(
                ComponentInfo(
                    name="lingua",
                    kind="external",
                    rung=Rung(backend or "openai", model_id),
                    url=section.get("chat_url", ""),
                )
            )

    if _is_enabled(modules, "audition"):
        audition = config.get("audition", {})
        if audition.get("transcription_enabled", False):
            backend = audition.get("backend", "speaches")
            if backend == "speaches":
                components.append(
                    ComponentInfo(
                        name="audition.stt",
                        kind="external",
                        rung=Rung("speaches", "medium.en"),
                        url=audition.get("speaches_url", "http://127.0.0.1:8000"),
                    )
                )
            elif backend == "sherpa_onnx":
                model_id = audition.get("sherpa_model_id") or DEFAULT_STT
                components.append(
                    ComponentInfo(
                        name="audition.stt",
                        kind="in_process",
                        rung=Rung("sherpa_onnx", model_id),
                        config_section=audition,
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="audition.stt",
                        kind="not_measured",
                        rung=Rung(backend, ""),
                        message=f"not measured: unknown audition backend {backend!r}",
                    )
                )

    if _is_enabled(modules, "vox"):
        vox = config.get("vox", {})
        backend = vox.get("backend", "chatterbox")
        if backend == "chatterbox":
            components.append(
                ComponentInfo(
                    name="vox.tts",
                    kind="external",
                    rung=Rung("chatterbox", "chatterbox"),
                    url=vox.get("chatterbox_url", "http://127.0.0.1:8883"),
                )
            )
        elif backend == "sherpa_onnx":
            model_id = vox.get("sherpa_model_id") or DEFAULT_TTS
            components.append(
                ComponentInfo(
                    name="vox.tts",
                    kind="in_process",
                    rung=Rung("sherpa_onnx", model_id),
                    config_section=vox,
                )
            )
        else:
            components.append(
                ComponentInfo(
                    name="vox.tts",
                    kind="not_measured",
                    rung=Rung(backend, ""),
                    message=f"not measured: unknown vox backend {backend!r}",
                )
            )

    if any(_is_enabled(modules, m) for m in ("mnemos", "empatheia", "hypnos")):
        embedding = config.get("embedding", {})
        components.append(
            ComponentInfo(
                name="embedder",
                kind="in_process",
                rung=Rung(
                    embedding.get("backend", "numpy"),
                    embedding.get("model_id", "default"),
                ),
                config_section=config,
            )
        )

    if _is_enabled(modules, "topos"):
        topos = config.get("topos", {})
        components.append(
            ComponentInfo(
                name="topos.encoder",
                kind="not_measured",
                rung=Rung(
                    topos.get("encoder_backend", "unknown"),
                    topos.get("model_id", "unknown"),
                ),
                message="not measured: calibration for this component is not implemented yet (task 2.2 follow-up)",
            )
        )

    if _is_enabled(modules, "audition"):
        audition = config.get("audition", {})
        components.append(
            ComponentInfo(
                name="audition.emotion",
                kind="not_measured",
                rung=Rung(
                    audition.get("emotion_backend", "unknown"),
                    audition.get("emotion_model_id", "unknown"),
                ),
                message="not measured: calibration for this component is not implemented yet (task 2.2 follow-up)",
            )
        )

    if only:
        components = [c for c in components if c.name in only]

    return components


def _build_demand(info: ComponentInfo) -> Demand:
    """Build a fit Demand for a selected component."""
    configured = info.rung
    installed: list[Rung] = [configured]
    ladder = SPEECH_LADDERS.get(info.name)
    if ladder is not None:
        for rung in ladder:
            if rung.backend == "sherpa_onnx" and model_dir(rung.model_id).exists():
                if rung not in installed:
                    installed.append(rung)
    interactive = info.name in ("audition.stt", "vox.tts")
    return Demand(
        component=info.name,
        configured=configured,
        installed=tuple(installed),
        interactive=interactive,
    )


def _make_entry(info: ComponentInfo, peak_bytes: int, host: str) -> FootprintEntry:
    """Create a calibration catalogue entry."""
    measured_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return FootprintEntry(
        component=info.name,
        backend=info.rung.backend,
        model_id=info.rung.model_id,
        peak_bytes=peak_bytes,
        device_peak_bytes=None,
        weights_mapped=None,
        host_class=host,
        measured_at=measured_at,
        kaine_version=kaine.__version__,
        source="calibration",
    )


def _fmt_mib(value: int) -> str:
    return f"{value / _MiB:.1f}"


def _read_proc_status_kb(key: str) -> int | None:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(key + ":"):
                    parts = line.split()
                    return int(parts[1])
    except Exception:
        return None
    return None


def _read_baseline_bytes() -> int:
    kb = _read_proc_status_kb("VmRSS")
    if kb is not None:
        return kb * 1024
    try:
        return psutil.Process().memory_info().rss
    except Exception:
        return 0


def _read_peak_bytes() -> int:
    kb = _read_proc_status_kb("VmHWM")
    if kb is not None:
        return kb * 1024
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return maxrss
    return maxrss * 1024


def _child_wrapper(conn, target_fn: Callable[[], Any]) -> None:
    try:
        baseline = _read_baseline_bytes()
        target_fn()
        peak = _read_peak_bytes()
        footprint = peak - baseline
        if footprint < 0:
            footprint = 0
        conn.send((True, footprint, ""))
    except Exception as exc:
        conn.send((False, None, f"{type(exc).__name__}: {exc}"))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _measure_callable_in_child(
    target_fn: Callable[[], Any], timeout: float = 600.0
) -> tuple[bool, int | None, str]:
    """Run a callable in a spawned child and return its memory footprint."""
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child_wrapper, args=(child_conn, target_fn))
    process.start()
    process.join(timeout=timeout)

    try:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            return (False, None, "timed out")

        if not parent_conn.poll(5):
            if process.exitcode is not None and process.exitcode != 0:
                return (False, None, f"child exited with code {process.exitcode}")
            return (False, None, "child produced no result")

        return parent_conn.recv()
    finally:
        parent_conn.close()


@dataclass(frozen=True)
class _ChildTask:
    component: str
    backend: str
    model_id: str
    model_dir: str | None = None
    num_threads: int = 2
    speaker_id: int = 0
    embedder_config: dict[str, Any] | None = None


def _run_component_target(task: _ChildTask) -> None:
    """In-child routine that imports, loads and exercises one component."""
    if task.component == "audition.stt":
        from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT

        client = SherpaMoonshineSTT(
            Path(task.model_dir),
            model_id=task.model_id,
            num_threads=task.num_threads,
        )

        async def _stt() -> None:
            await client.warm_up()
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00" * (16000 * 2))
            wav_bytes = buf.getvalue()
            await client.transcribe(
                wav_bytes, sample_rate=16000, model=task.model_id
            )

        asyncio.run(_stt())

    elif task.component == "vox.tts":
        from kaine.modules.vox.client import TTSRequest
        from kaine.modules.vox.sherpa_tts import SherpaKokoroTTS

        client = SherpaKokoroTTS(
            Path(task.model_dir),
            model_id=task.model_id,
            speaker_id=task.speaker_id,
            num_threads=task.num_threads,
        )

        async def _tts() -> None:
            await client.warm_up()
            await client.synthesize(TTSRequest(text="Calibration."))

        asyncio.run(_tts())

    elif task.component == "embedder":
        from kaine.text_embedding import make_text_embedder

        embedder = make_text_embedder(task.embedder_config or {})

        async def _embed() -> None:
            await embedder.load()
            if hasattr(embedder, "embed"):
                await embedder.embed("calibration")
            elif hasattr(embedder, "encode"):
                await embedder.encode("calibration")
            else:
                raise AttributeError("embedder has no embed or encode method")

        asyncio.run(_embed())
    else:
        raise ValueError(f"unknown in-process component {task.component}")


def _task_for_component(info: ComponentInfo, config: dict[str, Any]) -> _ChildTask | None:
    if info.name == "audition.stt":
        section = info.config_section or {}
        model_id = info.rung.model_id
        model_dir_path = section.get("sherpa_model_dir") or model_dir(model_id)
        return _ChildTask(
            component="audition.stt",
            backend="sherpa_onnx",
            model_id=model_id,
            model_dir=str(model_dir_path),
            num_threads=int(section.get("sherpa_num_threads", 2)),
        )

    if info.name == "vox.tts":
        section = info.config_section or {}
        model_id = info.rung.model_id
        model_dir_path = section.get("sherpa_model_dir") or model_dir(model_id)
        return _ChildTask(
            component="vox.tts",
            backend="sherpa_onnx",
            model_id=model_id,
            model_dir=str(model_dir_path),
            num_threads=int(section.get("sherpa_num_threads", 2)),
            speaker_id=int(section.get("sherpa_speaker_id", 0)),
        )

    if info.name == "embedder":
        return _ChildTask(
            component="embedder",
            backend=info.rung.backend,
            model_id=info.rung.model_id,
            embedder_config=config,
        )

    return None


def _measure_component_in_child(
    info: ComponentInfo, config: dict[str, Any], timeout: float = 600.0
) -> tuple[bool, int | None, str]:
    """Default in-process measurement: one spawned child per component."""
    task = _task_for_component(info, config)
    if task is None:
        return (False, None, f"no child target for {info.name}")
    target = functools.partial(_run_component_target, task)
    return _measure_callable_in_child(target, timeout=timeout)


# Processes that only forward a published container port. The model lives in
# the container, so measuring the forwarder would record a false footprint.
_PORT_PROXIES = frozenset(
    {"docker-proxy", "rootlesskit", "slirp4netns", "pasta", "conmon", "podman"}
)


class ServiceNotMeasurable(Exception):
    """The listening process cannot stand in for the service's footprint."""


def _process_peak_bytes(proc: "psutil.Process") -> int:
    status_path = Path(f"/proc/{proc.pid}/status")
    try:
        with status_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return proc.memory_info().rss


def _measure_service(url: str) -> int | None:
    """Default external-service measurement: inspect a listening process.

    The figure is the peak resident memory of the listening process plus all
    of its descendants (a server may hold its model in a worker child). Returns
    None when no listening process is visible to this user; raises
    ServiceNotMeasurable when the listener is a container port forwarder.
    """
    parsed = urllib.parse.urlparse(url)
    port = parsed.port
    if port is None:
        return None

    try:
        connections = psutil.net_connections(kind="inet")
    except Exception:
        return None

    pids = sorted(
        {
            c.pid
            for c in connections
            if c.status == psutil.CONN_LISTEN and c.laddr.port == port and c.pid is not None
        }
    )
    if not pids:
        return None

    try:
        proc = psutil.Process(pids[0])
        if proc.name() in _PORT_PROXIES:
            raise ServiceNotMeasurable(
                f"{url} is published by a container port forwarder ({proc.name()}); "
                "the model runs inside the container, so measure it there"
            )
        total = _process_peak_bytes(proc)
        for child in proc.children(recursive=True):
            try:
                total += _process_peak_bytes(child)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return total
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    isatty: Callable[[], bool] = sys.stdin.isatty,
    measure_in_child: Callable[
        [ComponentInfo, dict[str, Any], float], tuple[bool, int | None, str]
    ]
    | None = None,
    measure_service: Callable[[str], int | None] | None = None,
    budget_fn: Callable[[], ResidencyBudget] = probe_budget,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.footprint",
        description="Calibrate per-component memory footprints for KAINE.",
    )
    parser.add_argument("--yes", action="store_true", help="skip confirmation")
    parser.add_argument(
        "--catalogue",
        default="state/residency/footprints.json",
        help="catalogue file to update",
    )
    parser.add_argument(
        "--config-json",
        default=None,
        help="read config from this JSON file instead of the runtime config",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="per-component measurement timeout in seconds",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="only measure this component (can be given multiple times)",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if measure_in_child is None:
        measure_in_child = _measure_component_in_child
    if measure_service is None:
        measure_service = _measure_service

    try:
        if args.config_json:
            config = json.loads(Path(args.config_json).read_text(encoding="utf-8"))
        else:
            config = load_runtime_config()
    except Exception as exc:
        print(f"error: failed to load config: {exc}", file=sys.stderr)
        return 2

    only_set = set(args.only) if args.only else None
    components = _select_components(config, only=only_set)
    if not components:
        print("no components selected for calibration")
        return 0

    for info in components:
        if info.kind == "in_process":
            print(f"{info.name} ({info.rung.label}): will be LOADED")
        elif info.kind == "external":
            print(f"{info.name} ({info.rung.label}): will be INSPECTED at {info.url}")
        else:
            print(f"{info.name} ({info.rung.label}): {info.message}")

    to_measure = [c for c in components if c.kind != "not_measured"]
    if to_measure:
        if not args.yes:
            if not isatty():
                print(
                    "error: stdin is not a terminal; use --yes to run non-interactively",
                    file=sys.stderr,
                )
                return 2
            answer = input_fn(f"Load and measure {len(to_measure)} component(s)? [y/N] ")
            if answer.lower() not in ("y", "yes"):
                print("nothing was measured")
                return 0

    try:
        budget = budget_fn()
    except Exception as exc:
        print(f"error: failed to probe budget: {exc}", file=sys.stderr)
        return 2

    host = host_class(budget)
    budget_mib = (
        budget.system.budget_bytes / _MiB
        if budget.system.budget_bytes is not None
        else None
    )
    print(
        f"budget: {budget.topology}, system budget = "
        f"{_fmt_mib(int(budget_mib * _MiB)) if budget_mib is not None else 'unknown'} MiB"
    )
    for note in budget.notes:
        print(f"  note: {note}")

    catalogue_path = Path(args.catalogue)
    try:
        catalogue = load_catalogue(catalogue_path)
    except CatalogueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    demands: list[Demand] = []
    had_failure = False

    for info in components:
        demands.append(_build_demand(info))

        if info.kind == "not_measured":
            print(f"{info.name}: {info.message}")
            continue

        if info.kind == "external":
            try:
                peak_bytes = measure_service(info.url)
            except ServiceNotMeasurable as exc:
                print(f"{info.name}: not measured: {exc}")
                continue
            if peak_bytes is None:
                msg = (
                    f"not measured: {info.url} is not running or not visible to this "
                    "user; start it and rerun"
                )
                print(f"{info.name}: {msg}")
                continue
            entry = _make_entry(info, peak_bytes, host)
            catalogue = catalogue.merge(entry)
            print(
                f"{info.name}: {_fmt_mib(peak_bytes)} MiB "
                f"(external, peak since the service started)"
            )
            continue

        # in_process
        ok, peak_bytes, err = measure_in_child(info, config, timeout=args.timeout)
        if not ok:
            if err == "timed out":
                print(f"{info.name}: timed out")
            else:
                print(f"{info.name}: failed: {err}")
            had_failure = True
            continue
        entry = _make_entry(info, peak_bytes, host)  # type: ignore[arg-type]
        catalogue = catalogue.merge(entry)
        print(f"{info.name}: {_fmt_mib(peak_bytes)} MiB")

    save_catalogue(catalogue_path, catalogue)

    report = fit_report(
        budget=budget,
        catalogue=catalogue,
        demands=demands,
        host_class=host,
        pin="lingua",
    )
    print(report.render())

    return 1 if had_failure else 0


if __name__ == "__main__":
    sys.exit(main())
