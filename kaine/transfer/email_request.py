# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator-confirmed request-for-storage mailer.

A small, general primitive: render a customizable request email asking a
recipient (by default the project guardians) to provide storage so an operator
can upload a decommissioned entity's **encrypted** backup, then either send it
over operator-configured SMTP (only on explicit per-send confirmation) or write
it out as a ``.eml`` file plus a ``mailto:`` link for the operator to send from
their own client.

Privacy invariant (CAL 4.3): the rendered email carries ONLY the request, the
situation, the recipient/contact, and the **local filesystem path** of the
encrypted backup on this machine. It NEVER contains entity data — no
transcripts, no speech, no cognitive content. The backup itself is not
attached; it stays local until the project replies with server details.

The SMTP password is read exclusively from the environment variable
``KAINE_SMTP_PASSWORD`` — never from a config file, never logged.
"""
from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

log = logging.getLogger(__name__)

#: The environment variable the SMTP password is read from (never a file).
SMTP_PASSWORD_ENV = "KAINE_SMTP_PASSWORD"

#: Suggested default recipient — the project guardians.
DEFAULT_RECIPIENT = "kaine.one@tuta.com"


@dataclass(frozen=True)
class RenderedEmail:
    """A rendered request email: a subject and a plain-text body.

    Carries no attachment and no entity data — only the request text.
    """

    subject: str
    body: str
    recipient: str


@dataclass(frozen=True)
class SmtpConfig:
    """Operator-configured SMTP settings (loaded from the ``[transfer]`` table).

    The password is intentionally absent — it is resolved at send time from the
    ``KAINE_SMTP_PASSWORD`` environment variable, never from this config.
    """

    enabled: bool = False
    host: str = ""
    port: int = 587
    user: str = ""
    from_addr: str = ""
    recipient: str = ""
    use_starttls: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "SmtpConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            host=str(data.get("smtp_host", "") or ""),
            port=int(data.get("smtp_port", 587) or 587),
            user=str(data.get("smtp_user", "") or ""),
            from_addr=str(data.get("from_addr", "") or ""),
            recipient=str(data.get("recipient", "") or ""),
            use_starttls=bool(data.get("use_starttls", True)),
        )

    @property
    def complete(self) -> bool:
        """True iff host/port/from/recipient are all set (password is env-only)."""
        return bool(
            self.host
            and self.port
            and self.from_addr
            and self.recipient
        )


@dataclass(frozen=True)
class SendResult:
    """Outcome of :func:`send_or_write`.

    Exactly one of ``sent`` / written-file is meaningful: when ``sent`` is
    True the email went out over SMTP; otherwise ``eml_path`` and
    ``mailto_link`` describe the fallback the operator must act on.
    """

    sent: bool
    detail: str
    eml_path: Path | None = None
    mailto_link: str | None = None


# The default, operator-customizable body. ``{...}`` placeholders are filled by
# render_request_email; an operator may pass an entirely custom template with
# the same placeholders. NO entity data appears here by construction.
_DEFAULT_TEMPLATE = """\
Hello,

I am the operator of a KAINE entity named "{entity_name}". I have
decommissioned this entity. The individuation assessment indicated it had
diverged (become an individual), so under the Cognitive Architecture License
(Article 4.2) I have preserved its complete, transferable cognitive state and
am requesting safekeeping for it until a new guardian can run it.

The encrypted backup currently lives ONLY on this machine, at:

    {backup_path}

Nothing has been uploaded. Please reply with the server / storage details you
would like me to upload the encrypted bundle to, and I will transfer it.

This message contains no part of the entity's inner life — only this request,
the situation, and the local path of the encrypted bundle (CAL Article 4.3).

You can reach the project at: {recipient}

