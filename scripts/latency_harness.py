# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Residency latency harness: cold/warm loads, STT/TTS/organ timing, peak RSS.

Run:  .venv/bin/python scripts/latency_harness.py [--stt-rounds 5] [--output results.json]
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import io
import json
import logging
import resource
import statistics
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from kaine.model_paths import speech_model_dir
from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT
from kaine.modules.audition.stt_client import SpeachesClient
from kaine.modules.vocal.client import ChatterboxClient, TTSRequest
from kaine.modules.vocal.sherpa_tts import SherpaKokoroTTS
from kaine.residency.speech_rungs import (
    STT_LADDER,
    TTS_LADDER,
    is_rung_installed,
)

log = logging.getLogger(__name__)

MIB = 1 << 20


@dataclass
class LoadMeasurement:
    rung_label: str
    component: str
    cold_ms: float
    warm_ms: float


@dataclass
class STTMeasurement:
    rung_label: str
    segment_ms: float
    audio_duration_s: float
    realtime_factor: float


@dataclass
class TTSMeasurement:
    rung_label: str
    first_chunk_ms: float
    total_ms: float
    audio_duration_s: float
    realtime_factor: float


@dataclass
class OrganMeasurement:
    first_token_ms: float
    includes_swap_in: bool


@dataclass
class VoiceTurnMeasurement:
    stt_ms: float
    organ_ms: float
    tts_ms: float
    total_ms: float


@dataclass
class MemoryMeasurement:
    peak_rss_bytes: int
    peak_rss_mib: float


@dataclass
class HarnessResult:
    load_times: list[LoadMeasurement] = field(default_factory=list)
    stt: list[STTMeasurement] = field(default_factory=list)
    tts: list[TTSMeasurement] = field(default_factory=list)
    organ: list[OrganMeasurement] = field(default_factory=list)
    voice_turns: list[VoiceTurnMeasurement] = field(default_factory=list)
    memory: MemoryMeasurement | None = None


