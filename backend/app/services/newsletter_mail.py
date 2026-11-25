"""The newsletter email itself: plain text in, a tidy HTML message out."""

from __future__ import annotations

from html import escape
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.mailer import Mail
from app.models.event import Event
from app.models.newsletter_campaign import NewsletterCampaign


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]


def build_campaign_mail(
    settings: Settings,
    campaign: NewsletterCampaign,
    event: Event | None,
    *,
    to: str,
    unsubscribe_url: str | None,
    test: bool = False,
) -> Mail:
    """One subscriber's copy. The unsubscribe link is theirs alone, and is in the headers too."""
    base = settings.public_site_url.rstrip("/")
    subject = f"[Test] {campaign.subject}" if test else campaign.subject

    paragraphs = _paragraphs(campaign.body)
    html_body = "".join(
        f"<p style='margin:0 0 16px'>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs
    )
    text_parts = list(paragraphs)

    card = ""
    link = campaign.button_url
    label = campaign.button_label
    if event is not None:
        zone = ZoneInfo(event.timezone or settings.default_timezone)
        when = event.starts_at.astimezone(zone).strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ")
        page = f"{base}/events/{event.slug}"
        picture = event.thumbnail_image_url or event.banner_image_url
        image = (
            f"<img src='{escape(picture)}' alt='' width='520' style='width:100%;max-width:520px;"
            "height:auto;border-radius:14px;display:block;margin:0 0 12px'>"
            if picture and picture.startswith("https://")
            else ""
        )
        card = (
            "<div style='margin:8px 0 20px;padding:16px;border:1px solid #e5e5e5;"
            "border-radius:18px'>"
            f"{image}<p style='margin:0;font-size:20px;font-weight:600'>{escape(event.title)}</p>"
            f"<p style='margin:4px 0 0;color:#555'>{escape(when)}</p></div>"
        )
        text_parts.append(f"{event.title}\n{when}")
        link = link or page
        label = label or "Get tickets"

    button = ""
    if link and label:
        button = (
            f"<p style='margin:8px 0 24px'><a href='{escape(link)}' style='display:inline-block;"
            "padding:13px 26px;background:#111;color:#fff;border-radius:999px;"
            f"text-decoration:none;font-weight:600'>{escape(label)}</a></p>"
        )
        text_parts.append(f"{label}: {link}")

    footer_html = footer_text = ""
    headers: dict[str, str] = {}
    if unsubscribe_url:
        footer_html = (
            "<p style='margin:28px 0 0;color:#777;font-size:12px'>You get this because you joined "
            f"the JIVE list. <a href='{escape(unsubscribe_url)}'>Unsubscribe</a>.</p>"
        )
        footer_text = (
            f"\n\nYou get this because you joined the JIVE list. Unsubscribe: {unsubscribe_url}"
        )
        headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"

    html = (
        "<div style='font:16px/1.55 Arial,sans-serif;color:#111;max-width:560px;margin:0 auto;"
        "padding:24px'><p style='margin:0 0 20px;font:26px Georgia,serif'>JIVE</p>"
        f"{html_body}{card}{button}{footer_html}</div>"
    )
    text = "\n\n".join(text_parts) + footer_text
    return Mail(to=to, subject=subject, text=text, html=html, headers=headers)
