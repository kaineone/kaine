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
import functools
import io
import math
import multiprocessing
import os
import resource
import sys
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

_GiB = 1 << 30
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
            components.append(
                ComponentInfo(
                    name="lingua",
                    kind="external",
                    backend=backend or "openai",
                    model_id=model_id,
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
                        backend="speaches",
                        model_id="medium.en",
                        url=audition.get("speaches_url", "http://127.0.0.1:8000"),
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
            components.append(
                ComponentInfo(
                    name="vox.tts",
                    kind="external",
                    backend="chatterbox",
                    model_id="chatterbox",
                    url=vox.get("chatterbox_url", "http://127.0.0.1:8883"),
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


def _child_wrapper(conn: Any, target_fn: Callable[[], dict[str, Any]]) -> None:
    _set_offline_env()
    try:
        baseline = _read_baseline_bytes()
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
        mapped = bool(result.get("mapped", False)) if isinstance(result, dict) else False

        if "torch" in sys.modules:
            import torch  # type: ignore[import]

            if torch.cuda.is_available():
                reserved = int(torch.cuda.max_memory_reserved())
                if reserved > 0:
                    device = f"cuda:{torch.cuda.current_device()}"
                    device_bytes = reserved

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
            pass


def _measure_callable_in_child(
    target_fn: Callable[[], dict[str, Any]],
    timeout: float = 600.0,
) -> tuple[bool, int | None, int | None, str | None, bool, str]:
    """Run a callable in a spawned child and return its memory footprint."""
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child_wrapper, args=(child_conn, target_fn))
    process.start()

    try:
        if parent_conn.poll(timeout):
            data = parent_conn.recv()
            process.join(timeout=30)
            note = ""
            if process.is_alive():
                # The child reported and then failed to exit: stop it, but the
                # measurement it sent stands. Say so, so it is never mistaken
                # for a crash.
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                note = "the child was stopped after reporting; the measurement stands"

            if not data.get("ok"):
                return (False, None, None, None, False, data.get("error", "failed"))
            return (
                True,
                data.get("peak_bytes"),
                data.get("device_bytes"),
                data.get("device"),
                data.get("mapped", False),
                note,
            )

        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            return (False, None, None, None, False, "timed out")

        return (False, None, None, None, False, f"child exited with code {process.exitcode}")
    finally:
        parent_conn.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)


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

    name = root.name()
    if name in _PORT_PROXIES:
        raise ServiceNotMeasurable(
            "the service runs behind a container port forwarder; measure it from inside the container"
        )
    if name not in _SERVICE_PROCESSES:
        raise ServiceNotMeasurable(
            f"the listener on port {port} is {name!r}, not a known model server; measure the service directly"
        )

    total = _process_peak_bytes(root)
    for child in root.children(recursive=True):
        try:
            total += _process_peak_bytes(child)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def _needs_for(
    entries: list[Entry],
    components: list[ComponentInfo],
    host: str,
) -> list[Need]:
    """Build fit-report needs from catalogue entries that match this rung."""
    interactive_components = {"lingua", "audition.stt", "vox.tts"}
    needs: list[Need] = []
    for info in components:
        if info.kind not in ("in_process", "external"):
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
            continue
        max_entry = max(matches, key=lambda e: e.bytes)
        rung = f"{info.backend}:{info.model_id}"
        needs.append(
            Need(
                component=info.name,
                domain="system",
                footprint_bytes=max_entry.bytes,
                interactive=info.name in interactive_components,
                rung=rung,
            )
        )
        device_matches = [e for e in matches if e.device_bytes is not None]
        if device_matches:
            max_device = max(device_matches, key=lambda e: e.device_bytes)
            needs.append(
                Need(
                    component=info.name,
                    domain=max_device.device,
                    footprint_bytes=max_device.device_bytes,
                    interactive=info.name in interactive_components,
                    rung=rung,
                )
            )
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
        type=float,
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

    if args.catalogue is None:
        install_data_root(config)
        catalogue_path = None
    else:
        catalogue_path = args.catalogue

    # load_catalogue never raises: an unreadable file reads as empty. Say so
    # before it is replaced, so earlier measurements are not lost silently.
    entries = load_catalogue(catalogue_path)
    existing = _catalogue_file(catalogue_path)
    if not entries and existing.is_file() and existing.stat().st_size > 0:
        err(
            f"warning: the existing footprint catalogue at {existing} could not be "
            "read; it will be replaced by this run's measurements"
        )

    measured_entries: list[Entry] = []
    had_failure = False

    for info in components:
        if info.kind == "not_measured":
            continue

        if info.kind == "absent":
            continue

        if info.kind == "external":
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
            entry = Entry(
                component=info.name,
                backend=info.backend,
                model_id=info.model_id,
                bytes=peak_bytes,
                device=None,
                device_bytes=None,
                mapped=False,
                host_class=host,
            )
            measured_entries.append(entry)
            out(f"{info.name}: {_fmt_mib(peak_bytes)} MiB (external)")
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

    needs = _needs_for(entries, components, host)

    try:
        report = fit_report(budgets, needs, pin="lingua")
        for line in report.lines():
            out(line)
    except Exception as exc:
        err(f"error: failed to render fit report: {exc}")
        return 2

    return 1 if had_failure else 0


if __name__ == "__main__":
    sys.exit(main())
