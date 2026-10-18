# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Maternal voice layer for the KAINE audition module.

The fetal auditory environment is dominated by the maternal heartbeat and
intrauterine noise.  The maternal voice is audible above this background, but
its high frequencies are heavily attenuated by the maternal tissues and fluids
(Querleu et al. 1988; Gerhardt and Abrams 2000; Richards et al. 1992).
Newborns prefer a passage their mother read aloud before birth (DeCasper and
Spence 1986), so the repertoire contains a repeated passage alongside short
phrases.

Speech is paced by the mother's arousal and the unlocked portion of the
repertoire grows with awake time, like the developmental colour ramp, following
the progress niches of Oudeyer, Kaplan and Hafner (2007).

No speech is synthesized at runtime.  Only the files listed in the shipped
manifest are read; nothing is written.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from kaine.config import require_known_keys
from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.perception_prng import keyed_u64, unit_float
from kaine.modules.stimulus_source_signal import (
    _LOWPASS_TAPS,
    StimulusSourceParams,
    _lowpass_taps,
    maternal_state,
)

__all__ = [
    "MANIFEST_FORMAT",
    "MaternalVoiceLayer",
    "MaternalVoiceParams",
    "MaternalVoiceRepertoire",
    "SEED_SALT_VOICE",
    "Utterance",
    "VOICE_DATA_DIR",
    "unlocked_count",
]

VOICE_DATA_DIR = Path(__file__).with_name("maternal_voice_data")
SEED_SALT_VOICE = 0xF380
MANIFEST_FORMAT = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_flac_mono_int16(
    path: Path, expected_rate: int, expected_frames: int, av_mod: Any
) -> np.ndarray:
    try:
        with av_mod.open(str(path)) as container:
            if not container.streams.audio:
                raise PerceptionUnavailableError(
                    f"maternal voice take has no audio stream: {path}"
                )
            stream = container.streams.audio[0]
            rate = stream.codec_context.sample_rate
            channels = stream.codec_context.channels
            if rate != expected_rate:
                raise PerceptionUnavailableError(
                    f"maternal voice take sample rate mismatch in {path}: "
                    f"got {rate}, expected {expected_rate}"
                )
            if channels != 1:
                raise PerceptionUnavailableError(
                    f"maternal voice take must be mono: {path} has {channels} channels"
                )

            chunks: list[np.ndarray] = []
            total = 0
            for frame in container.decode(stream):
                name = frame.format.name
                if name not in ("s16", "s16p"):
                    raise PerceptionUnavailableError(
                        f"maternal voice take must be 16-bit int in {path}: {name}"
                    )
                arr = frame.to_ndarray()
                if arr.ndim == 2:
                    if arr.shape[0] == 1:
                        samples = arr.ravel()
                    else:
                        samples = arr[0]
                else:
                    samples = arr.ravel()
                chunks.append(samples)
                total += samples.size

            if total != expected_frames:
                raise PerceptionUnavailableError(
                    f"maternal voice take frame count mismatch in {path}: "
                    f"got {total}, expected {expected_frames}"
                )
            return np.concatenate(chunks).astype(np.int16, copy=False)
    except PerceptionUnavailableError:
        raise
    except Exception as exc:
        raise PerceptionUnavailableError(
            f"maternal voice take decode failed: {path}"
        ) from exc