def _make_wav(duration_s: float = 2.0, sample_rate: int = 16000) -> bytes:
    n_samples = int(duration_s * sample_rate)
    samples = np.zeros(n_samples, dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def _wav_duration_s(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


async def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def measure_load_times(rounds: int = 3) -> list[LoadMeasurement]:
    results: list[LoadMeasurement] = []

    for ladder, component in [(STT_LADDER, "stt"), (TTS_LADDER, "tts")]:
        for rung in ladder:
            if rung.backend in ("speaches", "chatterbox"):
                continue
            if not is_rung_installed(rung):
                log.info("skipping %s (not installed)", rung.label)
                continue

            try:
                model_dir = speech_model_dir(rung.model_id)
            except Exception as exc:
                log.warning("cannot locate %s: %s", rung.model_id, exc)
                continue

            cold_times: list[float] = []
            warm_times: list[float] = []

            try:
                for _ in range(rounds):
                    if component == "stt":
                        client: Any = SherpaMoonshineSTT(
                            model_dir, model_id=rung.model_id, _verify=False
                        )
                    else:
                        client = SherpaKokoroTTS(
                            model_dir, model_id=rung.model_id, _verify=False
                        )

                    t0 = time.monotonic()
                    await client.ensure_loaded()
                    cold_times.append((time.monotonic() - t0) * 1000)

                    t0 = time.monotonic()
                    await client.ensure_loaded()
                    warm_times.append((time.monotonic() - t0) * 1000)

                    await client.unload()
                    await client.aclose()
                    gc.collect()

                results.append(LoadMeasurement(
                    rung_label=rung.label,
                    component=component,
                    cold_ms=statistics.median(cold_times),
                    warm_ms=statistics.median(warm_times),
                ))
                log.info(
                    "load %s [%s]: cold=%.1fms warm=%.3fms",
                    rung.label, component,
                    results[-1].cold_ms, results[-1].warm_ms,
                )
            except Exception as exc:
                log.warning("load measurement failed for %s: %s", rung.label, exc)

    return results


async def _bench_stt(label: str, transcribe_fn, audio: bytes, rounds: int) -> STTMeasurement | None:
    try:
        actual: list[float] = []
        for _ in range(rounds):
            t0 = time.monotonic()
            await transcribe_fn(audio)
            actual.append((time.monotonic() - t0) * 1000)
        med = statistics.median(actual)
        log.info("stt %s: %.1fms (rtf=%.3f)", label, med, med / 2000.0)
        return STTMeasurement(rung_label=label, segment_ms=med, audio_duration_s=2.0, realtime_factor=med / 2000.0)
    except Exception as exc:
        log.warning("stt measurement failed for %s: %s", label, exc)
        return None


async def measure_stt(rounds: int = 5) -> list[STTMeasurement]:
    results: list[STTMeasurement] = []
    audio = _make_wav(2.0)

    for rung in STT_LADDER:
        if rung.backend == "sherpa_onnx" and is_rung_installed(rung):
            try:
                client = SherpaMoonshineSTT(speech_model_dir(rung.model_id), model_id=rung.model_id, _verify=False)
                await client.ensure_loaded()
                m = await _bench_stt(rung.label, lambda a: client.transcribe(a, sample_rate=16000, model=rung.model_id), audio, rounds)
                await client.aclose()
                if m:
                    results.append(m)
            except Exception as exc:
                log.warning("stt setup failed for %s: %s", rung.label, exc)

    if await _port_open("127.0.0.1", 8000):
        client_s = SpeachesClient()
        m = await _bench_stt("Speaches faster-whisper medium.en",
                             lambda a: client_s.transcribe(a, sample_rate=16000, model="faster-distil-whisper-medium.en"), audio, rounds)
        await client_s.aclose()
        if m:
            results.append(m)
    else:
        log.info("speaches not reachable on port 8000, skipping")
    return results


async def _bench_tts(label: str, synth_fn, rounds: int) -> TTSMeasurement | None:
    try:
        times: list[float] = []
        last_audio = b""
        for _ in range(rounds):
            t0 = time.monotonic()
            result = await synth_fn()
            times.append((time.monotonic() - t0) * 1000)
            last_audio = result.audio
        med = statistics.median(times)
        dur = _wav_duration_s(last_audio) if last_audio else 0.0
        rtf = (med / 1000.0) / dur if dur > 0 else 0.0
        log.info("tts %s: %.1fms audio=%.2fs rtf=%.3f", label, med, dur, rtf)
        return TTSMeasurement(rung_label=label, first_chunk_ms=med, total_ms=med, audio_duration_s=dur, realtime_factor=rtf)
    except Exception as exc:
        log.warning("tts measurement failed for %s: %s", label, exc)
        return None


async def measure_tts(rounds: int = 5) -> list[TTSMeasurement]:
    results: list[TTSMeasurement] = []
    text = "The quick brown fox jumps over the lazy dog."
    req = TTSRequest(text=text)

    for rung in TTS_LADDER:
        if rung.backend == "sherpa_onnx" and is_rung_installed(rung):
            try:
                client = SherpaKokoroTTS(speech_model_dir(rung.model_id), model_id=rung.model_id, _verify=False)
                await client.ensure_loaded()
                m = await _bench_tts(rung.label, lambda: client.synthesize(req), rounds)
                await client.aclose()
                if m:
                    results.append(m)
            except Exception as exc:
                log.warning("tts setup failed for %s: %s", rung.label, exc)

    if await _port_open("127.0.0.1", 8883):
        client_c = ChatterboxClient()
        m = await _bench_tts("Chatterbox (GPU service)", lambda: client_c.synthesize(req), rounds)
        await client_c.aclose()
        if m:
            results.append(m)
    else:
        log.info("chatterbox not reachable on port 8883, skipping")

    return results


_ORGAN_URL = "http://127.0.0.1:11435/v1/chat/completions"


async def _organ_stream(
    prompt: str, max_tokens: int = 32,
) -> tuple[float, str]:
    import httpx

    payload = {
        "model": "default",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max_tokens,
    }
    first_token_ms = 0.0
    text = ""
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        start = time.monotonic()
        async with client.stream(
            "POST", _ORGAN_URL, json=payload,
            headers={"Content-Type": "application/json"},
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                    continue
                if not first_token_ms and '"delta"' in line:
                    first_token_ms = (time.monotonic() - start) * 1000
                try:
                    delta = json.loads(line[6:]).get("choices", [{}])[0].get("delta", {})
                    text += delta.get("content", "")
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue  # SSE lines may be partial or non-JSON
    return first_token_ms, text


async def measure_organ(rounds: int = 3) -> list[OrganMeasurement]:
    if not await _port_open("127.0.0.1", 11435):
        log.info("organ not reachable on port 11435, skipping")
        return []
    try:
        import httpx  # noqa: F401
    except ImportError:
        log.warning("httpx not installed, cannot measure organ")
        return []

    results: list[OrganMeasurement] = []
    for i in range(rounds):
        try:
            ft_ms, _ = await _organ_stream("Say hello.")
            if ft_ms > 0:
                results.append(OrganMeasurement(first_token_ms=ft_ms, includes_swap_in=(i == 0)))
                log.info("organ round %d: first_token=%.1fms swap_in=%s", i, ft_ms, i == 0)
        except Exception as exc:
            log.warning("organ measurement round %d failed: %s", i, exc)
    return results


def _find_local_rung(ladder, backend="sherpa_onnx"):
    return next((r for r in ladder if r.backend == backend and is_rung_installed(r)), None)


async def measure_voice_turn() -> list[VoiceTurnMeasurement]:
    organ_ok = await _port_open("127.0.0.1", 11435)
    stt_rung = _find_local_rung(STT_LADDER)
    tts_rung = _find_local_rung(TTS_LADDER)

    if not (stt_rung and tts_rung and organ_ok):
        log.info("voice turn skipped (stt=%s tts=%s organ=%s)", bool(stt_rung), bool(tts_rung), organ_ok)
        return []
    try:
        import httpx  # noqa: F401
    except ImportError:
        log.warning("httpx not installed, cannot measure voice turn")
        return []

    audio = _make_wav(2.0)
    try:
        stt_client = SherpaMoonshineSTT(speech_model_dir(stt_rung.model_id), model_id=stt_rung.model_id, _verify=False)
        tts_client = SherpaKokoroTTS(speech_model_dir(tts_rung.model_id), model_id=tts_rung.model_id, _verify=False)
        await stt_client.ensure_loaded()
        await tts_client.ensure_loaded()

        t_total = time.monotonic()
        t0 = time.monotonic()
        transcript = await stt_client.transcribe(audio, sample_rate=16000, model=stt_rung.model_id)
        stt_ms = (time.monotonic() - t0) * 1000

        t0 = time.monotonic()
        _, organ_text = await _organ_stream(transcript.text or "Hello.", max_tokens=64)
        organ_ms = (time.monotonic() - t0) * 1000

        t0 = time.monotonic()
        await tts_client.synthesize(TTSRequest(text=organ_text.strip() or "Hello."))
        tts_ms = (time.monotonic() - t0) * 1000
        total_ms = (time.monotonic() - t_total) * 1000

        await stt_client.aclose()
        await tts_client.aclose()

        log.info("voice turn: stt=%.1f organ=%.1f tts=%.1f total=%.1fms", stt_ms, organ_ms, tts_ms, total_ms)
        return [VoiceTurnMeasurement(stt_ms=stt_ms, organ_ms=organ_ms, tts_ms=tts_ms, total_ms=total_ms)]
    except Exception as exc:
        log.warning("voice turn measurement failed: %s", exc)
        return []


def measure_memory() -> MemoryMeasurement:
    peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak_kib * 1024
    return MemoryMeasurement(
        peak_rss_bytes=peak_bytes,
        peak_rss_mib=peak_bytes / MIB,
    )


def _table(heading: str, cols: list[str], rows: list[list[str]]) -> str:
    sep = ["-" * max(3, len(c)) for c in cols]
    lines = [f"## {heading}\n", "| " + " | ".join(cols) + " |", "| " + " | ".join(sep) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def format_markdown(result: HarnessResult) -> str:
    parts: list[str] = []
    if result.load_times:
        parts.append(_table("Load Times", ["Component", "Rung", "Cold (ms)", "Warm (ms)"],
                            [[m.component, m.rung_label, f"{m.cold_ms:.1f}", f"{m.warm_ms:.3f}"] for m in result.load_times]))
    if result.stt:
        parts.append(_table("STT Latency", ["Rung", "Segment (ms)", "Audio (s)", "RTF"],
                            [[m.rung_label, f"{m.segment_ms:.1f}", f"{m.audio_duration_s:.1f}", f"{m.realtime_factor:.3f}"] for m in result.stt]))
    if result.tts:
        parts.append(_table("TTS Latency", ["Rung", "Total (ms)", "Audio (s)", "RTF"],
                            [[m.rung_label, f"{m.total_ms:.1f}", f"{m.audio_duration_s:.2f}", f"{m.realtime_factor:.3f}"] for m in result.tts]))
    if result.organ:
        parts.append(_table("Organ First Token", ["Round", "First Token (ms)", "Swap-in"],
                            [[str(i), f"{m.first_token_ms:.1f}", str(m.includes_swap_in)] for i, m in enumerate(result.organ)]))
    if result.voice_turns:
        parts.append(_table("End-to-End Voice Turn", ["STT (ms)", "Organ (ms)", "TTS (ms)", "Total (ms)"],
                            [[f"{m.stt_ms:.1f}", f"{m.organ_ms:.1f}", f"{m.tts_ms:.1f}", f"{m.total_ms:.1f}"] for m in result.voice_turns]))
    if result.memory:
        parts.append(f"## Peak Memory\n\n| Peak RSS | {result.memory.peak_rss_mib:.1f} MiB |\n")
    return "\n".join(parts)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Residency latency harness")
    parser.add_argument("--stt-rounds", type=int, default=5)
    parser.add_argument("--tts-rounds", type=int, default=5)
    parser.add_argument("--organ-rounds", type=int, default=3)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    result = HarnessResult()

    log.info("measuring load times...")
    result.load_times = await measure_load_times()

    log.info("measuring STT latency...")
    result.stt = await measure_stt(args.stt_rounds)

    log.info("measuring TTS latency...")
    result.tts = await measure_tts(args.tts_rounds)

    log.info("measuring organ first token...")
    result.organ = await measure_organ(args.organ_rounds)

    log.info("measuring end-to-end voice turn...")
    result.voice_turns = await measure_voice_turn()

    result.memory = measure_memory()
    log.info("peak RSS: %.1f MiB", result.memory.peak_rss_mib)

    payload = json.dumps(asdict(result), indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        log.info("JSON written to %s", args.output)
    else:
        sys.stdout.write(payload + "\n")

    sys.stderr.write("\n" + format_markdown(result) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
