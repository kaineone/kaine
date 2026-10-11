# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import ipaddress
import logging
import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from kaine.config import deep_merge

log = logging.getLogger(__name__)


class NexusConfigError(RuntimeError):
    """Nexus configuration is unsafe or invalid and the server must not start."""


@dataclass(frozen=True)
class NexusConfig:
    host: str = "127.0.0.1"
    port: int = 8088
    conversation_enabled: bool = False
    diagnostics_enabled: bool = True
    conversation_history_lookback: int = 50
    # Privacy override. Default False. When True, diagnostics surface
    # receives full content payloads. Operators see a "dev mode" banner.
    dev_content_override: bool = False
    # Read-only mode. Default False. When True, all state-changing HTTP
    # methods are refused with 403; only GET/HEAD/OPTIONS are allowed.
    read_only: bool = False
    # Operator authentication. Empty string means no token is configured;
    # state-changing endpoints and privileged read surfaces return 401.
    # Loaded from KAINE_NEXUS_TOKEN env or config/secrets.toml [nexus] operator_token.
    operator_token: str = field(default="", repr=False)
    # CSRF/Origin protection. Defaults cover loopback-only operation.
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:8088",
        "http://localhost:8088",
        "http://[::1]:8088",
    )
    host_allowlist: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
    # Explicit opt-in required to bind a non-loopback interface.
    non_loopback_allowed: bool = False
    # Access mode. The dataclass default is "token" so existing tests keep
    # their semantics; config/kaine.toml ships "open".
    access: str = "token"
    # Session / brute-force protection defaults.
    session_idle_minutes: int = 720
    session_max_hours: int = 24
    login_max_failures: int = 5
    login_failure_window_s: int = 300
    # Delay applied to login attempts from a client that has already exceeded
    # the failure limit. Slows brute-force guessing while still allowing a
    # correct token to log in.
    login_block_delay_s: float = 2.0

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "NexusConfig":
        data = dict(data or {})
        return cls(
            host=str(data.get("host", cls.host)),
            port=int(data.get("port", cls.port)),
            conversation_enabled=bool(data.get("conversation_enabled", cls.conversation_enabled)),
            diagnostics_enabled=bool(data.get("diagnostics_enabled", cls.diagnostics_enabled)),
            conversation_history_lookback=int(
                data.get("conversation_history_lookback", cls.conversation_history_lookback)
            ),
            dev_content_override=bool(data.get("dev_content_override", cls.dev_content_override)),
            read_only=bool(data.get("read_only", cls.read_only)),
            operator_token=str(data.get("operator_token", cls.operator_token)),
            allowed_origins=cls._parse_string_tuple(
                data.get("allowed_origins", cls.allowed_origins)
            ),
            host_allowlist=cls._parse_string_tuple(data.get("host_allowlist", cls.host_allowlist)),
            non_loopback_allowed=bool(data.get("non_loopback_allowed", cls.non_loopback_allowed)),
            access=_validate_access(data.get("access", cls.access), "[nexus].access"),
            session_idle_minutes=int(data.get("session_idle_minutes", cls.session_idle_minutes)),
            session_max_hours=int(data.get("session_max_hours", cls.session_max_hours)),
            login_max_failures=int(data.get("login_max_failures", cls.login_max_failures)),
            login_failure_window_s=int(
                data.get("login_failure_window_s", cls.login_failure_window_s)
            ),
            login_block_delay_s=float(
                data.get("login_block_delay_s", cls.login_block_delay_s)
            ),
        )

    @staticmethod
    def _parse_string_tuple(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(v.strip() for v in value.split(",") if v.strip())
        if isinstance(value, (list, tuple)):
            return tuple(str(v).strip() for v in value if str(v).strip())
        return ()


def _env_flag(name: str) -> bool | None:
    """Parse a boolean deployment override from the environment.

    Returns ``None`` when the variable is unset so the TOML value (or the
    dataclass default) is kept untouched; otherwise maps the common truthy
    spellings (``1``/``true``/``yes``/``on``, case-insensitive) to ``True`` and
    everything else to ``False``.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_ACCESS_MODES = ("open", "token")
_HOST_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _validate_access(value: Any, source: str) -> str:
    if value not in _ACCESS_MODES:
        raise NexusConfigError(
            f"{source} must be 'open' or 'token', got {value!r}"
        )
    return value


def _is_valid_host(name: str) -> bool:
    if not name or len(name) > 253:
        return False
    if name.endswith("."):
        name = name[:-1]
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    labels = name.split(".")
    if not labels or any(len(label) > 63 for label in labels):
        return False
    return all(_HOST_LABEL_RE.match(label) for label in labels)


def _parse_extra_hosts(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _extra_host_origins(
    host: str, port: int, published_port: int | None
) -> tuple[str, ...]:
    try:
        addr = ipaddress.ip_address(host)
        display = f"[{host}]" if addr.version == 6 else host
    except ValueError:
        display = host
    ports = [port]
    if published_port is not None and published_port != port:
        ports.append(published_port)
    origins: list[str] = []
    for scheme in ("http", "https"):
        for p in ports:
            origins.append(f"{scheme}://{display}")
            origins.append(f"{scheme}://{display}:{p}")
    seen: set[str] = set()
    result: list[str] = []
    for origin in origins:
        if origin not in seen:
            seen.add(origin)
            result.append(origin)
    return tuple(result)


def _raise_if_config_token(section: Any, file: Path) -> None:
    """Refuse to start if a config file (not a secrets file) holds a token."""
    if not isinstance(section, dict):
        return
    token = section.get("operator_token")
    if token and str(token).strip():
        raise NexusConfigError(
            f"non-empty operator_token in config file {file}: "
            "move it to config/secrets.toml or set KAINE_NEXUS_TOKEN"
        )


def load_nexus_config(
    path: str | os.PathLike[str] | None = None,
    *,
    operator_path: str | os.PathLike[str] | None = None,
    secrets_path: str | os.PathLike[str] | None = None,
) -> NexusConfig:
    target = Path(path or "config/kaine.toml")
    raw: dict[str, Any] = {}
    if target.exists():
        raw = tomllib.loads(target.read_text(encoding="utf-8"))

    # The committed, tracked config/kaine.toml is not a secrets file.
    _raise_if_config_token(raw.get("nexus"), target)

    base_dir = target.parent
    operator_target = Path(operator_path or base_dir / "kaine.operator.toml")
    overlay: dict[str, Any] = {}
    if operator_target.exists():
        try:
            overlay = tomllib.loads(operator_target.read_text(encoding="utf-8"))
        except Exception as e:
            raise NexusConfigError(
                f"malformed Nexus operator overlay: {operator_target}"
            ) from e

    # Operator overlays are config files, not secrets files.
    _raise_if_config_token(overlay.get("nexus"), operator_target)

    if overlay:
        raw = deep_merge(raw, overlay)

    merged_nexus = raw.get("nexus") or {}
    config = NexusConfig.from_mapping(merged_nexus)

    # Deployment overrides. A container mounts the baked, always-current kaine.toml
    # and expresses its handful of deployment-specific deltas through the environment
    # rather than a hand-maintained parallel copy of the whole config (which silently
    # drifts from the source of truth). KAINE_NEXUS_HOST / KAINE_NEXUS_PORT bind all
    # interfaces inside the container — the shipped default 127.0.0.1 is unreachable
    # via the published port mapping — while the compose publish rule keeps external
    # exposure loopback-only. KAINE_NEXUS_CONVERSATION_ENABLED toggles the
    # conversation surface (the only [nexus] delta with no other env knob).
    host = os.environ.get("KAINE_NEXUS_HOST")
    port = os.environ.get("KAINE_NEXUS_PORT")
    if host or port:
        config = replace(
            config,
            host=host or config.host,
            port=int(port) if port else config.port,
        )
    conversation = _env_flag("KAINE_NEXUS_CONVERSATION_ENABLED")
    if conversation is not None:
        config = replace(config, conversation_enabled=conversation)

    non_loopback = _env_flag("KAINE_NEXUS_NON_LOOPBACK_ALLOWED")
    if non_loopback is not None:
        config = replace(config, non_loopback_allowed=non_loopback)

    read_only = _env_flag("KAINE_NEXUS_READ_ONLY")
    if read_only is not None:
        config = replace(config, read_only=read_only)

    access_env = os.environ.get("KAINE_NEXUS_ACCESS")
    if access_env is not None and access_env.strip():
        access_env = access_env.strip()
        config = replace(
            config, access=_validate_access(access_env, "[nexus].access")
        )

    env_token = (os.environ.get("KAINE_NEXUS_TOKEN") or "").strip()
    if env_token:
        config = replace(config, operator_token=env_token)
    else:
        secrets_target = Path(secrets_path or base_dir / "secrets.toml")
        if secrets_target.exists():
            try:
                secrets_raw = tomllib.loads(secrets_target.read_text(encoding="utf-8"))
            except Exception as e:
                raise NexusConfigError(
                    f"malformed Nexus secrets file: {secrets_target}"
                ) from e
            secrets_token = (secrets_raw.get("nexus") or {}).get("operator_token")
            if secrets_token:
                token = str(secrets_token).strip()
                if token:
                    config = replace(config, operator_token=token)

    if config.operator_token and len(config.operator_token) < 32:
        raise NexusConfigError(
            "operator token is shorter than 32 characters; generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    origins_env = os.environ.get("KAINE_NEXUS_ALLOWED_ORIGINS")
    if origins_env is not None:
        config = replace(
            config,
            allowed_origins=NexusConfig._parse_string_tuple(origins_env),
        )
    elif "allowed_origins" not in merged_nexus:
        config = replace(
            config,
            allowed_origins=(
                f"http://127.0.0.1:{config.port}",
                f"http://localhost:{config.port}",
                f"http://[::1]:{config.port}",
            ),
        )

    extra_hosts_env = os.environ.get("KAINE_NEXUS_EXTRA_HOSTS")
    extra_hosts = _parse_extra_hosts(extra_hosts_env)
    published_port_env = os.environ.get("KAINE_NEXUS_PUBLISHED_PORT")
    published_port = (
        int(published_port_env.strip())
        if published_port_env is not None and published_port_env.strip()
        else None
    )
    if extra_hosts:
        for h in extra_hosts:
            if not _is_valid_host(h):
                raise NexusConfigError(
                    f"KAINE_NEXUS_EXTRA_HOSTS entry {h!r} is not a valid host name or IP literal"
                )

        hosts_list = list(config.host_allowlist)
        for h in extra_hosts:
            if h not in hosts_list:
                hosts_list.append(h)

        origins_list = list(config.allowed_origins)
        for h in extra_hosts:
            for origin in _extra_host_origins(h, config.port, published_port):
                if origin not in origins_list:
                    origins_list.append(origin)

        config = replace(
            config,
            host_allowlist=tuple(hosts_list),
            allowed_origins=tuple(origins_list),
        )

    return config
