# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path

from kaine.transfer.email_request import (
    DEFAULT_RECIPIENT,
    RenderedEmail,
    SmtpConfig,
    render_request_email,
    send_or_write,
)


def test_render_contains_path_recipient_situation_no_entity_data():
    rendered = render_request_email(
        backup_path="/home/op/backups/entity_Kaine_Nova_20260607",
        recipient="kaine.one@tuta.com",
        entity_name="Kaine Nova",
    )
    assert "/home/op/backups/entity_Kaine_Nova_20260607" in rendered.body
    assert "kaine.one@tuta.com" in rendered.body
    assert "decommission" in rendered.body.lower()
    assert "Kaine Nova" in rendered.body
    # NEVER any entity-data tokens.
    blob = (rendered.subject + rendered.body).lower()
    for forbidden in ("transcript", "internal_speech", "memory:", "thought", "pcm"):
        assert forbidden not in blob


def test_custom_template_overridable():
    rendered = render_request_email(
        backup_path="/p",
        recipient="r@example.com",
        entity_name="Lyra",
        template="custom {entity_name} at {backup_path} contact {recipient}",
    )
    assert rendered.body == "custom Lyra at /p contact r@example.com"


def test_custom_template_bad_placeholder_falls_back():
    rendered = render_request_email(
        backup_path="/p",
        recipient="r@example.com",
        entity_name="Lyra",
        template="bad {does_not_exist}",
    )
    # Falls back to default (does not crash).
    assert "/p" in rendered.body and "Lyra" in rendered.body


def _rendered() -> RenderedEmail:
    return render_request_email(
        backup_path="/p/backup", recipient=DEFAULT_RECIPIENT, entity_name="Lyra"
    )


def test_does_not_send_without_confirm(tmp_path):
    smtp = SmtpConfig(
        enabled=True,
        host="smtp.example.com",
        port=587,
        from_addr="op@example.com",
        recipient=DEFAULT_RECIPIENT,
    )
    result = send_or_write(
        _rendered(),
        smtp_config=smtp,
        confirm=lambda: False,
        out_dir=tmp_path,
    )
    assert result.sent is False
    assert result.eml_path is not None and result.eml_path.is_file()
    assert result.mailto_link and result.mailto_link.startswith("mailto:")


def test_mailto_fallback_when_unconfigured(tmp_path):
    smtp = SmtpConfig(enabled=False)  # not configured
    result = send_or_write(
        _rendered(),
        smtp_config=smtp,
        confirm=lambda: True,  # confirmed, but SMTP not configured
        out_dir=tmp_path,
    )
    assert result.sent is False
    assert result.eml_path is not None and result.eml_path.is_file()
    assert "not configured" in result.detail.lower()


def test_sends_over_smtp_when_confirmed_and_configured(tmp_path, monkeypatch):
    sent_messages = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            sent_messages.append(("login", user, password))

        def send_message(self, msg):
            sent_messages.append(("send", msg["To"], msg["Subject"]))

    import kaine.transfer.email_request as mod

    monkeypatch.setattr(mod.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("KAINE_SMTP_PASSWORD", "secret")

    smtp = SmtpConfig(
        enabled=True,
        host="smtp.example.com",
        port=587,
        user="op@example.com",
        from_addr="op@example.com",
        recipient=DEFAULT_RECIPIENT,
    )
    result = send_or_write(
        _rendered(),
        smtp_config=smtp,
        confirm=lambda: True,
        out_dir=tmp_path,
    )
    assert result.sent is True
    assert any(m[0] == "send" for m in sent_messages)
    # No .eml fallback written when sent.
    assert not (tmp_path / "transfer_request.eml").exists()


def test_smtp_failure_falls_back_to_eml(tmp_path, monkeypatch):
    class BoomSMTP:
        def __init__(self, *a, **k):
            raise ConnectionRefusedError("nope")

    import kaine.transfer.email_request as mod

    monkeypatch.setattr(mod.smtplib, "SMTP", BoomSMTP)

    smtp = SmtpConfig(
        enabled=True,
        host="smtp.example.com",
        port=587,
        from_addr="op@example.com",
        recipient=DEFAULT_RECIPIENT,
    )
    result = send_or_write(
        _rendered(), smtp_config=smtp, confirm=lambda: True, out_dir=tmp_path
    )
    assert result.sent is False
    assert result.eml_path is not None and result.eml_path.is_file()
