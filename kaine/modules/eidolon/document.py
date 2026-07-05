# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""SelfModel document for Eidolon.

A frozen JSON-serializable dataclass that describes who KAINE is.
Every field starts empty — Eidolon discovers identity through
observation; it prescribes nothing.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

# First name shared by this lineage of entities; the surname individuates each
# launch. The entity may rename itself later — this is only the starting point.
DEFAULT_FIRST_NAME = "Kaine"

# A tribute to Second Life's "last name" lineage: the surnames residents chose
# from a Linden-Lab dropdown (2003–2010, revived 2020) before everyone became
# "Resident". The full released set lives in `surnames.txt` (from the official
# SL wiki last-name list), minus the "Resident" placeholder — synthetic
# residents inheriting a name from the residents who came before.
def _load_surnames() -> tuple[str, ...]:
    try:
        text = (Path(__file__).parent / "surnames.txt").read_text(encoding="utf-8")
        names = tuple(n.strip() for n in text.splitlines() if n.strip())
        if names:
            return names
    except Exception:
        pass
    # Defensive fallback so naming never fails if the data file is missing.
    return ("Voxel", "Atheria", "Nova", "Aurora", "Argonaut", "Arcane")


_SURNAMES = _load_surnames()


def generate_launch_name(*, rng: random.Random | None = None) -> str:
    """``Kaine <Surname>`` with a surname picked at launch. Injectable RNG for
    deterministic tests."""
    r = rng or random
    return f"{DEFAULT_FIRST_NAME} {r.choice(_SURNAMES)}"


@dataclass(frozen=True)
class SelfModel:
    # The entity's name. Empty until assigned. A first name + a surname chosen
    # at first launch (see generate_launch_name); the long-term intent is that
    # an entity renames ITSELF once it has a sense of identity, at which point
    # this is overwritten from its own expressed preference.
    name: str = ""
    values: list[str] = field(default_factory=list)
    behavioral_norms: list[str] = field(default_factory=list)
    capability_map: dict[str, Any] = field(default_factory=dict)
    personality_baseline: dict[str, float] = field(default_factory=dict)
    identity_history: list[dict[str, Any]] = field(default_factory=list)
    internal_speech_count: int = 0
    external_speech_count: int = 0
    voice_observations: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "SelfModel":
        data = json.loads(text)
        return cls(
            name=str(data.get("name", "")),
            values=list(data.get("values", [])),
            behavioral_norms=list(data.get("behavioral_norms", [])),
            capability_map=dict(data.get("capability_map", {})),
            personality_baseline={
                str(k): float(v)
                for k, v in (data.get("personality_baseline") or {}).items()
            },
            identity_history=list(data.get("identity_history", [])),
            internal_speech_count=int(data.get("internal_speech_count", 0)),
            external_speech_count=int(data.get("external_speech_count", 0)),
            voice_observations=list(data.get("voice_observations", [])),
        )

    def with_updates(self, **changes: Any) -> "SelfModel":
        """Return a new SelfModel with the given fields replaced."""
        return replace(self, **changes)


def load(path: Path) -> SelfModel:
    """Load a SelfModel from a JSON path. Missing file → empty model.

    The on-disk bytes are passed through the active StateEncryptor's
    `maybe_decrypt`, so an encrypted self-model is transparently decrypted and
    a plaintext (or pre-encryption) file is read unchanged.
    """
    from kaine.security.crypto import get_state_encryptor

    if not path.exists():
        return SelfModel()
    raw = path.read_bytes()
    if not raw.strip():
        return SelfModel()
    text = get_state_encryptor().maybe_decrypt(raw).decode("utf-8")
    if not text.strip():
        return SelfModel()
    return SelfModel.from_json(text)


def save_atomic(path: Path, model: SelfModel) -> None:
    """Write `model` to `path` atomically.

    Writes to a sibling `*.tmp` and `os.replace`s into place so a crash
    mid-save cannot corrupt the destination file. When state encryption is
    enabled the payload is AES-256-GCM encrypted before it touches disk.
    """
    from kaine.security.crypto import get_state_encryptor

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = get_state_encryptor().encrypt_text(model.to_json())
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