@dataclass(frozen=True)
class MaternalVoiceParams:
    enabled: bool = True
    level_db: float = 6.0
    jitter_db: float = 3.0
    slot_seconds: float = 30.0
    episode_probability: float = 0.2
    repeat_share: float = 0.25
    unlock_seconds: float = 3600.0
    pause_min_seconds: float = 0.5
    pause_max_seconds: float = 1.5

    @staticmethod
    def _check_float(value: Any, key: str, lo: float, hi: float) -> float:
        if isinstance(value, bool):
            raise ValueError(
                f"[perception_feed.stimulus_source.voice] {key} must be a number, not bool"
            )
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"[perception_feed.stimulus_source.voice] {key} must be a number"
            )
        f = float(value)
        if not math.isfinite(f):
            raise ValueError(
                f"[perception_feed.stimulus_source.voice] {key} must be finite"
            )
        if f < lo or f > hi:
            raise ValueError(
                f"[perception_feed.stimulus_source.voice] {key} must be in [{lo}, {hi}]"
            )
        return f

    @classmethod
    def from_section(cls, section: dict | None) -> MaternalVoiceParams:
        if section is None:
            section = {}
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        require_known_keys(
            section, field_names, "[perception_feed.stimulus_source.voice]"
        )

        kwargs: dict[str, Any] = {}

        if "enabled" in section:
            val = section["enabled"]
            if not isinstance(val, bool):
                raise ValueError(
                    "[perception_feed.stimulus_source.voice] enabled must be a bool"
                )
            kwargs["enabled"] = val
        else:
            kwargs["enabled"] = cls.enabled

        simple_ranges = [
            ("level_db", -20.0, 20.0),
            ("jitter_db", 0.0, 6.0),
            ("slot_seconds", 5.0, 300.0),
            ("episode_probability", 0.0, 1.0),
            ("repeat_share", 0.0, 1.0),
        ]
        for name, lo, hi in simple_ranges:
            if name in section:
                kwargs[name] = cls._check_float(section[name], name, lo, hi)
            else:
                kwargs[name] = getattr(cls, name)

        if "unlock_seconds" in section:
            kwargs["unlock_seconds"] = cls._check_float(
                section["unlock_seconds"], "unlock_seconds", 0.0, math.inf
            )
            if kwargs["unlock_seconds"] <= 0.0:
                raise ValueError(
                    "[perception_feed.stimulus_source.voice] unlock_seconds must be in (0, inf)"
                )
        else:
            kwargs["unlock_seconds"] = cls.unlock_seconds

        if "pause_min_seconds" in section:
            kwargs["pause_min_seconds"] = cls._check_float(
                section["pause_min_seconds"], "pause_min_seconds", 0.0, 10.0
            )
        else:
            kwargs["pause_min_seconds"] = cls.pause_min_seconds

        if "pause_max_seconds" in section:
            kwargs["pause_max_seconds"] = cls._check_float(
                section["pause_max_seconds"],
                "pause_max_seconds",
                kwargs["pause_min_seconds"],
                10.0,
            )
        else:
            kwargs["pause_max_seconds"] = cls.pause_max_seconds
            if kwargs["pause_max_seconds"] < kwargs["pause_min_seconds"]:
                raise ValueError(
                    "[perception_feed.stimulus_source.voice] pause_max_seconds must be in [pause_min_seconds, 10]"
                )

        return cls(**kwargs)

    def as_record(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "level_db": self.level_db,
            "jitter_db": self.jitter_db,
            "slot_seconds": self.slot_seconds,
            "episode_probability": self.episode_probability,
            "repeat_share": self.repeat_share,
            "unlock_seconds": self.unlock_seconds,
            "pause_min_seconds": self.pause_min_seconds,
            "pause_max_seconds": self.pause_max_seconds,
        }


def unlocked_count(
    awake_seconds: float, initial: int, total: int, unlock_seconds: float
) -> int:
    if not math.isfinite(awake_seconds) or awake_seconds < 0.0:
        awake_seconds = 0.0
    base = min(total, initial + int(math.floor(awake_seconds / unlock_seconds)))
    return max(base, min(initial, total))


@dataclass(frozen=True)
class Utterance:
    start: int
    item: int
    take: int
    gain: float