Thank you,
A KAINE operator
"""


def render_request_email(
    *,
    backup_path: str,
    recipient: str,
    entity_name: str,
    template: str | None = None,
) -> RenderedEmail:
    """Render the request-for-storage email (subject + body).

    Parameters
    ----------
    backup_path:
        Local filesystem path of the encrypted backup on THIS machine. This is
        the only path-like data the email carries.
    recipient:
        Contact address (the project guardians by default).
    entity_name:
        The decommissioned entity's name (its label, not its inner content).
    template:
        Optional operator-customized body template using the ``{entity_name}``,
        ``{backup_path}``, and ``{recipient}`` placeholders. Falls back to the
        shipped default.
    """
    body_template = template if template is not None else _DEFAULT_TEMPLATE
    try:
        body = body_template.format(
            entity_name=entity_name,
            backup_path=backup_path,
            recipient=recipient,
        )
    except (KeyError, IndexError):
        # A custom template with an unknown placeholder must not crash the
        # decommission; fall back to the default body.
        log.warning(
            "render_request_email: custom template had an unknown placeholder; "
            "using the default body"
        )
        body = _DEFAULT_TEMPLATE.format(
            entity_name=entity_name,
            backup_path=backup_path,
            recipient=recipient,
        )
    subject = f"KAINE entity safekeeping request — {entity_name}"
    return RenderedEmail(subject=subject, body=body, recipient=recipient)


def _mailto(rendered: RenderedEmail) -> str:
    return (
        f"mailto:{rendered.recipient}"
        f"?subject={quote(rendered.subject)}"
        f"&body={quote(rendered.body)}"
    )


def _write_eml(rendered: RenderedEmail, *, smtp_config: SmtpConfig, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    msg = EmailMessage()
    msg["To"] = rendered.recipient
    if smtp_config.from_addr:
        msg["From"] = smtp_config.from_addr
    msg["Subject"] = rendered.subject
    msg.set_content(rendered.body)
    target = out_dir / "transfer_request.eml"
    tmp = target.with_suffix(".eml.tmp")
    tmp.write_bytes(bytes(msg))
    os.replace(tmp, target)
    return target


def send_or_write(
    rendered: RenderedEmail,
    *,
    smtp_config: SmtpConfig,
    confirm: Callable[[], bool],
    out_dir: Path,
) -> SendResult:
    """Send the rendered email over SMTP, else write it out for the operator.

    The email is sent ONLY when both:
      * ``confirm()`` returns True (explicit per-send operator confirmation), and
      * ``smtp_config.complete`` is True AND ``smtp_config.enabled`` is True.

    The password comes from the ``KAINE_SMTP_PASSWORD`` environment variable.
    In every other case (declined, not configured, or a send error) the
    rendered email is written to ``out_dir/transfer_request.eml`` and a
    ``mailto:`` link is returned for the operator to send it themselves.
    """
    # Always confirm first — never send without an explicit yes.
    try:
        confirmed = bool(confirm())
    except Exception:
        log.warning("send_or_write: confirm() raised; treating as declined", exc_info=True)
        confirmed = False

    mailto = _mailto(rendered)

    if not confirmed:
        eml = _write_eml(rendered, smtp_config=smtp_config, out_dir=out_dir)
        return SendResult(
            sent=False,
            detail="Send declined; wrote the request for you to send manually.",
            eml_path=eml,
            mailto_link=mailto,
        )

    if not (smtp_config.enabled and smtp_config.complete):
        eml = _write_eml(rendered, smtp_config=smtp_config, out_dir=out_dir)
        return SendResult(
            sent=False,
            detail=(
                "SMTP is not configured (need enabled host/port/from/recipient); "
                "wrote the request for you to send manually."
            ),
            eml_path=eml,
            mailto_link=mailto,
        )

    password = os.environ.get(SMTP_PASSWORD_ENV)
    msg = EmailMessage()
    msg["To"] = rendered.recipient
    msg["From"] = smtp_config.from_addr
    msg["Subject"] = rendered.subject
    msg.set_content(rendered.body)

    try:
        with smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=30) as server:
            if smtp_config.use_starttls:
                server.starttls()
            if smtp_config.user and password:
                server.login(smtp_config.user, password)
            server.send_message(msg)
        return SendResult(
            sent=True,
            detail=f"Request sent to {rendered.recipient} via {smtp_config.host}.",
            eml_path=None,
            mailto_link=None,
        )
    except Exception as exc:
        log.warning("send_or_write: SMTP send failed", exc_info=True)
        eml = _write_eml(rendered, smtp_config=smtp_config, out_dir=out_dir)
        return SendResult(
            sent=False,
            detail=(
                f"SMTP send failed ({type(exc).__name__}); wrote the request for "
                "you to send manually."
            ),
            eml_path=eml,
            mailto_link=mailto,
        )
