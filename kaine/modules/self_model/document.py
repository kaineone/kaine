# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""SelfModelDocument document for the self-model module.

A frozen JSON-serializable dataclass that describes who KAINE is.
Every field starts empty — the self-model module discovers identity through
observation; it prescribes nothing.
"""
from __future__ import annotations

import json
import logging
import os
import random
import tempfile
import unicodedata
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

MAX_NAME_LENGTH = 64


def is_valid_name(name: object) -> bool:
    """A name is a non-blank single-line string of at most 64 characters, with no
    leading or trailing whitespace and no control, format (bidi), surrogate,
    private-use or unassigned character (any Unicode category starting with "C")."""
    return (
        isinstance(name, str)
        and 0 < len(name) <= MAX_NAME_LENGTH
        and name == name.strip()
        and all(not unicodedata.category(c).startswith("C") for c in name)
        and len(name.splitlines()) == 1
    )


# First name shared by this lineage of entities; the surname individuates each
# launch. The name is drawn once at first boot and kept for life.
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
    except (OSError, UnicodeDecodeError):
        # File missing, unreadable, or garbled — fall through to the
        # built-in defaults so naming never fails.
        pass
    # Defensive fallback so naming never fails if the data file is missing.
    return ("Voxel", "Atheria", "Nova", "Aurora", "Argonaut", "Arcane")


_SURNAMES = _load_surnames()


def generate_launch_name(
    *, rng: random.Random | None = None, exclude: "str | Iterable[str] | None" = None
) -> str:
    """``Kaine <Surname>`` with a surname picked at launch. Injectable RNG for
    deterministic tests. ``exclude`` is a full name to avoid (a fork's parent's
    name); when every surname would produce it, the name is returned anyway."""
    r = rng or random
    avoid = {exclude} if isinstance(exclude, str) else set(exclude or ())
    candidates = [
        n for n in (f"{DEFAULT_FIRST_NAME} {s}" for s in _SURNAMES) if n not in avoid
    ]
    if not candidates:
        return f"{DEFAULT_FIRST_NAME} {r.choice(_SURNAMES)}"
    return r.choice(candidates)


@dataclass(frozen=True)
class SelfModelDocument:
    # The entity's name. Empty until assigned. A first name + a surname drawn
    # once at first boot (see generate_launch_name) and kept for life. The
    # identity file (state/identity/entity.json) is the record of the name; this
    # field mirrors it.
    name: str = ""
    values: list[str] = field(default_factory=list)
    behavioral_norms: list[str] = field(default_factory=list)
    capability_map: dict[str, Any] = field(default_factory=dict)
    personality_baseline: dict[str, float] = field(default_factory=dict)
    identity_history: list[dict[str, Any]] = field(default_factory=list)
    internal_speech_count: int = 0
    external_speech_count: int = 0
    voice_observations: list[dict[str, Any]] = field(default_factory=list)
    # Facts about the entity's situation that it is told (not values or norms,
    # never part of the identity clause), e.g. that it is periodically assessed
    # for its own protection.
    situation_facts: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        """Serialize to compact JSON.

        Uses the C encoder (``indent=None``) over the fields as they are,
        without the recursive Python copy ``dataclasses.asdict`` makes, so a
        long-lived self-model saves quickly. Every field already holds plain
        JSON types. Files written earlier with ``indent=2`` load unchanged.
        """
        plain = {f.name: getattr(self, f.name) for f in fields(self)}
        return json.dumps(plain, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> "SelfModelDocument":
        data = json.loads(text)
        name = str(data.get("name", ""))
        if name and not is_valid_name(name):
            log.warning("self-model document holds an invalid name %r; treating it as no name", name)
            name = ""
        return cls(
            name=name,
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
            situation_facts=[str(x) for x in data.get("situation_facts", [])],
        )

    def with_updates(self, **changes: Any) -> "SelfModelDocument":
        """Return a new SelfModelDocument with the given fields replaced."""
        return replace(self, **changes)


def load(path: Path) -> SelfModelDocument:
    """Load a SelfModelDocument from a JSON path. Missing file → empty model.

    The on-disk bytes are passed through the active StateEncryptor's
    `maybe_decrypt`, so an encrypted self-model is transparently decrypted and
    a plaintext (or pre-encryption) file is read unchanged.
    """
    from kaine.security.crypto import get_state_encryptor

    if not path.exists():
        return SelfModelDocument()
    raw = path.read_bytes()
    if not raw.strip():
        return SelfModelDocument()
    text = get_state_encryptor().maybe_decrypt(raw).decode("utf-8")
    if not text.strip():
        return SelfModelDocument()
    return SelfModelDocument.from_json(text)


def save_atomic(path: Path, model: SelfModelDocument) -> None:
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
            # Best-effort tmp cleanup — fdopen may have failed before the
            # file was created, so it may simply not exist.
            pass
        raise
