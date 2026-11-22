from pydantic import SecretStr

from app.core.config import Settings
from app.core.mailer import InlineImage, Mail, build_message


def test_message_has_text_html_and_inline_images() -> None:
    settings = Settings(
        smtp_host="smtp.gmail.com",
        smtp_username="a@gmail.com",
        smtp_password=SecretStr("x"),
        mail_from="a@gmail.com",
    )
    mail = Mail(
        to="c@example.com",
        subject="Tickets",
        text="plain",
        html='<img src="cid:t1">',
        images=[InlineImage(cid="t1", png=b"\x89PNG\r\n\x1a\n")],
    )
    message = build_message(settings, mail)
    assert message["To"] == "c@example.com"
    assert "JIVE Events" in message["From"] and "a@gmail.com" in message["From"]
    kinds = [part.get_content_type() for part in message.walk()]
    assert "text/plain" in kinds and "text/html" in kinds and "image/png" in kinds
    image = next(p for p in message.walk() if p.get_content_type() == "image/png")
    assert image["Content-ID"] == "<t1>"


def test_email_is_off_until_every_smtp_setting_is_present() -> None:
    assert Settings().email_configured is False
    assert (
        Settings(smtp_host="h", smtp_username="u", smtp_password=SecretStr("p")).email_configured
        is False
    )
