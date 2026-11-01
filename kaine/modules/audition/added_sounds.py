# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Added sounds of the developmental stimulus: a recurring melody and an outside voice.

Both are provided elements of the external environment, like the soundscape and
the maternal voice (paper §7, A.7). They are cited here, at the code site:

- The recurring melody. A melody heard repeatedly in late pregnancy leaves a
  neural trace lasting months: newborns and four-month-olds whose mothers played
  "Twinkle, Twinkle, Little Star" in the last trimester responded more strongly
  to its unchanged notes (Partanen, Kujala, Tervaniemi and Huotilainen 2013,
  PLoS ONE 8(10): e78946). The shipped rendering is that tune in G major, its
  fundamentals 392 to 659 Hz, inside the stage-0 hearing band, played at the
  maternal voice's level above the soundscape with a seeded level variation.
- The outside voice. Voices outside the mother reach the fetus attenuated but
  with their intonation (Querleu, Renard, Versyp, Paris-Delrue and Crepin 1988).
  A synthetic male voice at the soundscape's RMS level; its fundamental, about
  100 to 130 Hz, lies below stage 1's lower edge, so it is heard from the
  100 Hz step.

Each slot of the maternal voice's grid (``slot_seconds``) holds at most one sound.
A slot in which the maternal voice speaks holds no added sound; otherwise a keyed
draw on ``(seed, slot)`` below ``melody_probability`` holds the melody, else one
below ``outside_voice_probability`` holds one outside-voice utterance. The draws,
the take, the level and the placement are functions of the seed and the slot
only: nothing the entity does or feels changes them. Each sound ramps in and out
over 0.5 s and passes the same intrauterine low-pass as the maternal voice; the
stream mixes it before the hearing band.

No sound is synthesized at runtime. Only the files listed in the shipped manifest
are read, each checked against its sha256; nothing is written.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from kaine.config import require_known_keys
from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.audition.maternal_voice import _decode_flac_mono_int16
from kaine.modules.perception_prng import keyed_u64, unit_float
from kaine.modules.stimulus_source_signal import _LOWPASS_TAPS, _lowpass_taps

if TYPE_CHECKING:
    from kaine.modules.audition.maternal_voice import MaternalVoiceLayer, MaternalVoiceParams

__all__ = [
    "ADDED_SOUNDS_DATA_DIR",
    "AddedSound",
    "AddedSoundsLayer",
    "AddedSoundsParams",
    "AddedSoundsRepertoire",
    "MANIFEST_FORMAT",
    "RAMP_SECONDS",
    "SEED_SALT_ADDED",
]

ADDED_SOUNDS_DATA_DIR = Path(__file__).with_name("added_sounds_data")
SEED_SALT_ADDED = 0xA7D0
MANIFEST_FORMAT = 1
RAMP_SECONDS = 0.5

_TABLE = "[perception_feed.stimulus_source.added_sounds]"


@dataclass(frozen=True)
class AddedSoundsParams:
    """``[perception_feed.stimulus_source.added_sounds]``.

    Attributes:
        enabled: Whether the melody and the outside voice play.
        melody_probability: ``p_m``, the chance a slot without maternal speech
            holds the melody (Table A1, provisional).
        outside_voice_probability: ``p_x``, the chance a slot without maternal
            speech or melody holds an outside-voice utterance (Table A1, provisional).
    """

    enabled: bool = True
    melody_probability: float = 0.02
    outside_voice_probability: float = 0.05

    @classmethod
    def from_section(cls, section: dict | None) -> "AddedSoundsParams":
        if section is None:
            section = {}
        if not isinstance(section, dict):
            raise ValueError(f"{_TABLE} must be a table")
        require_known_keys(
            section, {"enabled", "melody_probability", "outside_voice_probability"}, _TABLE
        )
        enabled = section.get("enabled", cls.enabled)
        if not isinstance(enabled, bool):
            raise ValueError(f"{_TABLE} enabled must be a bool, got {type(enabled).__name__}")
        kwargs: dict[str, Any] = {"enabled": enabled}
        for key in ("melody_probability", "outside_voice_probability"):
            value = section.get(key, getattr(cls, key))
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{_TABLE} {key} must be a number in [0, 1]")
            value = float(value)
            if not math.isfinite(value) or not (0.0 <= value <= 1.0):
                raise ValueError(f"{_TABLE} {key} must be a number in [0, 1], got {value}")
            kwargs[key] = value
        return cls(**kwargs)

    def as_record(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "melody_probability": self.melody_probability,
            "outside_voice_probability": self.outside_voice_probability,
        }


