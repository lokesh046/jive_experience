"""Outgoing email over SMTP.

Kept free of business rules: it turns a finished message into bytes on the
wire. Sending runs in a worker thread because `smtplib` is blocking.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError


@dataclass(frozen=True)
class InlineImage:
    """A picture shown inside the message body, referenced as `cid:<cid>`."""

    cid: str
    png: bytes


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str
    images: list[InlineImage] = field(default_factory=list)


def build_message(settings: Settings, mail: Mail) -> EmailMessage:
    assert settings.mail_from is not None
    message = EmailMessage()
    message["From"] = formataddr((settings.mail_from_name, settings.mail_from))
    message["To"] = mail.to
    message["Subject"] = mail.subject
    message["Message-ID"] = make_msgid(domain=settings.mail_from.split("@")[-1])
    message.set_content(mail.text)
    message.add_alternative(mail.html, subtype="html")
    html_part = message.get_payload()[1]  # type: ignore[index]
    for image in mail.images:
        html_part.add_related(  # type: ignore[union-attr]
            image.png, maintype="image", subtype="png", cid=f"<{image.cid}>"
        )
    return message


def _send_blocking(settings: Settings, message: EmailMessage) -> None:
    assert settings.smtp_host and settings.smtp_username and settings.smtp_password
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        server.starttls(context=context)
        server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        server.send_message(message)


async def send_mail(settings: Settings, mail: Mail) -> None:
    """Send one message. Raises on failure so the outbox retries it."""
    if mail.to.lower().endswith(".invalid"):
        # A counter sale with no email address belongs to a throwaway account; nothing to send.
        return
    message = build_message(settings, mail)
    try:
        await asyncio.to_thread(_send_blocking, settings, message)
    except (smtplib.SMTPException, OSError) as exc:
        raise ServiceUnavailableError(
            "The email could not be sent.", code="EMAIL_SEND_FAILED"
        ) from exc
