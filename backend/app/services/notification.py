"""Customer emails, sent from the outbox worker."""

from __future__ import annotations

import asyncio
import io
import re
import uuid
from datetime import UTC, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import qrcode
import structlog
from qrcode.constants import ERROR_CORRECT_M
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.mailer import InlineImage, Mail
from app.core.money import format_inr
from app.models.commerce import Booking, BookingStatus
from app.models.event import Event, EventStatus
from app.models.fulfilment import TicketStatus
from app.models.user import User
from app.models.waitlist import WaitlistStatus
from app.repositories.catalogue import EventRepository
from app.repositories.commerce import BookingRepository, RefundRepository
from app.repositories.fulfilment import TicketRepository
from app.repositories.lead import EnquiryRepository, SubscriberRepository
from app.repositories.newsletter import CampaignRepository
from app.repositories.user import UserRepository
from app.repositories.waitlist import WaitlistRepository
from app.services.abandoned import abandoned_emails_enabled
from app.services.newsletter_mail import build_campaign_mail
from app.services.outbox import TOPIC_BOOKING_REMINDER
from app.services.ticket import TicketService

logger = structlog.get_logger(__name__)


def qr_png(token: str) -> bytes:
    image = qrcode.make(token, error_correction=ERROR_CORRECT_M, box_size=8, border=2)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


PREMIUM_NAME = re.compile(r"vip|premium|platinum|gold|black|elite|royal", re.IGNORECASE)


