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
from app.core.money import format_inr
from app.models.commerce import Booking
from app.models.event import Event, EventStatus
from app.models.user import User
from app.repositories.catalogue import EventRepository
from app.repositories.commerce import BookingRepository, RefundRepository
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
        self.refunds = RefundRepository(session)

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

    # ------------------------------------------------ cancellation & refund ---

    async def _booking_context(self, booking_id: uuid.UUID) -> tuple[Booking, User, Event]:
        booking = await self.bookings.get(booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        user = await self.users.get(booking.user_id)
        event = await self.events.get(booking.event_id)
        if user is None or event is None:
            raise NotFoundError("Booking details not found.", code="BOOKING_NOT_FOUND")
        await self.session.refresh(event, attribute_names=["venue"])
        return booking, user, event

    def _wrap(self, name: str, paragraphs: list[str], link: str, link_text: str) -> str:
        body_style = (
            "font:16px/1.5 -apple-system,Segoe UI,sans-serif;color:#111;max-width:520px;margin:auto"
        )
        inner = "".join(f"<p>{p}</p>" for p in paragraphs)
        return (
            f'<div style="{body_style}"><p>Hi {escape(name)},</p>{inner}'
            f'<p><a href="{escape(link)}">{escape(link_text)}</a></p></div>'
        )

    async def send_cancellation(self, booking_id: uuid.UUID) -> bool:
        """Tell the customer their booking was cancelled."""
        if not self.settings.email_configured:
            logger.warning("email_not_configured_skipping_cancel", booking_id=str(booking_id))
            return False
        booking, user, event = await self._booking_context(booking_id)
        name = (user.full_name or "").split(" ")[0] or "there"
        link = f"{self.settings.public_site_url.rstrip('/')}/tickets/{booking.reference}"
        by_us = event.status is EventStatus.CANCELLED
        what = (
            f"{event.title} has been cancelled."
            if by_us
            else f"Your booking {booking.reference} for {event.title} has been cancelled."
        )
        refund_line = (
            "A refund is being sent to your original payment method." if booking.total_paise else ""
        )
        subject = (
            f"{event.title} has been cancelled"
            if by_us
            else f"Booking {booking.reference} cancelled"
        )
        lines = [what, f"Booking {booking.reference}.", refund_line, "Your tickets no longer work."]
        lines = [line for line in lines if line]
        mail = Mail(
            to=user.email,
            subject=subject,
            text=f"Hi {name},\n\n" + "\n".join(lines) + f"\n\nDetails: {link}\n",
            html=self._wrap(name, [escape(line) for line in lines], link, "View your booking"),
        )
        await mailer.send_mail(self.settings, mail)
        logger.info("cancellation_email_sent", booking_id=str(booking.id))
        return True

    async def send_refund(self, refund_id: uuid.UUID) -> bool:
        """Tell the customer a refund has been sent."""
        if not self.settings.email_configured:
            logger.warning("email_not_configured_skipping_refund", refund_id=str(refund_id))
            return False
        refund = await self.refunds.get(refund_id)
        if refund is None:
            raise NotFoundError("Refund not found.", code="REFUND_NOT_FOUND")
        booking, user, event = await self._booking_context(refund.booking_id)
        name = (user.full_name or "").split(" ")[0] or "there"
        link = f"{self.settings.public_site_url.rstrip('/')}/tickets/{booking.reference}"
        amount = format_inr(refund.amount_paise)
        lines = [
            f"We have refunded {amount} for {event.title} (booking {booking.reference}).",
            "It goes back to the payment method you used. Banks can take a few working days "
            "to show it in your account.",
        ]
        mail = Mail(
            to=user.email,
            subject=f"Your refund of {amount} for {event.title}",
            text=f"Hi {name},\n\n" + "\n".join(lines) + f"\n\nDetails: {link}\n",
            html=self._wrap(name, [escape(line) for line in lines], link, "View your booking"),
        )
        await mailer.send_mail(self.settings, mail)
        logger.info("refund_email_sent", refund_id=str(refund.id))
        return True