def _ramp(n: int, sample_rate: int) -> np.ndarray:
    """A raised-cosine fade in and out over ``RAMP_SECONDS`` (shorter for a short sound)."""
    r = min(n // 2, int(round(RAMP_SECONDS * sample_rate)))
    env = np.ones(n, dtype=np.float64)
    if r > 0:
        w = 0.5 - 0.5 * np.cos(math.pi * np.arange(r, dtype=np.float64) / r)
        env[:r] = w
        env[n - r:] = w[::-1]
    return env


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AddedSoundsRepertoire:
    """The verified, upsampled and low-passed melody takes and outside-voice takes."""

    def __init__(
        self,
        melody: tuple[np.ndarray, ...],
        outside: tuple[tuple[np.ndarray, ...], ...],
        outside_ids: tuple[str, ...],
        sample_rate: int,
        manifest_sha256: str,
    ) -> None:
        if not melody:
            raise ValueError("AddedSoundsRepertoire: no melody takes")
        if not outside or any(not takes for takes in outside):
            raise ValueError("AddedSoundsRepertoire: every outside-voice item needs a take")
        if len(outside) != len(outside_ids):
            raise ValueError("AddedSoundsRepertoire: outside_ids must match the items")
        for arr in list(melody) + [t for takes in outside for t in takes]:
            if arr.ndim != 1 or arr.size == 0:
                raise ValueError("AddedSoundsRepertoire: takes must be non-empty 1-D arrays")
        self._melody = tuple(np.asarray(m, dtype=np.float64) for m in melody)
        self._outside = tuple(tuple(np.asarray(t, dtype=np.float64) for t in takes) for takes in outside)
        self._outside_ids = tuple(outside_ids)
        self._sample_rate = int(sample_rate)
        self._manifest_sha256 = manifest_sha256

    @property
    def melody(self) -> tuple[np.ndarray, ...]:
        return self._melody

    @property
    def outside(self) -> tuple[tuple[np.ndarray, ...], ...]:
        return self._outside

    @property
    def outside_ids(self) -> tuple[str, ...]:
        return self._outside_ids

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256

    @property
    def longest(self) -> int:
        return max(a.shape[0] for a in list(self._melody) + [t for ts in self._outside for t in ts])

    @staticmethod
    def _load_take(
        directory: Path,
        entry: object,
        where: str,
        manifest_path: Path,
        file_rate: int,
        taps: np.ndarray,
        av_mod: Any,
        label: str,
    ) -> np.ndarray:
        if not isinstance(entry, dict):
            raise PerceptionUnavailableError(f"added sounds manifest {where} is not a dict: {manifest_path}")
        file_name = entry.get("file")
        if not isinstance(file_name, str) or not file_name:
            raise PerceptionUnavailableError(f"added sounds manifest {where} has no file: {manifest_path}")
        if Path(file_name).is_absolute() or file_name.startswith(("/", "\\")) or ".." in Path(file_name).parts or (
            len(file_name) >= 2 and file_name[1] == ":"
        ):
            raise PerceptionUnavailableError(
                f"added sounds manifest {where} file path must be relative and inside the directory: {manifest_path}"
            )
        expected_hash = entry.get("sha256")
        expected_frames = entry.get("frames")
        if not isinstance(expected_hash, str):
            raise PerceptionUnavailableError(f"added sounds manifest {where} sha256 must be a string: {manifest_path}")
        if isinstance(expected_frames, bool) or not isinstance(expected_frames, int):
            raise PerceptionUnavailableError(f"added sounds manifest {where} frames must be an int: {manifest_path}")
        path = directory / file_name
        if not path.is_file():
            raise PerceptionUnavailableError(f"{label} missing: {path}")
        if _sha256_file(path) != expected_hash:
            raise PerceptionUnavailableError(f"{label} sha256 mismatch: {path}")
        x = _decode_flac_mono_int16(path, file_rate, expected_frames, av_mod, label=label)
        y = np.zeros(2 * x.size, dtype=np.float64)
        y[0::2] = x / 32768.0
        z = np.convolve(y, taps, mode="full")
        rms = float(np.sqrt(np.mean(z * z)))
        if rms == 0.0:
            raise PerceptionUnavailableError(f"{label} has zero RMS: {path}")
        return z / rms

    @classmethod
    def load(
        cls,
        directory: str | Path | None = None,
        *,
        sample_rate: int = 16000,
        lowpass_hz: float = 500.0,
    ) -> "AddedSoundsRepertoire":
        """Verify and load every take the manifest lists.

        Each take is upsampled to ``sample_rate`` (twice the files' rate), passed
        through the intrauterine low-pass at ``lowpass_hz`` as the maternal voice is,
        and scaled to unit RMS. A missing manifest, a missing file or a digest
        mismatch raises ``PerceptionUnavailableError`` naming the file.
        """
        directory = Path(directory) if directory is not None else ADDED_SOUNDS_DATA_DIR
        manifest_path = directory / "manifest.json"
        try:
            raw = manifest_path.read_bytes()
            manifest = json.loads(raw.decode("utf-8"))
        except FileNotFoundError as exc:
            raise PerceptionUnavailableError(f"added sounds manifest not found: {manifest_path}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise PerceptionUnavailableError(f"added sounds manifest unreadable or invalid JSON: {manifest_path}") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
            raise PerceptionUnavailableError(f"added sounds manifest format must be {MANIFEST_FORMAT}: {manifest_path}")
        file_rate = manifest.get("sample_rate")
        if isinstance(file_rate, bool) or not isinstance(file_rate, int):
            raise PerceptionUnavailableError(f"added sounds manifest sample_rate must be an int: {manifest_path}")
        if file_rate * 2 != sample_rate:
            raise ValueError(
                f"added sounds file sample rate {file_rate} is not compatible with stream sample rate {sample_rate}"
            )
        if not (0.0 < lowpass_hz < file_rate / 2.0):
            raise ValueError(f"lowpass_hz {lowpass_hz} must satisfy 0 < lowpass_hz < {file_rate / 2.0}")
        melody_section = manifest.get("melody")
        outside_section = manifest.get("outside_voice")
        if not isinstance(melody_section, dict) or not isinstance(melody_section.get("takes"), list) or not melody_section["takes"]:
            raise PerceptionUnavailableError(f"added sounds manifest has no melody takes: {manifest_path}")
        if (
            not isinstance(outside_section, dict)
            or not isinstance(outside_section.get("items"), list)
            or not outside_section["items"]
        ):
            raise PerceptionUnavailableError(
                f"added sounds manifest has no outside-voice items (render them with "
                f"tools/maintainer/generate_outside_voice.py): {manifest_path}"
            )
        try:
            import av
        except ImportError as exc:
            raise PerceptionUnavailableError(
                "PyAV (av) not installed; the added sounds need it to decode their FLAC files; "
                "install with: pip install -e .[audio]"
            ) from exc

        taps = 2.0 * _lowpass_taps(lowpass_hz / sample_rate, _LOWPASS_TAPS)
        melody = tuple(
            cls._load_take(directory, e, f"melody take {i}", manifest_path, file_rate, taps, av, "melody take")
            for i, e in enumerate(melody_section["takes"])
        )
        outside: list[tuple[np.ndarray, ...]] = []
        ids: list[str] = []
        for i, item in enumerate(outside_section["items"]):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise PerceptionUnavailableError(f"added sounds manifest outside-voice item {i} has no id: {manifest_path}")
            takes = item.get("takes")
            if not isinstance(takes, list) or not takes:
                raise PerceptionUnavailableError(
                    f"added sounds manifest outside-voice item {item['id']} has no takes: {manifest_path}"
                )
            ids.append(item["id"])
            outside.append(
                tuple(
                    cls._load_take(
                        directory, e, f"outside-voice item {item['id']} take {j}", manifest_path,
                        file_rate, taps, av, "outside voice take",
                    )
                    for j, e in enumerate(takes)
                )
            )
        return cls(melody, tuple(outside), tuple(ids), sample_rate, hashlib.sha256(raw).hexdigest())


@dataclass(frozen=True)
class AddedSound:
    """One slot's added sound: ``kind`` is ``"melody"`` or ``"outside_voice"``."""

    kind: str
    start: int
    item: int
    take: int
    gain: float


class AddedSoundsLayer:
    """Renders the added sounds for any sample range; a pure function of the seed and slot."""

    def __init__(
        self,
        repertoire: AddedSoundsRepertoire,
        params: AddedSoundsParams,
        *,
        seed: int,
        voice_params: "MaternalVoiceParams",
        voice: "MaternalVoiceLayer | None",
        background_rms: float,
    ) -> None:
        if not isinstance(params, AddedSoundsParams):
            raise TypeError("params must be an AddedSoundsParams instance")
        if not math.isfinite(background_rms) or background_rms <= 0.0:
            raise ValueError("background_rms must be finite and positive")
        if voice is not None and voice.repertoire.sample_rate != repertoire.sample_rate:
            raise ValueError("the maternal voice and the added sounds must share a sample rate")
        self._repertoire = repertoire
        self._params = params
        self._seed = int(seed)
        self._voice = voice
        self._jitter_db = float(voice_params.jitter_db)
        sr = repertoire.sample_rate
        self._slot_n = int(round(voice_params.slot_seconds * sr))
        if repertoire.longest > self._slot_n:
            raise ValueError(
                f"an added-sound take ({repertoire.longest / sr:.1f} s) is longer than a slot "
                f"({voice_params.slot_seconds} s)"
            )
        # The melody plays at the maternal voice's level above the soundscape, the
        # outside voice at the soundscape's level (paper A.7).
        self._melody_target = float(background_rms * (10.0 ** (voice_params.level_db / 20.0)))
        self._outside_target = float(background_rms)
        self._melody = tuple(m * _ramp(m.shape[0], sr) for m in repertoire.melody)
        self._outside = tuple(tuple(t * _ramp(t.shape[0], sr) for t in takes) for takes in repertoire.outside)
        self._cache: dict[int, AddedSound | None] = {}
        self._cache_lock = threading.Lock()

    @property
    def params(self) -> AddedSoundsParams:
        return self._params

    @property
    def repertoire(self) -> AddedSoundsRepertoire:
        return self._repertoire

    @property
    def slot_samples(self) -> int:
        return self._slot_n

    @property
    def headroom(self) -> float:
        """The RMS level of the louder added sound, which the stream's headroom covers."""
        return max(self._melody_target, self._outside_target)

    def _u(self, slot: int, k: int) -> float:
        return unit_float(keyed_u64(self._seed, slot, SEED_SALT_ADDED | k))

    def slot_sound(self, slot: int) -> AddedSound | None:
        """The added sound slot ``slot`` holds, or None. Depends only on the seed and slot."""
        with self._cache_lock:
            if slot in self._cache:
                return self._cache[slot]
        sound = self._plan(slot)
        with self._cache_lock:
            self._cache[slot] = sound
            for old in [k for k in self._cache if k < slot - 2]:
                del self._cache[old]
        return sound

    def _plan(self, slot: int) -> AddedSound | None:
        if slot < 0:
            return None
        if self._voice is not None and self._voice.speaks_in(slot):
            return None
        p = self._params
        t0 = slot * self._slot_n
        if self._u(slot, 1) < p.melody_probability:
            n = len(self._melody)
            take = min(n - 1, int(self._u(slot, 2) * n))
            gain = 10.0 ** ((2.0 * self._u(slot, 3) - 1.0) * self._jitter_db / 20.0)
            room = self._slot_n - self._melody[take].shape[0]
            start = t0 + int(self._u(slot, 4) * (room + 1)) if room > 0 else t0
            return AddedSound("melody", int(start), 0, int(take), float(gain * self._melody_target))
        if self._u(slot, 5) < p.outside_voice_probability:
            n_items = len(self._outside)
            item = min(n_items - 1, int(self._u(slot, 6) * n_items))
            takes = self._outside[item]
            take = min(len(takes) - 1, int(self._u(slot, 7) * len(takes)))
            room = self._slot_n - takes[take].shape[0]
            start = t0 + int(self._u(slot, 8) * (room + 1)) if room > 0 else t0
            return AddedSound("outside_voice", int(start), int(item), int(take), float(self._outside_target))
        return None

    def _array(self, sound: AddedSound) -> np.ndarray:
        if sound.kind == "melody":
            return self._melody[sound.take]
        return self._outside[sound.item][sound.take]

    def render(self, start: int, n: int) -> np.ndarray:
        """The added sounds over samples ``[start, start + n)`` of the stream."""
        out = np.zeros(max(0, n), dtype=np.float64)
        if n <= 0:
            return out
        for slot in range(max(0, start // self._slot_n), (start + n - 1) // self._slot_n + 1):
            sound = self.slot_sound(slot)
            if sound is None:
                continue
            arr = self._array(sound)
            lo = max(start, sound.start)
            hi = min(start + n, sound.start + arr.shape[0])
            if lo < hi:
                out[lo - start:hi - start] += sound.gain * arr[lo - sound.start:hi - sound.start]
        return out
