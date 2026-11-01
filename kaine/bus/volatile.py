# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The never-persisted Redis instance that holds companion streams.

``kaine-redis-volatile`` runs with ``--appendonly no --save ""``: it exists only
in memory and is lost when it stops, so it is working state in the plain sense.
It holds the companion streams of ``kaine.bus.companion``. It is reached only on
the compose network (no host port) through ``KAINE_REDIS_VOLATILE_URL``, or the
``[redis_volatile].url`` entry of ``config/secrets.toml``.

The boot refuses a declared companion producer unless the instance answers,
requires a password, reports ``appendonly no`` and an empty ``save``, and every
declared companion stream is capped at no more than
``[privacy].companion_stream_maxlen`` (``companion_refusals``).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from kaine.bus.companion import CompanionRegistry

log = logging.getLogger(__name__)

#: Environment variable holding the volatile instance's URL (with its password).
VOLATILE_URL_ENV = "KAINE_REDIS_VOLATILE_URL"
#: Default and shipped cap of a companion stream, and the bound on any cap.
DEFAULT_COMPANION_STREAM_MAXLEN = 12_000
#: The keys ``[privacy]`` accepts.
PRIVACY_KEYS = frozenset({"companion_stream_maxlen"})


class PrivacyConfigError(ValueError):
    """``[privacy]`` is malformed."""


@dataclass(frozen=True)
class PrivacySettings:
    """``[privacy]``: the bound on every companion stream's cap."""

    companion_stream_maxlen: int = DEFAULT_COMPANION_STREAM_MAXLEN

    @classmethod
    def from_config(cls, kaine_config: Mapping[str, Any]) -> "PrivacySettings":
        section = kaine_config.get("privacy")
        if section is None:
            return cls()
        if not isinstance(section, Mapping):
            raise PrivacyConfigError("[privacy] must be a table")
        unknown = sorted(set(section) - PRIVACY_KEYS)
        if unknown:
            raise PrivacyConfigError(f"[privacy] has unknown keys: {', '.join(unknown)}")
        raw = section.get("companion_stream_maxlen", DEFAULT_COMPANION_STREAM_MAXLEN)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise PrivacyConfigError(
                "[privacy].companion_stream_maxlen must be a positive integer"
            )
        return cls(companion_stream_maxlen=raw)


def resolve_volatile_url(
    env: Optional[Mapping[str, str]] = None, secrets_toml: Optional[Path] = None
) -> Optional[str]:
    """The volatile instance's URL from the environment or ``config/secrets.toml``."""
    env = env if env is not None else os.environ
    url = env.get(VOLATILE_URL_ENV)
    if url:
        return url
    from kaine.bus.config import load_secrets_doc

    section = load_secrets_doc(secrets_toml).get("redis_volatile") or {}
    url = section.get("url") if isinstance(section, Mapping) else None
    return str(url) if url else None


@dataclass
class VolatileBus:
    """A client of the volatile instance: companion writes, reads, checks, flush."""

    client: Any
    companion_stream_maxlen: int = DEFAULT_COMPANION_STREAM_MAXLEN
    per_stream_maxlen: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        companion_stream_maxlen: int = DEFAULT_COMPANION_STREAM_MAXLEN,
        per_stream_maxlen: Optional[Mapping[str, int]] = None,
        client_name: Optional[str] = None,
    ) -> "VolatileBus":
        import redis.asyncio as aioredis

        kwargs: dict[str, Any] = {"decode_responses": True}
        if client_name is not None:
            kwargs["client_name"] = client_name
        return cls(
            client=aioredis.from_url(url, **kwargs),
            companion_stream_maxlen=companion_stream_maxlen,
            per_stream_maxlen=dict(per_stream_maxlen or {}),
        )

    def cap_for(self, stream: str) -> int:
        """The cap of companion stream ``stream`` (``[bus].per_stream_maxlen`` may
        set it lower than the bound; the boot refuses one set higher)."""
        return int(self.per_stream_maxlen.get(stream, self.companion_stream_maxlen))

    async def add(self, stream: str, values: Mapping[str, Any]) -> str:
        entry_id = await self.client.xadd(
            stream,
            {"values": json.dumps(values, separators=(",", ":"))},
            maxlen=self.cap_for(stream),
            approximate=True,
        )
        if isinstance(entry_id, bytes):
            entry_id = entry_id.decode()
        return str(entry_id)

    async def get(self, stream: str, entry_id: str) -> Optional[dict[str, Any]]:
        """The values of one companion entry, or None when it is gone."""
        entries = await self.client.xrange(stream, min=entry_id, max=entry_id, count=1)
        if not entries:
            return None
        _eid, fields = entries[0]
        raw = fields.get("values") if isinstance(fields, Mapping) else None
        if raw is None and isinstance(fields, Mapping):
            raw = fields.get(b"values")
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            values = json.loads(raw or "")
        except (TypeError, ValueError):
            return None
        return values if isinstance(values, dict) else None

    async def _config_value(self, key: str) -> Optional[str]:
        reply = await self.client.config_get(key)
        value = (reply or {}).get(key)
        if value is None:
            value = (reply or {}).get(key.encode())
        if isinstance(value, bytes):
            value = value.decode()
        return None if value is None else str(value)

    async def persistence_refusals(self) -> list[str]:
        """Reasons the instance may not hold companion streams; empty when it may."""
        try:
            await self.client.ping()
        except Exception as exc:
            return [f"the volatile bus does not answer ({type(exc).__name__})"]
        reasons: list[str] = []
        checks = (
            ("requirepass", lambda v: bool(v), "the volatile bus requires no password"),
            ("appendonly", lambda v: v == "no", "the volatile bus persists: appendonly is {v!r}, not 'no'"),
            ("save", lambda v: v == "", "the volatile bus persists: save is {v!r}, not empty"),
        )
        for key, ok, message in checks:
            try:
                value = await self._config_value(key)
            except Exception as exc:
                reasons.append(f"the volatile bus refuses CONFIG GET {key} ({type(exc).__name__})")
                continue
            if value is None or not ok(value):
                reasons.append(message.format(v=value))
        return reasons

    async def flush(self) -> None:
        """Remove every companion stream (decommission)."""
        await self.client.flushdb()

    async def close(self) -> None:
        try:
            await self.client.aclose()
        except AttributeError:
            await self.client.close()


async def companion_refusals(
    registry: CompanionRegistry,
    volatile: Optional[VolatileBus],
    settings: PrivacySettings,
) -> list[str]:
    """Every reason the declared companion producers may not run; empty when
    nothing is declared or every condition holds."""
    if not registry.declarations:
        return []
    producers = ", ".join(registry.producers())
    if volatile is None:
        return [
            f"companion producers ({producers}) need the volatile bus, and none is "
            f"configured ({VOLATILE_URL_ENV})"
        ]
    reasons = await volatile.persistence_refusals()
    for stream in registry.companion_streams():
        cap = volatile.cap_for(stream)
        if cap > settings.companion_stream_maxlen:
            reasons.append(
                f"companion stream {stream} is capped at {cap}, above "
                f"[privacy].companion_stream_maxlen {settings.companion_stream_maxlen}"
            )
    return reasons
