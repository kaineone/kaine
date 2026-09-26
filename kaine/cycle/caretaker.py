# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Caretaker notices for unattended boot condition 7.

All notices are content-free: they contain only the install label, the
current time, the event kind, gate condition results, and the Nexus address.
Cognitive content, affect, welfare signals, or perception data are never
included.

This module uses only the Python standard library and KAINE's config /
secrets helpers.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import shutil
import socket
import ssl
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from urllib.parse import urlparse

from kaine.config import require_known_keys
from kaine.secrets_file import read_toml_field

log = logging.getLogger("kaine.cycle.caretaker")

_INSTALL_LABEL_RE = re.compile(
    r"^[A-Za-z0-9._-](?:[A-Za-z0-9 ._-]{0,62}[A-Za-z0-9._-])?$"
)
_TOKEN_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_NEXUS_URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-:\[\]/_]+$")
_EVENT_TITLE = {
    "starting_unattended": "starting unattended",
    "unattended_refused": "unattended start refused",
    "reminder": "acknowledgement reminder",
    "spot_escalation": "Spot escalation",
    "supervision_lost": "supervision lost",
    "welfare_response": "welfare response fired",
    "input_lost": "input lost",
    "boot_failed": "boot failed",
}

EVENT_KINDS = tuple(_EVENT_TITLE)
NOTICE_FIELDS = ("install_label", "time", "event", "conditions", "nexus_url")

_ALLOWED_IPV4 = (
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("100.64.0.0/10"),
)

_ALLOWED_IPV6 = (
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
)


class CaretakerConfigError(ValueError):
    """The [caretaker] section is missing a required value or is invalid."""


@dataclass(frozen=True)
class ChannelConfig:
    kind: str
    url: str | None = None
    token_name: str | None = None


@dataclass(frozen=True)
class CaretakerConfig:
    install_label: str = "kaine"
    channels: tuple[ChannelConfig, ...] = ()
    reminder_interval_s: float = 14400.0
    input_loss_after_s: float = 60.0
    nexus_url: str = "http://127.0.0.1:8088/"

    @classmethod
    def from_section(cls, section: dict) -> "CaretakerConfig":
        allowed = {
            "install_label",
            "channels",
            "reminder_interval_s",
            "input_loss_after_s",
            "nexus_url",
        }
        try:
            require_known_keys(section, allowed, "[caretaker]")
        except ValueError as exc:
            raise CaretakerConfigError(str(exc)) from None

        install_label = section.get("install_label", cls.install_label)
        if not isinstance(install_label, str) or not _INSTALL_LABEL_RE.fullmatch(
            install_label
        ):
            raise CaretakerConfigError(
                "invalid [caretaker].install_label: must match "
                "^[A-Za-z0-9._-](?:[A-Za-z0-9 ._-]{0,62}[A-Za-z0-9._-])?$ "
                "(1-64 characters, no leading or trailing space)"
            )

        reminder_interval_s = section.get("reminder_interval_s", cls.reminder_interval_s)
        if (
            isinstance(reminder_interval_s, bool)
            or not isinstance(reminder_interval_s, (int, float))
            or reminder_interval_s < 900
        ):
            raise CaretakerConfigError(
                "invalid [caretaker].reminder_interval_s: must be a number >= 900"
            )

        input_loss_after_s = section.get("input_loss_after_s", cls.input_loss_after_s)
        if (
            isinstance(input_loss_after_s, bool)
            or not isinstance(input_loss_after_s, (int, float))
            or input_loss_after_s <= 0
        ):
            raise CaretakerConfigError(
                "invalid [caretaker].input_loss_after_s: must be a number > 0"
            )

        nexus_url = section.get("nexus_url", cls.nexus_url)
        if not isinstance(nexus_url, str) or not _NEXUS_URL_RE.fullmatch(nexus_url):
            raise CaretakerConfigError(
                "invalid [caretaker].nexus_url: must match ^https?://[A-Za-z0-9.\\-:\\[\\]/_]+$"
            )

        raw_channels = section.get("channels", [])
        if not isinstance(raw_channels, list):
            raise CaretakerConfigError(
                "invalid [caretaker].channels: must be a list of tables"
            )

        channel_configs: list[ChannelConfig] = []
        for idx, table in enumerate(raw_channels):
            if not isinstance(table, dict):
                raise CaretakerConfigError(
                    f"invalid [caretaker].channels[{idx}]: must be a table"
                )
            extra = set(table) - {"kind", "url", "token_name"}
            if extra:
                raise CaretakerConfigError(
                    f"invalid keys in [caretaker].channels[{idx}]: {sorted(extra)}"
                )

            kind = table.get("kind")
            if kind not in ("desktop", "http"):
                raise CaretakerConfigError(
                    f"invalid [caretaker].channels[{idx}].kind: must be 'desktop' or 'http'"
                )

            url = table.get("url")
            token_name = table.get("token_name")

            if kind == "desktop":
                if url is not None or token_name is not None:
                    raise CaretakerConfigError(
                        f"desktop channel [{idx}] must not have url or token_name"
                    )
                channel_configs.append(ChannelConfig(kind="desktop"))
                continue

            # http channel
            if not isinstance(url, str) or not url:
                raise CaretakerConfigError(
                    f"http channel [{idx}] requires a url"
                )
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise CaretakerConfigError(
                    f"http channel [{idx}] url must use http or https"
                )
            if not parsed.hostname:
                raise CaretakerConfigError(
                    f"http channel [{idx}] url must have a host"
                )
            if parsed.username is not None or parsed.password is not None:
                raise CaretakerConfigError(
                    f"http channel [{idx}] url must not contain credentials; use token_name"
                )

            # IP literals are checked immediately; hostnames are checked after DNS at send time.
            try:
                addr = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                addr = None
            if addr is not None and not is_allowed_address(parsed.hostname):
                raise CaretakerConfigError(
                    f"http channel [{idx}] destination is a public or disallowed address"
                )

            if token_name is not None and (
                not isinstance(token_name, str)
                or not _TOKEN_NAME_RE.fullmatch(token_name)
            ):
                raise CaretakerConfigError(
                    f"invalid [caretaker].channels[{idx}].token_name: "
                    f"must match ^[a-z0-9_]{{1,64}}$"
                )

            channel_configs.append(
                ChannelConfig(kind="http", url=url, token_name=token_name)
            )

        return cls(
            install_label=install_label,
            channels=tuple(channel_configs),
            reminder_interval_s=float(reminder_interval_s),
            input_loss_after_s=float(input_loss_after_s),
            nexus_url=nexus_url,
        )