class MaternalVoiceRepertoire:
    def __init__(
        self,
        takes: tuple[tuple[np.ndarray, ...], ...],
        item_ids: tuple[str, ...],
        initial_unlocked: int,
        sample_rate: int,
        manifest_sha256: str,
    ) -> None:
        if not takes:
            raise ValueError("MaternalVoiceRepertoire: takes must not be empty")
        if len(takes) != len(item_ids):
            raise ValueError(
                "MaternalVoiceRepertoire: item_ids length must match takes length"
            )
        for i, item_takes in enumerate(takes):
            if not item_takes:
                raise ValueError(
                    f"MaternalVoiceRepertoire: item {i} has no takes"
                )
            for j, take in enumerate(item_takes):
                if take.ndim != 1 or take.size == 0:
                    raise ValueError(
                        f"MaternalVoiceRepertoire: take {j} of item {i} "
                        "must be a non-empty 1-D array"
                    )
        if not (1 <= initial_unlocked <= len(takes)):
            raise ValueError(
                "MaternalVoiceRepertoire: initial_unlocked must be between 1 and the number of items"
            )

        self._takes = tuple(
            tuple(np.asarray(t, dtype=np.float64) for t in item) for item in takes
        )
        self._item_ids = tuple(item_ids)
        self._initial_unlocked = int(initial_unlocked)
        self._sample_rate = int(sample_rate)
        self._manifest_sha256 = manifest_sha256

        peak = 0.0
        for item in self._takes:
            for take in item:
                m = float(np.max(np.abs(take)))
                if m > peak:
                    peak = m
        self._peak = peak

    @property
    def takes(self) -> tuple[tuple[np.ndarray, ...], ...]:
        return self._takes

    @property
    def item_ids(self) -> tuple[str, ...]:
        return self._item_ids

    @property
    def initial_unlocked(self) -> int:
        return self._initial_unlocked

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def peak(self) -> float:
        return self._peak

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256

    @classmethod
    def load(
        cls,
        directory: str | Path | None = None,
        *,
        sample_rate: int = 16000,
        lowpass_hz: float = 500.0,
    ) -> MaternalVoiceRepertoire:
        if directory is None:
            directory = VOICE_DATA_DIR
        directory = Path(directory)
        manifest_path = directory / "manifest.json"

        try:
            raw = manifest_path.read_bytes()
            manifest = json.loads(raw.decode("utf-8"))
        except FileNotFoundError as exc:
            raise PerceptionUnavailableError(
                f"maternal voice manifest not found: {manifest_path}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise PerceptionUnavailableError(
                f"maternal voice manifest unreadable or invalid JSON: {manifest_path}"
            ) from exc

        if manifest.get("format") != MANIFEST_FORMAT:
            raise PerceptionUnavailableError(
                f"maternal voice manifest format must be {MANIFEST_FORMAT}: {manifest_path}"
            )
        items = manifest.get("items")
        if not isinstance(items, list) or len(items) == 0:
            raise PerceptionUnavailableError(
                f"maternal voice manifest has no items: {manifest_path}"
            )
        initial_unlocked = manifest.get("initial_unlocked")
        if not isinstance(initial_unlocked, int) or isinstance(initial_unlocked, bool):
            raise PerceptionUnavailableError(
                f"maternal voice manifest initial_unlocked must be an int: {manifest_path}"
            )

        file_rate = manifest.get("sample_rate")
        if not isinstance(file_rate, int) or isinstance(file_rate, bool):
            raise ValueError(
                f"maternal voice manifest sample_rate must be an int: {manifest_path}"
            )
        if file_rate * 2 != sample_rate:
            raise ValueError(
                f"maternal voice file sample rate {file_rate} is not compatible "
                f"with stream sample rate {sample_rate}"
            )
        if not (0.0 < lowpass_hz < file_rate / 2.0):
            raise ValueError(
                f"lowpass_hz {lowpass_hz} must satisfy 0 < lowpass_hz < file_rate/2 "
                f"({file_rate / 2.0})"
            )

        try:
            import av
        except ImportError as exc:
            raise PerceptionUnavailableError(
                "PyAV (av) not installed; the maternal voice needs it to decode its FLAC repertoire; "
                "install with: pip install -e .[audio]"
            ) from exc

        h = 2.0 * _lowpass_taps(lowpass_hz / sample_rate, _LOWPASS_TAPS)
        loaded_takes: list[tuple[np.ndarray, ...]] = []
        item_ids: list[str] = []

        for item in items:
            item_id = item.get("id")
            item_ids.append(item_id)
            take_entries = item.get("takes", [])
            item_arrays: list[np.ndarray] = []
            for take in take_entries:
                file_name = take.get("file")
                take_path = directory / file_name
                expected_hash = take.get("sha256")
                expected_frames = take.get("frames")

                if not take_path.is_file():
                    raise PerceptionUnavailableError(
                        f"maternal voice take missing: {take_path}"
                    )
                digest = _sha256_file(take_path)
                if digest != expected_hash:
                    raise PerceptionUnavailableError(
                        f"maternal voice take sha256 mismatch: {take_path}"
                    )

                try:
                    x = _decode_flac_mono_int16(
                        take_path, file_rate, expected_frames, av
                    )
                except PerceptionUnavailableError:
                    raise
                except Exception as exc:
                    raise PerceptionUnavailableError(
                        f"maternal voice take decode failed: {take_path}"
                    ) from exc

                n = x.size
                y = np.zeros(2 * n, dtype=np.float64)
                y[0::2] = x / 32768.0
                z = np.convolve(y, h, mode="full")
                rms = float(np.sqrt(np.mean(z * z)))
                if rms == 0.0:
                    raise PerceptionUnavailableError(
                        f"maternal voice take has zero RMS: {take_path}"
                    )
                z = z / rms
                item_arrays.append(z.astype(np.float64, copy=False))
            loaded_takes.append(tuple(item_arrays))

        return cls(
            tuple(loaded_takes),
            tuple(item_ids),
            initial_unlocked,
            sample_rate,
            _sha256_bytes(raw),
        )