def is_premium_type(name: str, price_paise: int, all_prices: list[int]) -> bool:
    """VIP-style name, or the top-priced type of an event that has several.

    The same rule the website uses to give a ticket its premium look.
    """
    if PREMIUM_NAME.search(name):
        return True
    return len(all_prices) > 1 and price_paise > 0 and price_paise == max(all_prices)


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
        self.enquiries = EnquiryRepository(session)
        self.subscribers = SubscriberRepository(session)
        self.waitlist = WaitlistRepository(session)
        self.campaigns = CampaignRepository(session)

    async def send_tickets(self, booking_id: uuid.UUID) -> bool:
        """Email the tickets for a booking. Returns False when email is off."""
        return await self._send_ticket_mail(booking_id, reminder=False)

    async def send_reminder(self, booking_id: uuid.UUID) -> bool:
        """Remind a customer the event is coming up, with their tickets again.

        Sent only if the booking is still confirmed and still has live tickets:
        a booking cancelled after the reminder was queued gets nothing.
        """
        return await self._send_ticket_mail(booking_id, reminder=True)

    async def enqueue_due_reminders(self, now: datetime) -> int:
        """Queue a reminder for every booking now inside the reminder window."""
        horizon = timedelta(hours=self.settings.reminder_hours_before)
        due = await self.bookings.due_for_reminder(now=now, horizon=horizon)
        for booking_id in due:
            await self.tickets.outbox.enqueue(
                topic=TOPIC_BOOKING_REMINDER,
                payload={"booking_id": str(booking_id)},
                dedup_key=f"booking.reminder:{booking_id}",
            )
        if due:
            await self.session.commit()
        return len(due)

    async def _send_ticket_mail(self, booking_id: uuid.UUID, *, reminder: bool) -> bool:
        kind = "reminder" if reminder else "tickets"
        if not self.settings.email_configured:
            logger.warning(f"email_not_configured_skipping_{kind}", booking_id=str(booking_id))
            return False

        booking = await self.bookings.get(booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.", code="BOOKING_NOT_FOUND")
        user = await self.users.get(booking.user_id)
        event = await self.events.get(booking.event_id)
        if user is None or event is None:
            raise NotFoundError("Booking details not found.", code="BOOKING_NOT_FOUND")
        rows = list(await self.ticket_rows.for_booking(booking.id))
        if reminder:
            if booking.status is not BookingStatus.CONFIRMED:
                return False
            rows = [row for row in rows if row.status is TicketStatus.ISSUED]
        if not rows:
            return False

        # Explicit, so a venue that is not loaded yet cannot trigger a lazy load here.
        await self.session.refresh(event, attribute_names=["venue", "ticket_categories"])
        items = {item.ticket_category_id: item for item in await self.bookings.items(booking.id)}
        all_prices = [c.price_paise for c in event.ticket_categories]
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
            item = items.get(ticket.ticket_category_id)
            kind = escape(item.category_name) if item else "Ticket"
            img = (
                f'<img src="cid:{cid}" width="200" height="200" '
                f'alt="Entry code {serial}" style="display:block">'
            )
            if item and is_premium_type(item.category_name, item.unit_price_paise, all_prices):
                # The warm orange of the website's premium ticket, in plain email-safe HTML.
                blocks.append(
                    '<div style="margin:0 0 24px;padding:22px;border-radius:18px;'
                    'background:#e5702f;color:#5a3520;text-align:center">'
                    '<div style="font:600 12px sans-serif;letter-spacing:.14em">'
                    "JIVE PRESENTS</div>"
                    f'<div style="font:700 46px/1.05 sans-serif;margin:6px 0 14px">'
                    f"{kind.upper()}</div>"
                    '<div style="display:inline-block;background:#fff;padding:12px;'
                    f'border-radius:14px">{img}</div>'
                    f'<div style="font:600 13px sans-serif;margin-top:12px">'
                    f"Ticket {index} of {len(rows)} · {serial}</div></div>"
                )
            else:
                blocks.append(
                    f'<div style="{card}">'
                    f'<div style="font:600 14px sans-serif;margin-bottom:8px">'
                    f"{kind} · ticket {index} of {len(rows)} · {serial}</div>"
                    f'<div style="display:inline-block">{img}</div></div>'
                )
            lines.append(f"Ticket {index} of {len(rows)}: {ticket.serial}")

        body_style = (
            "font:16px/1.5 -apple-system,Segoe UI,sans-serif;color:#111;max-width:520px;margin:auto"
        )
        if reminder:
            lead_text = f"{event.title} is coming up soon."
            lead_html = f"<b>{escape(event.title)}</b> is coming up soon."
            subject = f"Reminder: {event.title} is on {when}"
        else:
            lead_text = f"you are going to {event.title}."
            lead_html = f"you are going to <b>{escape(event.title)}</b>."
            subject = f"Your tickets for {event.title}"
        directions = (
            f'<p><a href="{escape(event.venue.map_url)}">Get directions</a></p>'
            if event.venue.map_url
            else ""
        )
        html = (
            f'<div style="{body_style}">'
            f"<p>Hi {escape(name)}, {lead_html}</p>"
            f"<p>{escape(when)}<br>{escape(venue)}<br>"
            f"Booking <b>{escape(booking.reference)}</b></p>"
            f"{''.join(blocks)}"
            "<p>Show each code at the gate. Every ticket works once.</p>"
            f"{directions}"
            f'<p><a href="{escape(link)}">Open your booking</a></p></div>'
        )
        text = (
            f"Hi {name}, {lead_text}\n{when}\n{venue}\n"
            f"Booking {booking.reference}\n\n" + "\n".join(lines) + "\n\n"
            f"Your QR codes are in the HTML version of this email, and always at:\n{link}\n"
        )
        mail = Mail(
            to=user.email,
            subject=subject,
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

    # ------------------------------------------------------------- leads ---

    async def send_enquiry(self, enquiry_id: uuid.UUID) -> bool:
        """Tell the team about a new enquiry, and let the sender know it arrived."""
        if not self.settings.email_configured:
            logger.warning("email_not_configured_skipping_enquiry", enquiry_id=str(enquiry_id))
            return False
        enquiry = await self.enquiries.get(enquiry_id)
        if enquiry is None:
            raise NotFoundError("Enquiry not found.", code="ENQUIRY_NOT_FOUND")

        cell = "padding:4px 16px 4px 0;color:#666"

        def row(label: str, value: object) -> str:
            return f"<tr><td style='{cell}'>{label}</td><td>{escape(str(value))}</td></tr>"

        details = "".join(
            [
                row("Name", enquiry.name),
                row("Email", enquiry.email),
                row("Phone", enquiry.phone or "—"),
                row("Date wanted", enquiry.event_date.isoformat() if enquiry.event_date else "—"),
                row("Guests", enquiry.guests or "—"),
            ]
        )
        body = escape(enquiry.message).replace("\n", "<br>")
        inbox = f"{self.settings.public_site_url.rstrip('/')}/admin/inbox"
        team = Mail(
            to=self.settings.enquiry_notify_email or str(self.settings.mail_from),
            subject=f"New private-booking enquiry from {enquiry.name}",
            text=(
                f"{enquiry.name} <{enquiry.email}> sent an enquiry.\n\n{enquiry.message}\n\n"
                f"Open it in the admin inbox: {inbox}\n"
            ),
            html=(
                f"<div style='font:16px/1.5 sans-serif;max-width:560px'><p>New enquiry.</p>"
                f"<table>{details}</table><p style='margin-top:16px'>{body}</p>"
                f"<p><a href='{escape(inbox)}'>Open the admin inbox</a></p></div>"
            ),
        )
        await mailer.send_mail(self.settings, team)
        thanks = Mail(
            to=enquiry.email,
            subject="We received your enquiry",
            text=(
                f"Hi {enquiry.name.split(' ')[0]}, thank you for getting in touch. "
                "We have your enquiry and will reply by email soon.\n"
            ),
            html=(
                f"<div style='font:16px/1.5 sans-serif;max-width:520px'>"
                f"<p>Hi {escape(enquiry.name.split(' ')[0])}, thank you for getting in touch.</p>"
                "<p>We have your enquiry and will reply by email soon.</p></div>"
            ),
        )
        await mailer.send_mail(self.settings, thanks)
        logger.info("enquiry_emails_sent", enquiry_id=str(enquiry.id))
        return True

    async def send_newsletter_welcome(self, subscriber_id: uuid.UUID) -> bool:
        if not self.settings.email_configured:
            logger.warning(
                "email_not_configured_skipping_welcome", subscriber_id=str(subscriber_id)
            )
            return False
        subscriber = await self.subscribers.get(subscriber_id)
        if subscriber is None or not subscriber.subscribed:
            return False
        base = self.settings.public_site_url.rstrip("/")
        link = f"{base}/unsubscribe?token={subscriber.unsubscribe_token}"
        mail = Mail(
            to=subscriber.email,
            subject="You are on the JIVE list",
            text=(
                "You are subscribed to announcements about new JIVE nights. "
                f"If this was not you, or you change your mind, unsubscribe here: {link}\n"
            ),
            html=(
                "<div style='font:16px/1.5 sans-serif;max-width:520px'>"
                "<p>You are subscribed to announcements about new JIVE nights.</p>"
                f"<p style='color:#666'>If this was not you, or you change your mind, "
                f"<a href='{escape(link)}'>unsubscribe here</a>.</p></div>"
            ),
        )
        await mailer.send_mail(self.settings, mail)
        logger.info("newsletter_welcome_sent", subscriber_id=str(subscriber.id))
        return True

    async def send_campaign(self, campaign_id: uuid.UUID, subscriber_id: uuid.UUID) -> bool:
        """One subscriber's copy of a newsletter issue."""
        if not self.settings.email_configured:
            logger.warning("email_not_configured_skipping_newsletter", campaign_id=str(campaign_id))
            return False
        campaign = await self.campaigns.get(campaign_id)
        subscriber = await self.subscribers.get(subscriber_id)
        # Someone who unsubscribed after the issue was queued must not get it.
        if campaign is None or subscriber is None or not subscriber.subscribed:
            return False
        event = await self.events.get(campaign.event_id) if campaign.event_id else None
        base = self.settings.public_site_url.rstrip("/")
        mail = build_campaign_mail(
            self.settings,
            campaign,
            event,
            to=subscriber.email,
            unsubscribe_url=f"{base}/unsubscribe?token={subscriber.unsubscribe_token}",
        )
        await mailer.send_mail(self.settings, mail)
        await self.campaigns.count_delivered(campaign.id)
        return True

    async def send_abandoned(self, booking_id: uuid.UUID) -> bool:
        """ "You left before paying": one email, only if coming back would still work."""
        if not self.settings.email_configured:
            logger.warning("email_not_configured_skipping_abandoned", booking_id=str(booking_id))
            return False
        booking = await self.bookings.get(booking_id)
        if booking is None or booking.status is not BookingStatus.EXPIRED:
            return False
        user = await self.users.get(booking.user_id)
        event = await self.events.get(booking.event_id)
        if user is None or event is None or user.email.endswith(".invalid"):
            return False
        if not await abandoned_emails_enabled(self.session):
            return False
        now = datetime.now(UTC)
        if (
            event.status is not EventStatus.PUBLISHED
            or event.starts_at <= now
            or (event.sale_ends_at is not None and event.sale_ends_at <= now)
            or (event.sale_starts_at is not None and event.sale_starts_at > now)
        ):
            return False
        # They may have bought in the meantime, from this booking's twin or at the counter.
        bought = await self.session.scalar(
            select(Booking.id)
            .where(
                Booking.user_id == booking.user_id,
                Booking.event_id == booking.event_id,
                Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PARTIALLY_REFUNDED]),
            )
            .limit(1)
        )
        if bought is not None:
            return False

        await self.session.refresh(event, attribute_names=["venue", "ticket_categories"])
        wanted = {c.id: c for c in event.ticket_categories}
        lines: list[str] = []
        for item in await self.bookings.items(booking.id):
            category = wanted.get(item.ticket_category_id)
            if category is None or not category.is_active or category.available < item.quantity:
                continue
            lines.append(
                f"{item.quantity} x {category.name} ({format_inr(category.price_paise)} each)"
            )
        if not lines:
            return False  # what they wanted has sold out: nothing useful to say

        zone = ZoneInfo(event.timezone or self.settings.default_timezone)
        when = event.starts_at.astimezone(zone).strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ")
        page = f"{self.settings.public_site_url.rstrip('/')}/events/{event.slug}#tickets"
        name = (user.full_name or "").split(" ")[0] or "there"
        title = escape(event.title)
        mail = Mail(
            to=user.email,
            subject=f"Still thinking about {event.title}?",
            text=(
                f"Hi {name}, you started booking {event.title} ({when}) but did not finish.\n\n"
                + "\n".join(lines)
                + f"\n\nTickets are first come, first served and we cannot hold them: {page}\n"
            ),
            html=(
                "<div style='font:16px/1.55 Arial,sans-serif;max-width:520px;color:#111'>"
                f"<p>Hi {escape(name)}, you started booking <b>{title}</b> "
                f"({escape(when)}) but did not finish.</p><ul>"
                + "".join(f"<li>{escape(line)}</li>" for line in lines)
                + "</ul><p>Tickets are first come, first served and we cannot hold them.</p>"
                f"<p><a href='{escape(page)}' style='display:inline-block;padding:12px 22px;"
                "background:#111;color:#fff;border-radius:999px;text-decoration:none'>"
                "Pick up where you left off</a></p>"
                "<p style='color:#777;font-size:12px'>One reminder only, because you started a "
                "booking on our site.</p></div>"
            ),
        )
        await mailer.send_mail(self.settings, mail)
        logger.info("abandoned_email_sent", booking_id=str(booking.id))
        return True

    async def send_waitlist_available(self, entry_id: uuid.UUID) -> bool:
        """Tell someone on the waitlist that tickets are back on sale."""
        if not self.settings.email_configured:
            logger.warning("email_not_configured_skipping_waitlist", id=str(entry_id))
            return False
        entry = await self.waitlist.get(entry_id)
        if entry is None or entry.status is not WaitlistStatus.NOTIFIED:
            return False
        event = await self.events.get(entry.event_id)
        if event is None:
            return False
        await self.session.refresh(event, attribute_names=["venue"])
        zone = ZoneInfo(event.timezone or self.settings.default_timezone)
        when = event.starts_at.astimezone(zone).strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ")
        base = self.settings.public_site_url.rstrip("/")
        page = f"{base}/events/{event.slug}"
        leave = f"{base}/waitlist/leave?token={entry.leave_token}"
        title = escape(event.title)
        mail = Mail(
            to=entry.email,
            subject=f"Tickets are available again: {event.title}",
            text=(
                f"Good news: tickets for {event.title} ({when}) are available again.\n"
                f"They are first come, first served and we cannot hold them: {page}\n\n"
                f"No longer interested? Leave the waitlist: {leave}\n"
            ),
            html=(
                "<div style='font:16px/1.5 sans-serif;max-width:520px'>"
                f"<p>Good news: tickets for <b>{title}</b> ({escape(when)}) "
                "are available again.</p>"
                "<p>They are first come, first served and we cannot hold them.</p>"
                f"<p><a href='{escape(page)}' style='display:inline-block;padding:12px 22px;"
                "background:#111;color:#fff;border-radius:999px;text-decoration:none'>"
                "Get tickets</a></p>"
                f"<p style='color:#666;font-size:13px'>No longer interested? "
                f"<a href='{escape(leave)}'>Leave the waitlist</a>.</p></div>"
            ),
        )
        await mailer.send_mail(self.settings, mail)
        logger.info("waitlist_email_sent", entry_id=str(entry.id))
        return True
