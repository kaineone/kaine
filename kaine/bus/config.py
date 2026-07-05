# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kaine.bus.errors import BusConfigError


DEFAULT_KAINE_TOML = "config/kaine.toml"
DEFAULT_SECRETS_TOML = "config/secrets.toml"


@dataclass(frozen=True)
class BusConfig:
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    username: Optional[str] = None
    password: Optional[str] = None
    default_maxlen: int = 100_000
    per_stream_maxlen: dict[str, int] = field(default_factory=dict)
    url_override: Optional[str] = None
    audit_required: bool = True

    @property
    def url(self) -> str:
        if self.url_override:
            return self.url_override
        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"
        elif self.password:
            auth = f":{self.password}@"
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def load_secrets_doc(secrets_toml: Optional[Path] = None) -> dict:
    """Read ``config/secrets.toml``, warning if it is group/world-readable.

    Returns an empty dict when the file is absent. Shared by the bus config
    loader and the cycle config loader so secrets parsing and the file-mode
    warning behave identically across both boot paths.
    """
    secrets_toml = secrets_toml or _project_root() / DEFAULT_SECRETS_TOML
    if secrets_toml.exists():
        mode = secrets_toml.stat().st_mode & 0o777
        if mode & 0o077:
            print(
                f"warning: {secrets_toml} mode 0o{mode:o} is world/group-readable; "
                "recommend chmod 600",
                file=sys.stderr,
            )
    return _read_toml(secrets_toml)


def load_bus_config(
    kaine_toml: Optional[Path] = None,
    secrets_toml: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> BusConfig:
    env = env if env is not None else os.environ
    root = _project_root()
    kaine_toml = kaine_toml or root / DEFAULT_KAINE_TOML
    secrets_toml = secrets_toml or root / DEFAULT_SECRETS_TOML

    kaine_doc = _read_toml(kaine_toml)
    secrets_doc = load_secrets_doc(secrets_toml)

    redis_doc = (kaine_doc.get("redis") or {})
    bus_doc = (kaine_doc.get("bus") or {})
    redis_secrets = (secrets_doc.get("redis") or {})

    url_override = env.get("KAINE_REDIS_URL") or redis_secrets.get("url")

    password = (
        env.get("KAINE_REDIS_PASSWORD")
        or redis_secrets.get("password")
        or redis_doc.get("password")
    )
    username = (
        env.get("KAINE_REDIS_USERNAME")
        or redis_secrets.get("username")
        or redis_doc.get("username")
    )

    config = BusConfig(
        host=str(redis_doc.get("host", "127.0.0.1")),
        port=int(redis_doc.get("port", 6379)),
        db=int(redis_doc.get("db", 0)),
        username=username,
        password=password,
        default_maxlen=int(bus_doc.get("default_maxlen", 100_000)),
        per_stream_maxlen={
            str(k): int(v)
            for k, v in (bus_doc.get("per_stream_maxlen") or {}).items()
        },
        url_override=url_override,
        audit_required=bool(bus_doc.get("audit_required", True)),
    )

    if not url_override and not config.password:
        raise BusConfigError(
            "no Redis password found in KAINE_REDIS_PASSWORD env, "
            f"{secrets_toml}, or {kaine_toml}; KAINE refuses to connect "
            "to an unauthenticated Redis on any host (the same checkout "
            "must be safe to ship onto network-attached hosts)"
        )
    return config


def maxlen_for(config: BusConfig, stream: str) -> int:
    return config.per_stream_maxlen.get(stream, config.default_maxlen)
