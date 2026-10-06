# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Status vocabulary + individual dependency probe implementations.

Each ``probe_*``/``nous_health_probe`` coroutine answers one question — is
this external dependency reachable and correctly configured? — and returns
``(status, detail)``. They are pure I/O: no state, no caching (caching lives
in :class:`~kaine.nexus.health.prober.HealthProber`).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Status vocabulary (kept as plain strings to match the JSON contract).
UP = "up"
DOWN = "down"
DEGRADED = "degraded"
NOT_CONFIGURED = "not_configured"

DEFAULT_PROBE_TIMEOUT_S = 2.0
DEFAULT_CACHE_TTL_S = 5.0

SHERPA_PROBE_RETRY_S = 60.0
SHERPA_PROBE_WAIT_S = 1.5
SHERPA_PROBE_CHILD_TIMEOUT_S = 300.0

_SHERPA_PROBE_MEMO: dict[tuple, tuple[str, str, float, tuple]] = {}
_SHERPA_INFLIGHT: dict[tuple, concurrent.futures.Future] = {}
_SHERPA_PROBE_LOCK = threading.Lock()
_SHERPA_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="sherpa-probe"
)


def set_sherpa_probe_wait(seconds: float) -> None:
    """Set how long callers wait before a slow load is reported DEGRADED."""
    global SHERPA_PROBE_WAIT_S
    SHERPA_PROBE_WAIT_S = seconds


def get_sherpa_probe_wait() -> float:
    """Return the current slow-load wait threshold."""
    return SHERPA_PROBE_WAIT_S


def clear_sherpa_probe_memo() -> None:
    """Reset the sherpa probe memo and single-flight map. For tests."""
    with _SHERPA_PROBE_LOCK:
        _SHERPA_PROBE_MEMO.clear()
        _SHERPA_INFLIGHT.clear()


_CHILD_SCRIPT = r'''
import asyncio
import io
import json
import sys
import wave


async def _main():
    args = json.loads(sys.argv[1])
    kind = args["kind"]
    client = None
    try:
        if kind == "stt":
            from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT
            from kaine.model_paths import DEFAULT_STT

            client = SherpaMoonshineSTT(
                args["model_dir"],
                model_id=args.get("model_id"),
                num_threads=args.get("num_threads", 1),
            )
            warm_up = getattr(client, "warm_up", None)
            if warm_up is not None:
                await warm_up()

            n_samples = int(16000 * 0.5)
            pcm = b"\x00\x00" * n_samples
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm)
            audio = buf.getvalue()

            await client.transcribe(
                audio,
                sample_rate=16000,
                model=args.get("model_id"),
                filename="silence.wav",
            )
            detail = (
                f"{args.get('model_id') or DEFAULT_STT} "
                "loaded and transcribed a test clip"
            )
        else:
            from kaine.modules.vox.client import TTSRequest
            from kaine.modules.vox.sherpa_tts import SherpaKokoroTTS
            from kaine.model_paths import DEFAULT_TTS

            client = SherpaKokoroTTS(
                args["model_dir"],
                model_id=args.get("model_id"),
                speaker_id=args.get("speaker_id", 0),
                num_threads=args.get("num_threads", 1),
            )
            warm_up = getattr(client, "warm_up", None)
            if warm_up is not None:
                await warm_up()

            req = TTSRequest(text="ok")
            result = await client.synthesize(req)
            if not getattr(result, "audio", b""):
                raise RuntimeError("synthesized audio was empty")
            detail = (
                f"{args.get('model_id') or DEFAULT_TTS} "
                "loaded and synthesized a test word"
            )

        print(json.dumps({"status": "up", "detail": detail}))
    except Exception as exc:
        print(json.dumps({"status": "down", "detail": f"{type(exc).__name__}: {exc}"}))
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


asyncio.run(_main())
'''