class MaternalVoiceLayer:
    def __init__(
        self,
        repertoire: MaternalVoiceRepertoire,
        params: MaternalVoiceParams,
        *,
        seed: int,
        stimulus_params: StimulusSourceParams,
        background_rms: float,
    ) -> None:
        if not isinstance(params, MaternalVoiceParams):
            raise TypeError("params must be a MaternalVoiceParams instance")
        if not math.isfinite(background_rms) or background_rms <= 0.0:
            raise ValueError("background_rms must be finite and positive")

        self._repertoire = repertoire
        self._params = params
        self._seed = int(seed)
        self._stimulus_params = stimulus_params
        self._target = float(background_rms * (10.0 ** (params.level_db / 20.0)))
        self._peak = float(
            repertoire.peak
            * self._target
            * (10.0 ** (params.jitter_db / 20.0))
        )
        self._slot_n = int(round(params.slot_seconds * repertoire.sample_rate))
        if self._slot_n <= 0:
            raise ValueError("slot_seconds is too small for the repertoire sample rate")
        self._cache: dict[int, tuple[Utterance, ...]] = {}

    @property
    def params(self) -> MaternalVoiceParams:
        return self._params

    @property
    def repertoire(self) -> MaternalVoiceRepertoire:
        return self._repertoire

    @property
    def peak(self) -> float:
        return self._peak

    @property
    def target_rms(self) -> float:
        return self._target

    def slot_plan(self, slot: int, unlocked: int) -> tuple[Utterance, ...]:
        sr = self._repertoire.sample_rate
        t0 = slot * self._slot_n
        end = t0 + self._slot_n
        s = self._seed
        S = SEED_SALT_VOICE
        params = self._params
        stimulus_params = self._stimulus_params

        arousal = maternal_state(s, t0 / sr, stimulus_params)[1]
        if not (
            unit_float(keyed_u64(s, slot, S | 1))
            < params.episode_probability * arousal
        ):
            return ()

        n_un = max(1, min(unlocked, len(self._repertoire.takes)))
        start = t0 + int(unit_float(keyed_u64(s, slot, S | 2)) * 2.0 * sr)

        utterances: list[Utterance] = []
        for k in range(64):
            idx = slot * 64 + k
            if k == 0 and unit_float(keyed_u64(s, idx, S | 3)) < params.repeat_share:
                item = 0
            else:
                item = min(
                    n_un - 1, int(unit_float(keyed_u64(s, idx, S | 4)) * n_un)
                )

            takes = self._repertoire.takes[item]
            take = min(
                len(takes) - 1,
                int(unit_float(keyed_u64(s, idx, S | 5)) * len(takes)),
            )
            arr = takes[take]
            length = arr.shape[0]
            if start + length > end:
                break

            gain = 10.0 ** (
                (2.0 * unit_float(keyed_u64(s, idx, S | 6)) - 1.0)
                * params.jitter_db
                / 20.0
            )
            utterances.append(
                Utterance(int(start), int(item), int(take), float(gain))
            )

            pause = params.pause_min_seconds + (
                params.pause_max_seconds - params.pause_min_seconds
            ) * unit_float(keyed_u64(s, idx, S | 7))
            start += length + int(round(pause * sr))

        return tuple(utterances)

    def plan_for(self, slot: int, awake_seconds: float) -> tuple[Utterance, ...]:
        if slot in self._cache:
            return self._cache[slot]

        unlocked = unlocked_count(
            awake_seconds,
            self._repertoire.initial_unlocked,
            len(self._repertoire.takes),
            self._params.unlock_seconds,
        )
        plan = self.slot_plan(slot, unlocked)
        self._cache[slot] = plan

        for old in list(self._cache.keys()):
            if old < slot - 2:
                del self._cache[old]

        return plan

    def render(self, start: int, n: int, awake_seconds: float) -> np.ndarray:
        if n <= 0:
            return np.empty(0, dtype=np.float64)

        slot_n = self._slot_n
        start_slot = start // slot_n
        end_slot = (start + n - 1) // slot_n
        out = np.zeros(n, dtype=np.float64)
        target = self._target

        for slot in range(start_slot, end_slot + 1):
            for utt in self.plan_for(slot, awake_seconds):
                arr = self._repertoire.takes[utt.item][utt.take]
                utt_end = utt.start + arr.shape[0]
                clip_lo = max(start, utt.start)
                clip_hi = min(start + n, utt_end)
                if clip_lo < clip_hi:
                    src_lo = clip_lo - utt.start
                    src_hi = clip_hi - utt.start
                    dst_lo = clip_lo - start
                    dst_hi = clip_hi - start
                    out[dst_lo:dst_hi] += utt.gain * target * arr[src_lo:src_hi]

        return out
