# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Calibrate per-component memory footprints for KAINE.

This command loads each configured model once in its own spawned child
process, exercises it with synthetic input, and records only the peak
resident (and optional accelerator) memory size to the footprint
catalogue.  It never downloads weights or other assets, never writes
text/audio/images/latents to disk, and is content-free: the catalogue
holds only sizes and identifiers.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import functools
import io
import ipaddress
import json
import math
import multiprocessing
import os
import re
import resource
import signal
import subprocess
import sys
import time
import urllib.parse
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psutil

from kaine.config import load_runtime_config
from kaine.hostmem import classify_accelerator_memory
from kaine.model_paths import DEFAULT_STT, DEFAULT_TTS, speech_model_dir
from kaine.modules.topos.internvideo_next_loader import default_weights_dir
from kaine.residency.budget import current_budgets
from kaine.residency.catalogue import (
    DEFAULT_CATALOGUE_PATH,
    Entry,
    load_catalogue,
    upsert,
    write_catalogue,
)
from kaine.residency.fit import Need, fit_report
from kaine.speech_manifest import is_installed
from kaine.storage import install_data_root
from kaine.text_embedding import resolve_embedding_config
from kaine.text_embedding_numpy import resolve_model_dir

_MiB = 1 << 20


class HostClassUnknown(Exception):
    """The accelerator's memory topology cannot be classified."""


class ServiceNotMeasurable(Exception):
    """The listening process cannot stand in for the service's footprint."""


# Processes that only forward a published container port. The model lives in
# the container, so measuring the forwarder would record a false footprint.
_PORT_PROXIES = frozenset(
    {"docker-proxy", "rootlesskit", "slirp4netns", "pasta", "conmon", "podman"}
)

# Processes that may legitimately stand in for an external model service.
_SERVICE_PROCESSES = frozenset(
    {"llama-server", "ollama", "python", "python3", "uvicorn", "gunicorn"}
)


@dataclass(frozen=True)
class ComponentInfo:
    """A component selected for calibration."""

    name: str
    kind: str  # "in_process", "external", "absent", "not_measured"
    backend: str
    model_id: str
    fetch_command: str | None = None
    message: str | None = None
    url: str | None = None
    config_section: dict[str, Any] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _ChildTask:
    component: str
    backend: str
    model_id: str
    model_dir: str | None = None
    num_threads: int = 2
    speaker_id: int = 0
    embedder_config: dict[str, Any] | None = None
    device_preference: str = "auto"
    weights_dir: str | None = None
    clip_len: int = 16
    clip_resolution: int = 224
    emotion_device: str = "cpu"


def _fmt_mib(value: int) -> str:
    return f"{value / _MiB:.1f}"


def _positive_finite_float(value: str) -> float:
    try:
        f = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid float value: {value!r}") from exc
    if not math.isfinite(f) or f <= 0:
        raise argparse.ArgumentTypeError("timeout must be a finite number > 0")
    return f


def _is_loopback_host(host: str) -> bool:
    host = host.lower()
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_loopback
    except ValueError:
        return False


def _is_loopback_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.hostname is None:
        return False
    return _is_loopback_host(parsed.hostname)


def _apply_child_env_allowlist() -> None:
    """Reduce os.environ to a known-safe allowlist in spawned children."""
    allowed_names = frozenset(
        {
            "PATH",
            "HOME",
            "LANG",
            "TMPDIR",
            "CUDA_VISIBLE_DEVICES",
            "HF_HOME",
            "HF_HUB_CACHE",
            "TRANSFORMERS_CACHE",
            "KAINE_MODELS_DIR",
            "KAINE_DATA_ROOT",
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "LD_LIBRARY_PATH",
            "PYTHONPATH",
        }
    )
    allowed_prefixes = ("LC_",)

    kept: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in allowed_names or key.startswith(allowed_prefixes):
            kept[key] = value

    os.environ.clear()
    os.environ.update(kept)


def _read_proc_status_kb(key: str) -> int | None:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(key + ":"):
                    parts = line.split()
                    return int(parts[1])
    except Exception:
        # /proc/self/status may be unreadable in restricted environments.
        return None
    return None


def _read_baseline_bytes() -> int:
    kb = _read_proc_status_kb("VmRSS")
    if kb is not None:
        return kb * 1024
    try:
        return psutil.Process().memory_info().rss
    except Exception:
        # Fall back to a zero baseline if psutil also fails.
        return 0


def _read_peak_bytes() -> int:
    kb = _read_proc_status_kb("VmHWM")
    if kb is not None:
        return kb * 1024
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return maxrss
    return maxrss * 1024