def _run_probe_child(kind: str, args: dict[str, Any]) -> tuple[str, str]:
    """Run the sherpa load/inference in an isolated child process.

    Factored out so unit tests can replace the subprocess boundary with a
    synchronous fake.
    """
    child_args = dict(args)
    child_args["kind"] = kind
    argv = [sys.executable, "-c", _CHILD_SCRIPT, json.dumps(child_args)]
    env = os.environ.copy()

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=SHERPA_PROBE_CHILD_TIMEOUT_S,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return DOWN, f"model load exceeded {SHERPA_PROBE_CHILD_TIMEOUT_S} s; killed"

    last_stderr = "no stderr"
    if proc.stderr and proc.stderr.strip():
        last_stderr = proc.stderr.strip().splitlines()[-1]

    if proc.returncode != 0:
        return DOWN, f"probe process exited with status {proc.returncode}: {last_stderr}"

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return DOWN, f"probe process exited with status {proc.returncode}: {last_stderr}"

    try:
        result = json.loads(lines[-1])
        return result["status"], result["detail"]
    except Exception:
        return DOWN, f"probe process exited with status {proc.returncode}: {last_stderr}"


def _model_fingerprint(model_dir: str, model_id: str | None) -> tuple:
    """Return a stable fingerprint of the files that matter for ``model_dir``.

    For known model ids this is the manifest's required files (using a
    directory's own stat for directory entries such as ``espeak-ng-data``) plus
    the ``.verified`` marker. Unknown ids fall back to the top-level files of
    the directory only, with no recursion.
    """
    base = Path(model_dir)
    try:
        if not base.exists():
            return ("missing", str(model_dir))

        entries: list[tuple[str, int, int]] = []
        seen: set[str] = set()

        verified = base / ".verified"
        if verified.exists():
            try:
                st = verified.stat()
                entries.append((".verified", st.st_size, st.st_mtime_ns))
            except OSError:
                entries.append((".verified", 0, 0))
            seen.add(".verified")

        from kaine import speech_manifest

        required_files: list[str] | None = None
        manifest = speech_manifest.MANIFEST.get(model_id)
        if manifest is not None:
            required_files = list(manifest.required_files)

        if required_files is not None:
            for rel in required_files:
                if rel in seen:
                    continue
                p = base / rel
                if not p.exists():
                    continue
                try:
                    st = p.stat()
                    entries.append((rel, st.st_size, st.st_mtime_ns))
                except OSError:
                    entries.append((rel, 0, 0))
                seen.add(rel)
        else:
            for p in base.iterdir():
                if not p.is_file():
                    continue
                rel = p.name
                if rel in seen:
                    continue
                try:
                    st = p.stat()
                    entries.append((rel, st.st_size, st.st_mtime_ns))
                except OSError:
                    entries.append((rel, 0, 0))
                seen.add(rel)

        entries.sort(key=lambda item: item[0])
        return tuple(entries)
    except Exception as exc:
        return ("error", type(exc).__name__, str(exc))


def _sherpa_worker(
    key: tuple,
    model_dir: str,
    model_id: str | None,
    runner: Callable[[], tuple[str, str]],
) -> tuple[str, str]:
    """Run the synchronous load/inference, then record the memo entry.

    Success and failure are both handled inside the worker; the awaiting
    coroutine only waits on the shared future.
    """
    fingerprint = _model_fingerprint(model_dir, model_id)
    try:
        status, detail = runner()
    except Exception as exc:
        status, detail = DOWN, f"{type(exc).__name__}: {exc}"
    with _SHERPA_PROBE_LOCK:
        _SHERPA_PROBE_MEMO[key] = (status, detail, time.monotonic(), fingerprint)
        _SHERPA_INFLIGHT.pop(key, None)
    return status, detail


def _cleanup_inflight(key: tuple, fut: concurrent.futures.Future) -> None:
    """Make sure the in-flight map is cleaned up once the future settles."""
    with _SHERPA_PROBE_LOCK:
        _SHERPA_INFLIGHT.pop(key, None)