def is_allowed_address(ip: str) -> bool:
    """True only for loopback, RFC 1918, 100.64/10, and fc00::/7 (and ::1)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped
        if mapped is not None:
            addr = mapped

    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in net for net in _ALLOWED_IPV4)
    return any(addr in net for net in _ALLOWED_IPV6)


def build_notice(
    event: str,
    config: CaretakerConfig,
    *,
    conditions: Mapping[str, bool] | None = None,
    now: datetime | None = None,
) -> dict:
    """Build a content-free caretaker notice."""
    if event not in EVENT_KINDS:
        raise ValueError(f"unknown caretaker event: {event!r}")

    if now is None:
        now = datetime.now(timezone.utc)
    return {
        "install_label": config.install_label,
        "time": now.isoformat(),
        "event": event,
        "conditions": dict(conditions) if conditions is not None else None,
        "nexus_url": config.nexus_url,
    }


def render_text(notice: dict) -> tuple[str, str]:
    """Return (title, message) for a notice."""
    install_label = notice["install_label"]
    event = notice["event"]
    title = f"KAINE {install_label}: {_EVENT_TITLE[event]}"

    parts: list[str] = []
    conditions = notice.get("conditions")
    if isinstance(conditions, dict):
        failed = [name for name, ok in conditions.items() if not ok]
        if failed:
            parts.append("Failed gate conditions: " + ", ".join(failed))
    parts.append(f"Nexus: {notice['nexus_url']}")
    return title, "\n".join(parts)


@dataclass(frozen=True)
class ChannelResult:
    kind: str
    accepted: bool
    detail: str


def _gvariant_string(s: str) -> str:
    """Return ``s`` as a GVariant string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def send_desktop(
    notice: dict,
    *,
    runner=subprocess.run,
    timeout_s: float = 5.0,
) -> ChannelResult:
    """Send the notice as a freedesktop notification over the session D-Bus."""
    if shutil.which("gdbus") is None:
        return ChannelResult(kind="desktop", accepted=False, detail="gdbus not installed")

    title, message = render_text(notice)
    argv = [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.Notifications",
        "--object-path",
        "/org/freedesktop/Notifications",
        "--method",
        "org.freedesktop.Notifications.Notify",
        # End of gdbus options: without it the trailing "-1" timeout is parsed
        # as an option and gdbus prints its usage instead of calling Notify.
        "--",
        _gvariant_string("KAINE"),
        "0",
        _gvariant_string(""),
        _gvariant_string(title),
        _gvariant_string(message),
        "[]",
        "{}",
        "-1",
    ]

    try:
        proc = runner(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return ChannelResult(kind="desktop", accepted=False, detail="TimeoutExpired")
    except OSError as exc:
        return ChannelResult(kind="desktop", accepted=False, detail=type(exc).__name__)

    if proc.returncode == 0 and re.search(r"\(\s*uint32\s+\d+\s*,\s*\)", proc.stdout):
        return ChannelResult(kind="desktop", accepted=True, detail="")

    detail = f"gdbus exit {proc.returncode}"
    if proc.stderr:
        detail += f": {proc.stderr.strip()[:120]}"
    return ChannelResult(kind="desktop", accepted=False, detail=detail)


class _VerifiedHostHTTPSConnection(HTTPSConnection):
    """HTTPSConnection that verifies the hostname while connecting to a checked IP."""

    def __init__(self, host: str, port: int, server_hostname: str, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._server_hostname = server_hostname

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = _tls_context().wrap_socket(sock, server_hostname=self._server_hostname)


def _tls_context() -> ssl.SSLContext:
    """Certificate- and hostname-verifying context that refuses TLS below 1.2."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def send_http(
    notice: dict,
    url: str,
    token: str | None,
    *,
    resolver=socket.getaddrinfo,
    timeout_s: float = 5.0,
) -> ChannelResult:
    """POST the notice to a private HTTP(S) endpoint."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ChannelResult(
            kind="http", accepted=False, detail="unsupported URL scheme"
        )

    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if host is None:
        return ChannelResult(kind="http", accepted=False, detail="missing host")

    if parsed.username is not None or parsed.password is not None:
        return ChannelResult(
            kind="http", accepted=False, detail="url contains credentials"
        )

    try:
        results = resolver(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        return ChannelResult(
            kind="http", accepted=False, detail=f"could not resolve host: {type(exc).__name__}"
        )

    if not results:
        return ChannelResult(
            kind="http", accepted=False, detail="could not resolve host"
        )

    for family, socktype, proto, canonname, sockaddr in results:
        ip_str = sockaddr[0]
        if not is_allowed_address(ip_str):
            return ChannelResult(
                kind="http",
                accepted=False,
                detail="destination resolves to a public address",
            )

    first = results[0]
    ip_str = first[4][0]
    conn: HTTPConnection | HTTPSConnection

    path = parsed.path or "/"
    if parsed.query:
        path = path + "?" + parsed.query

    title, message = render_text(notice)
    payload = {"title": title, "message": message, **notice}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    ipv6 = isinstance(addr, ipaddress.IPv6Address)
    if parsed.port is not None:
        host_header = f"[{host}]:{port}" if ipv6 else f"{host}:{port}"
    else:
        host_header = f"[{host}]" if ipv6 else host

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "Host": host_header,
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    try:
        if parsed.scheme == "https":
            conn = _VerifiedHostHTTPSConnection(
                ip_str, port, server_hostname=host, timeout=timeout_s
            )
        else:
            conn = HTTPConnection(ip_str, port, timeout=timeout_s)

        try:
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            if 200 <= response.status < 300:
                return ChannelResult(kind="http", accepted=True, detail="")
            return ChannelResult(
                kind="http",
                accepted=False,
                detail=f"HTTP {response.status}",
            )
        finally:
            conn.close()
    except Exception as exc:
        return ChannelResult(
            kind="http",
            accepted=False,
            detail=type(exc).__name__,
        )


def load_token(
    token_name: str | None,
    *,
    secrets_path: Path = Path("config/secrets.toml"),
) -> str | None:
    """Read a bearer token name from config/secrets.toml."""
    if token_name is None:
        return None
    try:
        return read_toml_field(secrets_path, "caretaker.tokens", token_name)
    except Exception:
        log.warning("malformed secrets file, cannot load caretaker token")
        return None


def notify(
    config: CaretakerConfig,
    notice: dict,
    *,
    secrets_path: Path = Path("config/secrets.toml"),
    desktop_sender=send_desktop,
    http_sender=send_http,
) -> list[ChannelResult]:
    """Send a notice to every configured caretaker channel."""
    results: list[ChannelResult] = []
    for channel in config.channels:
        try:
            if channel.kind == "desktop":
                result = desktop_sender(notice)
            elif channel.kind == "http":
                token = load_token(channel.token_name, secrets_path=secrets_path)
                result = http_sender(notice, channel.url, token)
            else:  # pragma: no cover - validated at config time
                result = ChannelResult(
                    kind=channel.kind, accepted=False, detail="unsupported channel kind"
                )
        except Exception as exc:
            result = ChannelResult(
                kind=channel.kind,
                accepted=False,
                detail=type(exc).__name__,
            )
        results.append(result)
        log.info(
            "caretaker channel %s: accepted=%s detail=%s",
            result.kind,
            result.accepted,
            result.detail,
        )
    return results


def check_caretaker_condition(
    caretaker_section: dict | None,
    *,
    prerequisites_ok: bool,
    conditions: Mapping[str, bool],
    notify_fn=notify,
    secrets_path: Path = Path("config/secrets.toml"),
):
    """Evaluate unattended gate condition 7: the caretaker must be told.

    This function imports ``Condition`` and ``CONDITION_NAMES`` from
    ``kaine.cycle.unattended_gate`` locally to avoid an import cycle.
    """
    from kaine.cycle.unattended_gate import CONDITION_NAMES, Condition

    if caretaker_section is None:
        caretaker_section = {}

    try:
        cfg = CaretakerConfig.from_section(caretaker_section)
    except CaretakerConfigError as exc:
        return Condition(
            number=7,
            name=CONDITION_NAMES[7],
            ok=False,
            reason=f"invalid [caretaker] config: {exc}",
        )

    if not cfg.channels:
        return Condition(
            number=7,
            name=CONDITION_NAMES[7],
            ok=False,
            reason="no channel configured",
        )

    if not prerequisites_ok:
        return Condition(
            number=7,
            name=CONDITION_NAMES[7],
            ok=False,
            reason="not attempted: other conditions failed",
        )

    notice = build_notice("starting_unattended", cfg, conditions=conditions)
    results = notify_fn(cfg, notice, secrets_path=secrets_path)
    if any(r.accepted for r in results):
        return Condition(
            number=7,
            name=CONDITION_NAMES[7],
            ok=True,
            reason="",
        )

    details = "; ".join(f"{r.kind}: {r.detail}" for r in results)
    return Condition(
        number=7,
        name=CONDITION_NAMES[7],
        ok=False,
        reason=f"no channel accepted the notice: {details}",
    )


def send_refusal_notice(
    caretaker_section: dict | None,
    conditions: Mapping[str, bool],
    *,
    notify_fn=notify,
    secrets_path: Path = Path("config/secrets.toml"),
) -> None:
    """Best-effort refusal notice. Invalid or channel-less config is ignored."""
    if caretaker_section is None:
        log.debug("no [caretaker] section, skipping refusal notice")
        return

    try:
        cfg = CaretakerConfig.from_section(caretaker_section)
    except CaretakerConfigError as exc:
        log.debug("invalid [caretaker] config, skipping refusal notice: %s", exc)
        return

    if not cfg.channels:
        log.debug("no caretaker channels, skipping refusal notice")
        return

    notice = build_notice("unattended_refused", cfg, conditions=conditions)
    try:
        notify_fn(cfg, notice, secrets_path=secrets_path)
    except Exception as exc:
        log.warning("failed to send caretaker refusal notice: %s", type(exc).__name__)


__all__ = [
    "CaretakerConfigError",
    "ChannelConfig",
    "CaretakerConfig",
    "is_allowed_address",
    "EVENT_KINDS",
    "NOTICE_FIELDS",
    "build_notice",
    "render_text",
    "ChannelResult",
    "send_desktop",
    "send_http",
    "load_token",
    "notify",
    "check_caretaker_condition",
    "send_refusal_notice",
]