def _set_offline_env() -> None:
    """Disable network access for Hugging Face tooling in spawned children."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def host_class(*, torch_module: Any | None = None) -> str:
    """Return the host memory class: one of 'unified', 'discrete', or 'cpu'."""
    torch = torch_module
    if torch is None:
        try:
            import torch  # type: ignore[import]
        except Exception:
            return "cpu"
    if not torch.cuda.is_available():
        return "cpu"
    classification = classify_accelerator_memory(0, torch=torch)
    if classification.state in ("unified", "discrete"):
        return classification.state
    reason = classification.unknown_reason or "unknown reason"
    raise HostClassUnknown(reason)


def _hf_cached(model_id: str, *, cache_dir: str | Path | None = None) -> bool:
    """Check whether a Hugging Face model is available in the local cache.

    Probes the hub cache read-only: no downloader is ever invoked.
    """
    try:
        if cache_dir is None:
            from huggingface_hub import constants

            cache = getattr(constants, "HF_HUB_CACHE", None)
            if cache is None:
                cache = getattr(constants, "HUGGINGFACE_HUB_CACHE", None)
            if cache is None:
                return False
        else:
            cache = cache_dir

        cache_path = Path(cache)
        safe_id = model_id.replace("/", "--")
        snapshots = cache_path / f"models--{safe_id}" / "snapshots"
        if not snapshots.is_dir():
            return False
        for child in snapshots.iterdir():
            if child.is_dir() and any(child.iterdir()):
                return True
        return False
    except Exception:
        # The cache layout is not the standard Hugging Face structure.
        return False


def _sherpa_present(model_id: str, model_dir: str | None) -> bool:
    if model_dir:
        return Path(model_dir).is_dir()
    return is_installed(model_id)


def _catalogue_file(path: str | Path | None) -> Path:
    """The file the catalogue functions read and write for ``path``."""
    if path is not None:
        return Path(path)
    from kaine.storage import resolve

    return Path(resolve(DEFAULT_CATALOGUE_PATH))


def _is_enabled(modules: dict[str, Any], name: str) -> bool:
    return bool(modules.get(name, False))


def _select_components(
    config: dict[str, Any], *, only: set[str] | None = None
) -> list[ComponentInfo]:
    """Select components to calibrate from the runtime config."""
    modules = config.get("modules", {})
    components: list[ComponentInfo] = []
    default_stt = DEFAULT_STT
    default_tts = DEFAULT_TTS

    if _is_enabled(modules, "lingua"):
        section = config.get("lingua", {})
        backend = section.get("backend")
        model_id = section.get("model_id") or ""
        if backend == "llama_cpp":
            components.append(
                ComponentInfo(
                    name="lingua",
                    kind="not_measured",
                    backend=backend,
                    model_id=model_id,
                    message="not measured: in-process llama_cpp organ calibration is not implemented yet",
                )
            )
        else:
            url = section.get("chat_url", "")
            if not _is_loopback_url(url):
                components.append(
                    ComponentInfo(
                        name="lingua",
                        kind="not_measured",
                        backend=backend or "openai",
                        model_id=model_id,
                        message="not measured: remote_endpoint",
                        url=url,
                        reason="remote_endpoint",
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="lingua",
                        kind="external",
                        backend=backend or "openai",
                        model_id=model_id,
                        url=url,
                    )
                )

    if _is_enabled(modules, "audition"):
        audition = config.get("audition", {})
        if audition.get("transcription_enabled", False):
            backend = audition.get("backend", "speaches")
            if backend == "speaches":
                url = audition.get("speaches_url", "http://127.0.0.1:8000")
                if not _is_loopback_url(url):
                    components.append(
                        ComponentInfo(
                            name="audition.stt",
                            kind="not_measured",
                            backend="speaches",
                            model_id="medium.en",
                            message="not measured: remote_endpoint",
                            url=url,
                            reason="remote_endpoint",
                        )
                    )
                else:
                    components.append(
                        ComponentInfo(
                            name="audition.stt",
                            kind="external",
                            backend="speaches",
                            model_id="medium.en",
                            url=url,
                        )
                    )
            elif backend == "sherpa_onnx":
                model_id = audition.get("sherpa_model_id") or default_stt
                model_dir = audition.get("sherpa_model_dir")
                if _sherpa_present(model_id, model_dir):
                    components.append(
                        ComponentInfo(
                            name="audition.stt",
                            kind="in_process",
                            backend="sherpa_onnx",
                            model_id=model_id,
                            config_section=audition,
                        )
                    )
                else:
                    components.append(
                        ComponentInfo(
                            name="audition.stt",
                            kind="absent",
                            backend="sherpa_onnx",
                            model_id=model_id,
                            fetch_command=f"python -m kaine.setup.speech_models --stt {model_id}",
                        )
                    )
            else:
                components.append(
                    ComponentInfo(
                        name="audition.stt",
                        kind="not_measured",
                        backend=backend,
                        model_id="",
                        message=f"not measured: unknown audition backend {backend!r}",
                    )
                )

    if _is_enabled(modules, "vox"):
        vox = config.get("vox", {})
        backend = vox.get("backend", "chatterbox")
        if backend == "chatterbox":
            url = vox.get("chatterbox_url", "http://127.0.0.1:8883")
            if not _is_loopback_url(url):
                components.append(
                    ComponentInfo(
                        name="vox.tts",
                        kind="not_measured",
                        backend="chatterbox",
                        model_id="chatterbox",
                        message="not measured: remote_endpoint",
                        url=url,
                        reason="remote_endpoint",
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="vox.tts",
                        kind="external",
                        backend="chatterbox",
                        model_id="chatterbox",
                        url=url,
                    )
                )
        elif backend == "sherpa_onnx":
            model_id = vox.get("sherpa_model_id") or default_tts
            model_dir = vox.get("sherpa_model_dir")
            if _sherpa_present(model_id, model_dir):
                components.append(
                    ComponentInfo(
                        name="vox.tts",
                        kind="in_process",
                        backend="sherpa_onnx",
                        model_id=model_id,
                        config_section=vox,
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="vox.tts",
                        kind="absent",
                        backend="sherpa_onnx",
                        model_id=model_id,
                        fetch_command=f"python -m kaine.setup.speech_models --tts {model_id}",
                    )
                )
        else:
            components.append(
                ComponentInfo(
                    name="vox.tts",
                    kind="not_measured",
                    backend=backend,
                    model_id="",
                    message=f"not measured: unknown vox backend {backend!r}",
                )
            )

    if any(v for v in modules.values() if v):
        emb = resolve_embedding_config(config)
        backend = emb["backend"]
        model_id = emb["model_id"]
        if backend == "numpy":
            try:
                resolve_model_dir(model_id, model_path=emb.get("model_path"))
                components.append(
                    ComponentInfo(
                        name="embedding",
                        kind="in_process",
                        backend="numpy",
                        model_id=model_id,
                        config_section=config,
                    )
                )
            except FileNotFoundError:
                components.append(
                    ComponentInfo(
                        name="embedding",
                        kind="absent",
                        backend="numpy",
                        model_id=model_id,
                        fetch_command="python -m kaine.setup.provision",
                    )
                )
            except Exception as exc:
                components.append(
                    ComponentInfo(
                        name="embedding",
                        kind="not_measured",
                        backend="numpy",
                        model_id=model_id,
                        message=f"not measured: {type(exc).__name__}: {exc}",
                    )
                )
        elif backend == "sentence_transformers":
            if _hf_cached(model_id):
                components.append(
                    ComponentInfo(
                        name="embedding",
                        kind="in_process",
                        backend="sentence_transformers",
                        model_id=model_id,
                        config_section=config,
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="embedding",
                        kind="absent",
                        backend="sentence_transformers",
                        model_id=model_id,
                        fetch_command="python -m kaine.setup.provision",
                    )
                )
        else:
            components.append(
                ComponentInfo(
                    name="embedding",
                    kind="not_measured",
                    backend=backend,
                    model_id=model_id,
                    message=f"not measured: unknown embedding backend {backend!r}",
                )
            )

    if _is_enabled(modules, "topos"):
        topos = config.get("topos", {})
        backend = topos.get("encoder_backend", "internvideo_next")
        if backend == "internvideo_next":
            model_id = topos.get("encoder_model_id") or "internvideo_next"
            weights_dir = topos.get("encoder_local_dir") or default_weights_dir()
            present = (Path(weights_dir) / "model.safetensors").is_file()
            if present:
                components.append(
                    ComponentInfo(
                        name="topos.encoder",
                        kind="in_process",
                        backend="internvideo_next",
                        model_id=model_id,
                        config_section=topos,
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="topos.encoder",
                        kind="absent",
                        backend="internvideo_next",
                        model_id=model_id,
                        fetch_command="python -m kaine.setup.internvideo_next --yes",
                    )
                )
        elif backend == "dinov2":
            model_id = topos.get("encoder_model_id") or "facebook/dinov2-small"
            if _hf_cached(model_id):
                components.append(
                    ComponentInfo(
                        name="topos.encoder",
                        kind="in_process",
                        backend="dinov2",
                        model_id=model_id,
                        config_section=topos,
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="topos.encoder",
                        kind="absent",
                        backend="dinov2",
                        model_id=model_id,
                        fetch_command="python -m kaine.setup.provision",
                    )
                )
        else:
            components.append(
                ComponentInfo(
                    name="topos.encoder",
                    kind="not_measured",
                    backend=backend,
                    model_id="",
                    message=f"not measured: unknown topos encoder backend {backend!r}",
                )
            )

    if _is_enabled(modules, "audition"):
        audition = config.get("audition", {})
        model_id = audition.get("emotion_model_id", "emotion2vec/emotion2vec_plus_base")
        if model_id:
            if _hf_cached(model_id):
                components.append(
                    ComponentInfo(
                        name="audition.emotion",
                        kind="in_process",
                        backend="emotion2vec",
                        model_id=model_id,
                        config_section=audition,
                    )
                )
            else:
                components.append(
                    ComponentInfo(
                        name="audition.emotion",
                        kind="absent",
                        backend="emotion2vec",
                        model_id=model_id,
                        fetch_command="python -m kaine.setup.provision",
                    )
                )

    if only:
        components = [c for c in components if c.name in only]

    return components


def _silence_wav(duration: float = 1.0, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * int(duration * sample_rate * 2))
    return buf.getvalue()


def _sine_wav(
    frequency: float = 440.0, duration: float = 1.0, sample_rate: int = 16000
) -> bytes:
    import array

    samples = array.array(
        "h",
        (
            int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
            for i in range(int(duration * sample_rate))
        ),
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def _target_audition_stt(task: _ChildTask) -> dict[str, Any]:
    _set_offline_env()
    from pathlib import Path

    from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT

    client = SherpaMoonshineSTT(
        Path(task.model_dir),
        model_id=task.model_id,
        num_threads=task.num_threads,
    )

    async def _stt() -> None:
        await client.warm_up()
        await client.transcribe(
            _silence_wav(), sample_rate=16000, model=task.model_id
        )
        if hasattr(client, "aclose"):
            await client.aclose()
        elif hasattr(client, "close"):
            await client.close()

    asyncio.run(_stt())
    return {}


def _target_vox_tts(task: _ChildTask) -> dict[str, Any]:
    _set_offline_env()
    from pathlib import Path

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
        if hasattr(client, "aclose"):
            await client.aclose()
        elif hasattr(client, "close"):
            await client.close()

    asyncio.run(_tts())
    return {}


def _target_embedding(task: _ChildTask) -> dict[str, Any]:
    _set_offline_env()
    from kaine.text_embedding import make_text_embedder

    embedder = make_text_embedder(task.embedder_config or {})

    async def _embed() -> None:
        if hasattr(embedder, "ensure_loaded"):
            await embedder.ensure_loaded()
        if hasattr(embedder, "encode"):
            await embedder.encode("calibration")
        elif hasattr(embedder, "embed"):
            await embedder.embed("calibration")
        else:
            raise AttributeError("embedder has no embed or encode method")

    asyncio.run(_embed())

    mapped = False
    if hasattr(embedder, "weights_residency"):
        # A property on the NumPy embedder: mapped vs private weight bytes.
        residency = embedder.weights_residency
        mapped = bool(residency.get("mapped_bytes", 0) > 0)

    if hasattr(embedder, "unload"):
        try:
            if asyncio.iscoroutinefunction(embedder.unload):
                asyncio.run(embedder.unload())
            else:
                embedder.unload()
        except Exception:
            # Unload is best-effort; a failure should not hide a valid measurement.
            pass

    return {"mapped": mapped}


def _target_topos_encoder(task: _ChildTask) -> dict[str, Any]:
    _set_offline_env()
    from PIL import Image

    from kaine.modules.topos.encoder import make_encoder

    enc = make_encoder(
        task.backend,
        model_id=task.model_id,
        device_preference=task.device_preference,
        weights_dir=task.weights_dir,
        clip_len=task.clip_len,
        clip_resolution=task.clip_resolution,
    )
    img = Image.new(
        "RGB",
        (task.clip_resolution, task.clip_resolution),
        (128, 128, 128),
    )

    async def _encode() -> None:
        await enc.ensure_loaded()
        if task.backend == "internvideo_next":
            await enc.encode_clip([img] * task.clip_len)
        else:
            await enc.encode(img)
        if hasattr(enc, "unload"):
            await enc.unload()

    asyncio.run(_encode())
    return {}


def _target_audition_emotion(
    task: _ChildTask,
    classifier_cls: Any | None = None,
) -> dict[str, Any]:
    _set_offline_env()
    if classifier_cls is None:
        from kaine.modules.audition.emotion import Emotion2vecClassifier

        classifier_cls = Emotion2vecClassifier

    clf = classifier_cls(task.model_id, device=task.emotion_device)

    async def _run() -> None:
        await clf.ensure_loaded()
        if not clf.loaded:
            raise RuntimeError("Emotion2vecClassifier load degraded (loaded=False)")
        await clf.classify(_sine_wav(), sample_rate=16000)

    asyncio.run(_run())
    return {}


def _run_component_target(task: _ChildTask) -> dict[str, Any]:
    """In-child routine that imports, loads and exercises one component."""
    if task.component == "audition.stt":
        return _target_audition_stt(task)
    if task.component == "vox.tts":
        return _target_vox_tts(task)
    if task.component == "embedding":
        return _target_embedding(task)
    if task.component == "topos.encoder":
        return _target_topos_encoder(task)
    if task.component == "audition.emotion":
        return _target_audition_emotion(task)
    raise ValueError(f"unknown in-process component {task.component}")


def _task_for_component(
    info: ComponentInfo, config: dict[str, Any]
) -> _ChildTask | None:
    if info.name == "audition.stt":
        section = info.config_section or {}
        model_id = info.model_id
        model_dir = section.get("sherpa_model_dir") or speech_model_dir(model_id)
        return _ChildTask(
            component="audition.stt",
            backend="sherpa_onnx",
            model_id=model_id,
            model_dir=str(model_dir),
            num_threads=int(section.get("sherpa_num_threads", 2)),
        )

    if info.name == "vox.tts":
        section = info.config_section or {}
        model_id = info.model_id
        model_dir = section.get("sherpa_model_dir") or speech_model_dir(model_id)
        return _ChildTask(
            component="vox.tts",
            backend="sherpa_onnx",
            model_id=model_id,
            model_dir=str(model_dir),
            num_threads=int(section.get("sherpa_num_threads", 2)),
            speaker_id=int(section.get("sherpa_speaker_id", 0)),
        )

    if info.name == "embedding":
        return _ChildTask(
            component="embedding",
            backend=info.backend,
            model_id=info.model_id,
            embedder_config=config,
        )

    if info.name == "topos.encoder":
        section = info.config_section or {}
        weights_dir = section.get("encoder_local_dir") or default_weights_dir()
        return _ChildTask(
            component="topos.encoder",
            backend=info.backend,
            model_id=info.model_id,
            device_preference=section.get("device", "auto"),
            weights_dir=str(weights_dir),
            clip_len=int(section.get("clip_len", 16)),
            clip_resolution=int(section.get("clip_resolution", 224)),
        )

    if info.name == "audition.emotion":
        section = info.config_section or {}
        return _ChildTask(
            component="audition.emotion",
            backend=info.backend,
            model_id=info.model_id,
            emotion_device=section.get("emotion_device", "cpu"),
        )

    return None


def _child_main(conn: Any, target_fn: Callable[[], dict[str, Any]]) -> None:
    """Spawed-child entry point: detach into a new process group, then wrap."""
    # Detach into a new process group so a parent timeout can terminate the
    # whole subtree with killpg without leaving orphan model processes.
    if hasattr(os, "setsid"):
        os.setsid()
    _child_wrapper(conn, target_fn)


def _child_wrapper(conn: Any, target_fn: Callable[[], dict[str, Any]]) -> None:
    # Restrict the child to a small allowlist before any model code runs. This
    # prevents secrets and proxy vars from leaking into downloaded weights'
    # subprocesses or logs.
    _apply_child_env_allowlist()
    _set_offline_env()

    try:
        baseline = _read_baseline_bytes()

        # Import torch here so we can measure per-device memory after the
        # model code runs. On CPU-only hosts this is a no-op.
        torch: Any | None = None
        try:
            import torch  # type: ignore[import]
        except Exception:
            # Torch is not installed or cannot be imported in this child.
            torch = None

        result = target_fn()
        peak = _read_peak_bytes()

        if peak <= baseline:
            conn.send(
                {
                    "ok": False,
                    "peak_bytes": None,
                    "device": None,
                    "device_bytes": None,
                    "mapped": False,
                    "error": "invalid measurement: peak <= baseline",
                }
            )
            return

        footprint = peak - baseline

        device: str | None = None
        device_bytes: int | None = None
        mapped = (
            bool(result.get("mapped", False)) if isinstance(result, dict) else False
        )

        if torch is not None and torch.cuda.is_available():
            # Per device, the larger of torch's peak reservation (survives
            # frees) and nvidia-smi's figure for this process (includes the
            # CUDA context and non-torch allocations). A device that cannot
            # be read raises, so the measurement fails instead of recording
            # "no device".
            usage: dict[str, int] = {}
            for i in range(torch.cuda.device_count()):
                reserved_i = int(torch.cuda.max_memory_reserved(i))
                if reserved_i > 0:
                    usage[f"cuda:{i}"] = reserved_i
            smi = _nvidia_smi_usage({os.getpid()}, torch)
            for name, smi_bytes in (smi or {}).items():
                usage[name] = max(usage.get(name, 0), smi_bytes)
            if usage:
                device, device_bytes = max(usage.items(), key=lambda item: item[1])

        conn.send(
            {
                "ok": True,
                "peak_bytes": footprint,
                "device": device,
                "device_bytes": device_bytes,
                "mapped": mapped,
                "error": "",
            }
        )
    except Exception as exc:
        conn.send(
            {
                "ok": False,
                "peak_bytes": None,
                "device": None,
                "device_bytes": None,
                "mapped": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        try:
            conn.close()
        except Exception:
            # The parent may have closed its end of the pipe already.
            pass


def _validate_child_record(data: Any) -> tuple[bool, str]:
    """Validate a result record from a child process.

    Returns (True, "") for a valid record, otherwise (False, error_message).
    """
    if not isinstance(data, dict):
        return False, f"invalid child record: expected dict, got {type(data).__name__}"
    if data.get("ok") is not True:
        return False, f"invalid child record: ok={data.get('ok')!r}"
    peak = data.get("peak_bytes")
    if isinstance(peak, bool) or not isinstance(peak, int) or peak <= 0:
        return False, f"invalid child record: peak_bytes={peak!r}"
    device = data.get("device")
    if device is not None:
        if not isinstance(device, str) or not re.fullmatch(r"cuda:\d+", device):
            return False, f"invalid child record: device={device!r}"
    device_bytes = data.get("device_bytes")
    if device_bytes is not None:
        if (
            isinstance(device_bytes, bool)
            or not isinstance(device_bytes, int)
            or device_bytes <= 0
        ):
            return False, f"invalid child record: device_bytes={device_bytes!r}"
    mapped = data.get("mapped")
    if not isinstance(mapped, bool):
        return False, f"invalid child record: mapped={mapped!r}"
    return True, ""


def _measure_callable_in_child(
    target_fn: Callable[[], dict[str, Any]],
    timeout: float = 600.0,
) -> tuple[bool, int | None, int | None, str | None, bool, str]:
    """Run a callable in a spawned child and return its memory footprint."""
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child_main, args=(child_conn, target_fn))
    process.start()
    # Close the parent's copy of the child's connection immediately so a crash
    # or exit in the child is visible as EOF on the receive end.
    child_conn.close()

    def _stop_group(pgid: int) -> None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        try:
            ready = parent_conn.poll(timeout)
        except OSError as exc:
            return (False, None, None, None, False, f"child poll failed: {exc}")

        if ready:
            try:
                data = parent_conn.recv()
            except EOFError:
                return (
                    False,
                    None,
                    None,
                    None,
                    False,
                    "child closed connection without result",
                )
            except OSError as exc:
                return (False, None, None, None, False, f"child recv failed: {exc}")
            except Exception as exc:
                # PicklingError and other deserialization problems land here.
                return (
                    False,
                    None,
                    None,
                    None,
                    False,
                    f"child result unreadable: {exc}",
                )

            if isinstance(data, dict) and data.get("ok") is False:
                child_msg = str(data.get("error") or "failed")
                process.join(timeout=30)
                if process.is_alive():
                    _stop_group(process.pid)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                return (False, None, None, None, False, child_msg)

            ok, err = _validate_child_record(data)
            if not ok:
                process.join(timeout=30)
                if process.is_alive():
                    _stop_group(process.pid)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                return (False, None, None, None, False, err)

            note = ""
            process.join(timeout=30)
            if process.is_alive():
                # The child reported and then failed to exit: stop it, but the
                # measurement it sent stands. Say so, so it is never mistaken
                # for a crash.
                _stop_group(process.pid)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                process.join(timeout=2)
                note = "the child was stopped after reporting; the measurement stands"

            return (
                True,
                data["peak_bytes"],
                data["device_bytes"],
                data["device"],
                data["mapped"],
                note,
            )

        # Timeout: the child is still running.
        if process.is_alive():
            _stop_group(process.pid)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            process.join(timeout=2)
            return (False, None, None, None, False, "timed out")

        return (
            False,
            None,
            None,
            None,
            False,
            f"child exited with code {process.exitcode}",
        )
    finally:
        parent_conn.close()
        if process.is_alive():
            _stop_group(process.pid)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            process.join(timeout=2)


def _measure_component(
    info: ComponentInfo, config: dict[str, Any], timeout: float = 600.0
) -> tuple[bool, int | None, int | None, str | None, bool, str]:
    """Default in-process measurement: one spawned child per component."""
    task = _task_for_component(info, config)
    if task is None:
        return (False, None, None, None, False, f"no child target for {info.name}")
    target = functools.partial(_run_component_target, task)
    return _measure_callable_in_child(target, timeout=timeout)


def _process_peak_bytes(proc: psutil.Process) -> int:
    """Peak resident memory (VmHWM) of ``proc``.

    The current RSS is never used instead: it can be far below the peak, and
    an under-estimate is the unsafe direction. Raises ``psutil.NoSuchProcess``
    when the process has exited and ``ServiceNotMeasurable`` when its peak
    cannot be read.
    """
    status_path = Path(f"/proc/{proc.pid}/status")
    try:
        with status_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except FileNotFoundError:
        if Path("/proc/self/status").exists():
            # /proc works, so the process exited after it was listed.
            raise psutil.NoSuchProcess(proc.pid) from None
        raise ServiceNotMeasurable(
            "this platform does not report peak process memory (VmHWM)"
        ) from None
    except OSError as exc:
        raise ServiceNotMeasurable(
            f"the peak memory of pid {proc.pid} could not be read ({exc})"
        ) from None
    raise ServiceNotMeasurable(f"pid {proc.pid} reports no peak memory (VmHWM)")


def _listener_root_pid(url: str) -> int | None:
    """Return the root listener PID for a local service URL, if any."""
    parsed = urllib.parse.urlparse(url)
    port = parsed.port
    if port is None:
        return None
    try:
        connections = psutil.net_connections(kind="inet")
    except Exception:
        # psutil may need elevated privileges to list connections.
        return None

    pids = sorted(
        {
            c.pid
            for c in connections
            if c.status == psutil.CONN_LISTEN
            and c.laddr.port == port
            and c.pid is not None
        }
    )
    if not pids:
        return None
    return pids[0]


def _bare_gpu_uuid(value: str) -> str:
    """A GPU UUID without nvidia-smi's ``GPU-`` prefix, lower-cased.

    nvidia-smi prints ``GPU-<uuid>``; torch's ``device_properties.uuid``
    prints the bare uuid in some versions and the prefixed form in others.
    """
    value = value.strip().lower()
    return value[4:] if value.startswith("gpu-") else value


def _nvidia_smi_usage(
    pids: set[int], torch_module: Any
) -> dict[str, int] | None:
    """Return GPU memory usage per ``cuda:i`` for ``pids``, or ``None`` if unknown.

    Maps nvidia-smi GPU UUIDs to torch CUDA device indices, so identical GPU
    names are disambiguated and the returned domain matches the torch device.
    """
    if not pids:
        return {}

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory,gpu_uuid",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        # nvidia-smi is absent, slow, or unsupported on this host.
        return None

    if proc.returncode != 0:
        return None

    per_uuid: dict[str, int] = {}
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            line_pid = int(parts[0])
        except ValueError:
            continue
        if line_pid not in pids:
            continue
        try:
            used_mib = int(parts[1])
        except ValueError:
            # One of our processes is on a GPU but its usage is not reported
            # (for example "[N/A]"): the total would be an under-estimate.
            return None
        gpu_uuid = parts[2]
        per_uuid[gpu_uuid] = per_uuid.get(gpu_uuid, 0) + used_mib * (1 << 20)

    if not per_uuid:
        return {}

    try:
        device_count = torch_module.cuda.device_count()
    except Exception:
        return None

    uuid_to_index: dict[str, int] = {}
    for i in range(device_count):
        try:
            props = torch_module.cuda.get_device_properties(i)
            uuid_to_index[_bare_gpu_uuid(str(props.uuid))] = i
        except Exception:
            continue

    result: dict[str, int] = {}
    for gpu_uuid, bytes_ in per_uuid.items():
        index = uuid_to_index.get(_bare_gpu_uuid(gpu_uuid))
        if index is None:
            # Unknown UUID: we cannot map this usage to a torch device.
            return None
        result[f"cuda:{index}"] = result.get(f"cuda:{index}", 0) + bytes_

    return result


def _service_gpu_memory(
    url: str,
    budgets: tuple[Any, ...] | list[Any],
    torch_module: Any | None = None,
) -> tuple[str | None, int | None] | None:
    """Return (device, bytes) for a local service's listener, if measurable.

    On a host with a ``cuda:N`` budget, returns ``None`` whenever the
    service's GPU memory cannot be read (no listener, unreadable process
    tree, no torch, nvidia-smi unavailable or unmappable), so the component
    is not recorded and stays uncalibrated. ``(None, None)`` means it uses no
    GPU, or the host has no device budget.
    """
    has_cuda_domain = any(
        hasattr(b, "name") and b.name.startswith("cuda:") for b in budgets
    )
    if not has_cuda_domain:
        # CPU-only or unified-memory host: there is no device budget to fill.
        return None, None

    # From here on the host has a device budget, so anything that stops us
    # reading the service's GPU memory makes it unknown (None), never "none".
    root_pid = _listener_root_pid(url)
    if root_pid is None:
        return None
    try:
        root = psutil.Process(root_pid)
        descendants = {child.pid for child in root.children(recursive=True)}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    pids = descendants | {root_pid}

    torch = torch_module
    if torch is None:
        try:
            import torch  # type: ignore[import]
        except Exception:
            # Without torch the GPUs cannot be mapped to budget domains.
            return None
    if not torch.cuda.is_available():
        return None

    usage = _nvidia_smi_usage(pids, torch)
    if usage is None:
        return None
    if not usage:
        return None, None
    device, bytes_ = max(usage.items(), key=lambda item: item[1])
    return device, bytes_


def _measure_service(url: str) -> int | None:
    """Inspect a listening process for an external service footprint.

    The figure is the peak resident memory of the listening process tree.
    Returns None when no listener is visible; raises ServiceNotMeasurable
    when the listener is a container port forwarder, an unknown process,
    or when several unrelated processes share the port.
    """
    parsed = urllib.parse.urlparse(url)
    port = parsed.port
    if port is None:
        return None

    try:
        connections = psutil.net_connections(kind="inet")
    except Exception:
        # psutil may need elevated privileges to list connections.
        return None

    pids = sorted(
        {
            c.pid
            for c in connections
            if c.status == psutil.CONN_LISTEN
            and c.laddr.port == port
            and c.pid is not None
        }
    )
    if not pids:
        return None

    root_pid = pids[0]
    try:
        root = psutil.Process(root_pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

    try:
        descendants = {child.pid for child in root.children(recursive=True)}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = set()
    descendants.add(root_pid)

    for pid in pids:
        if pid not in descendants:
            raise ServiceNotMeasurable(
                f"several unrelated processes listen on port {port}; "
                "the service cannot be measured unambiguously"
            )

    try:
        name = root.name()
    except psutil.NoSuchProcess:
        return None  # the service exited after the port scan
    if name in _PORT_PROXIES:
        raise ServiceNotMeasurable(
            "the service runs behind a container port forwarder; measure it from inside the container"
        )
    if name not in _SERVICE_PROCESSES:
        raise ServiceNotMeasurable(
            f"the listener on port {port} is {name!r}, not a known model server; measure the service directly"
        )

    try:
        total = _process_peak_bytes(root)
        children = root.children(recursive=True)
    except psutil.NoSuchProcess:
        return None  # the service exited after the port scan
    except psutil.AccessDenied as exc:
        raise ServiceNotMeasurable(
            f"the service's process tree could not be read ({exc})"
        ) from None
    for child in children:
        try:
            total += _process_peak_bytes(child)
        except psutil.NoSuchProcess:
            # An exited child no longer holds memory.
            continue
    return total


def _needs_for(
    entries: list[Entry],
    components: list[ComponentInfo],
    host: str,
    budgets: tuple[Any, ...] | list[Any],
) -> list[Need]:
    """Build fit-report needs from catalogue entries that match this rung.

    Components that run on a remote endpoint (``reason == "remote_endpoint"``)
    are skipped because the fit report does not plan for them. Every other
    enabled component is represented; those without a matching entry are emitted
    as uncalibrated so the fit report cannot falsely claim a clean fit.
    """
    interactive_components = {"lingua", "audition.stt", "vox.tts"}
    budget_domains = {b.name for b in budgets}
    needs: list[Need] = []
    for info in components:
        rung = f"{info.backend}:{info.model_id}"

        if info.reason == "remote_endpoint":
            continue

        matches = [
            e
            for e in entries
            if e.component == info.name
            and e.backend == info.backend
            and e.model_id == info.model_id
            and e.host_class == host
        ]

        if not matches:
            needs.append(
                Need(
                    component=info.name,
                    domain="system",
                    footprint_bytes=None,
                    interactive=info.name in interactive_components,
                    rung=rung,
                )
            )
            continue

        max_entry = max(matches, key=lambda e: e.bytes)
        system_need = Need(
            component=info.name,
            domain="system",
            footprint_bytes=max_entry.bytes,
            interactive=info.name in interactive_components,
            rung=rung,
        )
        needs.append(system_need)

        device_matches = [e for e in matches if e.device_bytes is not None]
        if device_matches:
            max_device = max(device_matches, key=lambda e: e.device_bytes)
            if max_device.device in budget_domains:
                needs.append(
                    Need(
                        component=info.name,
                        domain=max_device.device,
                        footprint_bytes=max_device.device_bytes,
                        interactive=info.name in interactive_components,
                        rung=rung,
                    )
                )
            else:
                # Unified-memory hosts have no cuda:N budget domain; fold the
                # device footprint into the system need.
                if (
                    system_need.footprint_bytes is not None
                    and max_device.device_bytes is not None
                ):
                    folded = Need(
                        component=info.name,
                        domain="system",
                        footprint_bytes=system_need.footprint_bytes
                        + max_device.device_bytes,
                        interactive=system_need.interactive,
                        rung=system_need.rung,
                    )
                    needs[-1] = folded
    return needs


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    config_loader: Callable[[], dict[str, Any]] | None = None,
    budgets_fn: Callable[[], tuple[Any, ...]] | None = None,
    measure_fn: Callable[
        [ComponentInfo, dict[str, Any], float],
        tuple[bool, int | None, int | None, str | None, bool, str],
    ]
    | None = None,
    service_fn: Callable[[str], int | None] | None = None,
    torch_module: Any | None = None,
    out: Callable[..., None] = print,
    err: Callable[..., None] | None = None,
    stdin_isatty: bool | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.footprint",
        description="Calibrate per-component memory footprints for KAINE.",
    )
    parser.add_argument("--yes", action="store_true", help="skip confirmation")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="only measure this component (can be given multiple times)",
    )
    parser.add_argument(
        "--catalogue",
        default=None,
        help="catalogue file to update (default: under the data root)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_finite_float,
        default=600.0,
        help="per-component measurement timeout in seconds",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="path to the runtime config",
    )
    parser.add_argument(
        "--operator-config",
        default=None,
        help="path to the operator config",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="module-selection profile to calibrate (default: as the cycle resolves it)",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if err is None:
        err = functools.partial(print, file=sys.stderr)

    if measure_fn is None:
        measure_fn = _measure_component
    if service_fn is None:
        service_fn = _measure_service
    if budgets_fn is None:
        budgets_fn = current_budgets

    try:
        if config_loader is None:
            load_kwargs: dict[str, Any] = {}
            if args.config is not None:
                load_kwargs["path"] = args.config
            if args.operator_config is not None:
                load_kwargs["operator_path"] = args.operator_config
            if args.profile is not None:
                load_kwargs["profile"] = args.profile
            config = load_runtime_config(**load_kwargs)
        else:
            config = config_loader()
    except Exception as exc:
        err(f"error: failed to load config: {exc}")
        return 2

    install_data_root(config)

    only_set = set(args.only) if args.only else None
    components = _select_components(config, only=only_set)
    if not components:
        out("no components selected for calibration")
        return 0

    for info in components:
        label = f"{info.backend}:{info.model_id}" if info.model_id else info.backend
        if info.kind == "in_process":
            out(f"{info.name} ({label}): will be LOADED")
        elif info.kind == "external":
            out(f"{info.name} ({label}): will be INSPECTED at {info.url}")
        elif info.kind == "absent":
            out(f"{info.name} ({label}): absent: run {info.fetch_command} to fetch")
        else:
            out(f"{info.name} ({label}): {info.message}")

    to_measure = [c for c in components if c.kind in ("in_process", "external")]
    if to_measure:
        if not args.yes:
            is_tty = sys.stdin.isatty() if stdin_isatty is None else stdin_isatty
            if not is_tty:
                err("refusing to load models without consent; re-run with --yes")
                return 2
            answer = input_fn(
                f"Load and measure {len(to_measure)} component(s)? [y/N] "
            )
            if answer.lower() not in ("y", "yes"):
                out("nothing was loaded")
                return 0

    try:
        host = host_class(torch_module=torch_module)
    except HostClassUnknown as exc:
        err(
            f"cannot calibrate: the accelerator's memory class is unknown ({exc}); nothing was recorded"
        )
        return 1

    try:
        budgets = budgets_fn()
    except Exception as exc:
        err(f"error: failed to probe budgets: {exc}")
        return 2

    catalogue_path = args.catalogue

    entries = load_catalogue(catalogue_path)
    existing = _catalogue_file(catalogue_path)
    if existing.is_file() and existing.stat().st_size > 0:
        corrupt = False
        try:
            raw = json.loads(existing.read_text(encoding="utf-8"))
            corrupt = not isinstance(raw, list)
        except (OSError, UnicodeDecodeError, ValueError):
            # Any read/parse failure means the file cannot be trusted.
            corrupt = True
        if corrupt:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
            backup = existing.with_name(f"{existing.name}.bak-{stamp}")
            try:
                existing.rename(backup)
                err(
                    f"warning: the existing footprint catalogue at {existing} "
                    f"could not be read; it was moved to {backup} and will be replaced"
                )
            except OSError as move_exc:
                err(
                    f"error: the existing footprint catalogue at {existing} "
                    f"could not be read and could not be moved aside ({move_exc}); "
                    f"nothing was recorded"
                )
                return 1

    measured_entries: list[Entry] = []
    had_failure = False

    for info in components:
        if info.kind == "not_measured":
            continue

        if info.kind == "absent":
            continue

        if info.kind == "external":
            if not _is_loopback_url(info.url):
                # Remote endpoints are never measured locally.
                out(f"{info.name}: not measured: {info.url} is not a loopback endpoint")
                continue

            try:
                peak_bytes = service_fn(info.url)
            except ServiceNotMeasurable as exc:
                out(f"{info.name}: not measured: {exc}")
                continue
            if peak_bytes is None:
                out(
                    f"{info.name}: not measured: {info.url} is not running or not visible to this user; start it and rerun"
                )
                continue

            device = None
            device_bytes = None
            gpu_result = _service_gpu_memory(info.url, budgets, torch_module)
            if gpu_result is None:
                out(
                    f"{info.name}: not measured: its GPU memory could not be read; "
                    f"it stays uncalibrated"
                )
                continue
            device, device_bytes = gpu_result

            entry = Entry(
                component=info.name,
                backend=info.backend,
                model_id=info.model_id,
                bytes=peak_bytes,
                device=device,
                device_bytes=device_bytes,
                mapped=False,
                host_class=host,
            )
            measured_entries.append(entry)
            out(f"{info.name}: {_fmt_mib(peak_bytes)} MiB (external)")
            if device_bytes:
                out(f"{info.name}: device {device} {_fmt_mib(device_bytes)} MiB")
            continue

        # in_process
        ok, peak_bytes, device_bytes, device, mapped, error = measure_fn(
            info, config, args.timeout
        )
        if not ok:
            out(f"{info.name}: FAILED: {error}")
            had_failure = True
            continue
        if peak_bytes is None:
            out(f"{info.name}: FAILED: no measurement returned")
            had_failure = True
            continue

        entry = Entry(
            component=info.name,
            backend=info.backend,
            model_id=info.model_id,
            bytes=peak_bytes,
            device=device,
            device_bytes=device_bytes,
            mapped=mapped,
            host_class=host,
        )
        measured_entries.append(entry)
        out(f"{info.name}: {_fmt_mib(peak_bytes)} MiB")
        if error:
            out(f"{info.name}: note: {error}")

    if measured_entries:
        for entry in measured_entries:
            entries = upsert(entries, entry)
        try:
            write_catalogue(entries, catalogue_path)
        except Exception as exc:
            err(
                f"error: cannot write the footprint catalogue: {type(exc).__name__}: {exc}; nothing was recorded"
            )
            return 1

    needs = _needs_for(entries, components, host, budgets)

    try:
        report = fit_report(budgets, needs, pin="lingua")
        for line in report.lines():
            out(line)
    except Exception as exc:
        err(f"error: failed to render fit report: {exc}")
        return 2

    if had_failure:
        return 1

    if report.uncalibrated:
        uncalibrated_list = ", ".join(report.uncalibrated)
        err(
            f"error: result is partial; uncalibrated components: {uncalibrated_list}"
        )
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