async def _cached_sherpa_probe(
    key: tuple,
    model_dir: str,
    model_id: str | None,
    runner: Callable[[], tuple[str, str]],
) -> tuple[str, str]:
    """Return a cached UP result if the files are unchanged, retry DOWN
    after ``SHERPA_PROBE_RETRY_S``, and ensure at most one load per key is
    actually running.

    A load that takes longer than ``SHERPA_PROBE_WAIT_S`` returns DEGRADED
    but keeps running in the background so it can be reused by later callers.
    """
    now = time.monotonic()
    fingerprint = await asyncio.to_thread(_model_fingerprint, model_dir, model_id)

    with _SHERPA_PROBE_LOCK:
        cached = _SHERPA_PROBE_MEMO.get(key)
        if cached is not None:
            status, detail, verified_at, stored_fp = cached
            if stored_fp == fingerprint:
                age = now - verified_at
                if status == UP:
                    return UP, f"{detail} (verified {int(age)} s ago)"
                if age < SHERPA_PROBE_RETRY_S:
                    retry_in = int(SHERPA_PROBE_RETRY_S - age)
                    return DOWN, f"{detail} (retry in {retry_in} s)"
            # Fingerprint changed or retry window expired: drop the stale entry.
            _SHERPA_PROBE_MEMO.pop(key, None)

        fut = _SHERPA_INFLIGHT.get(key)
        if fut is None:
            fut = _SHERPA_EXECUTOR.submit(
                _sherpa_worker, key, model_dir, model_id, runner
            )
            _SHERPA_INFLIGHT[key] = fut
            fut.add_done_callback(lambda f: _cleanup_inflight(key, f))

    # Wait on the in-flight load without letting the prober's timeout cancel it.
    wrapped = asyncio.wrap_future(fut)
    shielded = asyncio.shield(wrapped)
    try:
        status, detail = await asyncio.wait_for(shielded, timeout=SHERPA_PROBE_WAIT_S)
    except asyncio.TimeoutError:
        return DEGRADED, "sherpa-onnx model load in progress"
    return status, detail


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def probe_redis(*, host: str, port: int, password: str | None) -> tuple[str, str]:
    try:
        import redis.asyncio as aioredis
    except Exception:
        return DEGRADED, "redis client not importable"
    client = aioredis.Redis(
        host=host,
        port=port,
        password=password or None,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
    )
    try:
        pong = await client.ping()
        if pong:
            return UP, f"PING ok ({host}:{port})"
        return DOWN, "PING returned falsy"
    finally:
        try:
            await client.aclose()
        except Exception:
            try:
                await client.close()
            except Exception:
                pass


async def probe_qdrant(*, host: str, port: int, api_key: str | None) -> tuple[str, str]:
    url = f"http://{host}:{port}/readyz"
    headers = {"api-key": api_key} if api_key else {}
    async with httpx.AsyncClient(timeout=1.8, trust_env=False) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 200:
        return UP, f"/readyz ok ({host}:{port})"
    return DEGRADED, f"/readyz returned HTTP {resp.status_code}"


async def probe_chat_llm(
    *, base_url: str, model_id: str | None, api_key: str | None = None
) -> tuple[str, str]:
    # Tolerate chat_url given as the server root or with a trailing /v1 (the
    # OpenAI-compat surface) — strip then hit the /v1/models listing either way.
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    url = base + "/v1/models"
    # A keyed server (Unsloth Studio) needs bearer auth or the probe 401s and
    # falsely reports degraded; keyless servers ignore the header.
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    async with httpx.AsyncClient(timeout=1.8, headers=headers, trust_env=False) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return DEGRADED, f"/v1/models returned HTTP {resp.status_code}"
        try:
            data = resp.json()
            served = [m.get("id") for m in (data.get("data") or [])]
        except Exception:
            return DEGRADED, "could not parse /v1/models response"
        if model_id and model_id not in served:
            return (
                DEGRADED,
                f"reachable but model '{model_id}' not served ({len(served)} models present)",
            )
        detail = f"model '{model_id}' served" if model_id else f"{len(served)} models served"
        try:
            props = await client.get(base + "/props")
            if props.status_code == 200:
                body = props.json()
                if isinstance(body, dict) and body.get("is_sleeping") is True:
                    return UP, detail + " (asleep; loads on the next request)"
        except (httpx.HTTPError, ValueError):
            log.debug("organ /props unavailable; sleep state unknown", exc_info=True)
        return UP, detail


