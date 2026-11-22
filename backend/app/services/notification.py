"""Customer emails, sent from the outbox worker."""

from __future__ import annotations

import asyncio
import io
import uuid
from html import escape
from zoneinfo import ZoneInfo

import qrcode
import structlog
from qrcode.constants import ERROR_CORRECT_M
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.mailer import InlineImage, Mail
from app.repositories.catalogue import EventRepository
from app.repositories.commerce import BookingRepository
from app.repositories.fulfilment import TicketRepository
from app.repositories.user import UserRepository
from app.services.ticket import TicketService

logger = structlog.get_logger(__name__)


def qr_png(token: str) -> bytes:
    image = qrcode.make(token, error_correction=ERROR_CORRECT_M, box_size=8, border=2)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class NotificationService:
    def __init__(self, session: AsyncSession, settings: Settings, tickets: TicketService) -> None:
        self.session = session
        self.settings = settings
        self.tickets = tickets
        self.bookings = BookingRepository(session)
        self.events = EventRepository(session)
        self.users = UserRepository(session)
        self.ticket_rows = TicketRepository(session)

    async def send_tickets(self, booking_id: uuid.UUID) -> bool:
        """Email the tickets for a booking. Returns False when email is off."""
        if not self.settings.email_configured:
            logger.warning("email_not_configured_skipping_tickets", booking_id=str(booking_id))
            return False

        booking = await self.bookings.get(booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        user = await self.users.get(booking.user_id)
        event = await self.events.get(booking.event_id)
        if user is None or event is None:
            raise NotFoundError("Booking details not found.", code="BOOKING_NOT_FOUND")
        rows = await self.ticket_rows.for_booking(booking.id)
        if not rows:
            return False

        # Explicit, so a venue that is not loaded yet cannot trigger a lazy load here.
        await self.session.refresh(event, attribute_names=["venue"])
        zone = ZoneInfo(event.timezone or self.settings.default_timezone)
        when = event.starts_at.astimezone(zone).strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ")
        venue = f"{event.venue.name}, {event.venue.city}"
        link = f"{self.settings.public_site_url.rstrip('/')}/tickets/{booking.reference}"
        name = (user.full_name or "").split(" ")[0] or "there"

        images: list[InlineImage] = []
        blocks: list[str] = []
        lines: list[str] = []
        card = (
            "margin:0 0 24px;padding:16px;border:1px solid #ddd;"
            "border-radius:12px;text-align:center"
        )
        for index, ticket in enumerate(rows, start=1):
            cid = f"ticket{index}"
            png = await asyncio.to_thread(qr_png, self.tickets.qr_token_for(ticket))
            images.append(InlineImage(cid=cid, png=png))
            serial = escape(ticket.serial)
            blocks.append(
                f'<div style="{card}">'
                f'<div style="font:600 14px sans-serif;margin-bottom:8px">'
                f"Ticket {index} of {len(rows)} · {serial}</div>"
                f'<img src="cid:{cid}" width="200" height="200" alt="Entry code {serial}">'
                "</div>"
            )
            lines.append(f"Ticket {index} of {len(rows)}: {ticket.serial}")

        body_style = (
            "font:16px/1.5 -apple-system,Segoe UI,sans-serif;color:#111;max-width:520px;margin:auto"
        )
        html = (
            f'<div style="{body_style}">'
            f"<p>Hi {escape(name)}, you are going to <b>{escape(event.title)}</b>.</p>"
            f"<p>{escape(when)}<br>{escape(venue)}<br>"
            f"Booking <b>{escape(booking.reference)}</b></p>"
            f"{''.join(blocks)}"
            "<p>Show each code at the gate. Every ticket works once.</p>"
            f'<p><a href="{escape(link)}">Open your booking</a></p></div>'
        )
        text = (
            f"Hi {name}, you are going to {event.title}.\n{when}\n{venue}\n"
            f"Booking {booking.reference}\n\n" + "\n".join(lines) + "\n\n"
            f"Your QR codes are in the HTML version of this email, and always at:\n{link}\n"
        )
        mail = Mail(
            to=user.email,
            subject=f"Your tickets for {event.title}",
            text=text,
            html=html,
            images=images,
        )
        await mailer.send_mail(self.settings, mail)
        logger.info("tickets_email_sent", booking_id=str(booking.id), tickets=len(rows))
        return True