async def probe_speaches(*, base_url: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/v1/models"
    async with httpx.AsyncClient(timeout=1.8, trust_env=False) as client:
        resp = await client.get(url)
    if resp.status_code == 200:
        return UP, "/v1/models ok"
    return DEGRADED, f"/v1/models returned HTTP {resp.status_code}"


async def probe_chatterbox(*, base_url: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/"
    async with httpx.AsyncClient(timeout=1.8, trust_env=False) as client:
        resp = await client.get(url)
    # Chatterbox's root may answer 200 or a redirect / 404 while still
    # being a live listener; any HTTP response means the port is serving.
    if resp.status_code < 500:
        return UP, f"responding (HTTP {resp.status_code})"
    return DEGRADED, f"HTTP {resp.status_code}"


async def probe_sherpa_stt(
    *,
    model_dir: str,
    model_id: str | None,
    num_threads: int,
) -> tuple[str, str]:
    """Probe the local sherpa-onnx Moonshine STT backend with a silent clip."""

    def _run() -> tuple[str, str]:
        args = {
            "model_dir": model_dir,
            "model_id": model_id,
            "num_threads": num_threads,
        }
        return _run_probe_child("stt", args)

    key = ("stt", model_dir, model_id, None, num_threads)
    return await _cached_sherpa_probe(key, model_dir, model_id, _run)


async def probe_sherpa_tts(
    *,
    model_dir: str,
    model_id: str | None,
    speaker_id: int,
    num_threads: int,
) -> tuple[str, str]:
    """Probe the local sherpa-onnx Kokoro TTS backend by saying a short word."""

    def _run() -> tuple[str, str]:
        args = {
            "model_dir": model_dir,
            "model_id": model_id,
            "speaker_id": speaker_id,
            "num_threads": num_threads,
        }
        return _run_probe_child("tts", args)

    key = ("tts", model_dir, model_id, speaker_id, num_threads)
    return await _cached_sherpa_probe(key, model_dir, model_id, _run)


async def probe_state_encryption(
    *, section: dict[str, Any]
) -> tuple[str, str]:
    """Probe the state-encryption posture from [security.state_encryption].

    Three outcomes:
    - disabled → plaintext (not an error; the shipped default)
    - enabled + key resolvable → at-rest: encrypted
    - enabled + no key → fail-closed (operator action required)

    The key is NEVER read or logged; only its presence is checked.
    """
    enabled = bool(section.get("enabled", False))
    if not enabled:
        return UP, "at-rest: plaintext (encryption disabled)"

    key_env_var = str(section.get("key_env_var", "KAINE_STATE_KEY"))

    def _check_key() -> tuple[str, str]:
        import os

        # Check env var without reading the value into any log.
        if os.environ.get(key_env_var):
            return UP, "at-rest: encrypted (key resolvable via env var)"

        # Check kernel keyring without reading the value.
        try:
            import keyutils  # type: ignore

            kid = keyutils.request_key(
                "kaine:state_key", keyutils.KEY_SPEC_USER_KEYRING
            )
            if kid is not None:
                return UP, "at-rest: encrypted (key resolvable via keyring)"
        except Exception:
            # keyutils is optional and the keyring lookup is best-effort; any
            # failure (module absent, no key, keyring unavailable) must not crash
            # the probe. Fall through to the degraded/fail-closed return below.
            pass

        return (
            DEGRADED,
            f"encryption enabled but NO KEY found (set ${key_env_var} or load keyring); fail-closed",
        )

    return await asyncio.to_thread(_check_key)


async def nous_health_probe(*, backend: str = "pymdp") -> tuple[str, str]:
    """Probe Nous's active-inference backend (pymdp or NumPy).

    The ``backend`` keyword selects which implementation is checked:
    ``"pymdp"`` requires the ``reasoning`` extra (jax + inferactively-pymdp),
    while ``"numpy"`` builds the pure-NumPy engine and runs a single step.
    """

    def _check() -> tuple[str, str]:
        if backend == "numpy":
            try:
                from kaine.modules.nous.engine import encode_snapshot_default
                from kaine.modules.nous.generative_model import build_generative_model
                from kaine.modules.nous.numpy_engine import NumpyActiveInferenceEngine
                engine = NumpyActiveInferenceEngine(build_generative_model())
                engine.infer(encode_snapshot_default(engine.model))
                engine.close()
            except Exception as exc:
                return DOWN, f"nous numpy backend failed: {exc}"
            return UP, "nous numpy backend built and ran one step"

        if backend != "pymdp":
            return DEGRADED, f"nous backend {backend!r} is not recognised"

        try:
            import jax  # noqa: F401
            import pymdp  # noqa: F401
        except Exception as exc:  # ImportError or backend init failure
            return DOWN, f"pymdp/jax import failed: {exc}"
        try:
            devices = ", ".join(str(d) for d in jax.devices())
        except Exception:
            devices = "unknown"
        try:
            from kaine.modules.nous.generative_model import build_generative_model
            build_generative_model()
        except Exception as exc:
            return DEGRADED, (
                f"pymdp + jax importable (devices: {devices}) but "
                f"generative model build failed: {exc}"
            )
        return UP, f"pymdp + jax importable; generative model built (devices: {devices})"

    return await asyncio.to_thread(_check)
