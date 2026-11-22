"""Model registry.

Alembic autogenerate only sees tables that have been imported. Every model
module must be imported here — this is the single place to register a new one.

Import order matters only for readability; SQLAlchemy resolves relationships
by class name once every model is registered.
"""

from __future__ import annotations

from app.models.audit_log import AuditLog  # noqa: F401
from app.models.base import Base
from app.models.commerce import (  # noqa: F401
    Booking,
    BookingItem,
    Payment,
    PaymentWebhookEvent,
    Refund,
    TicketReservation,
)
from app.models.event import Event, EventPerformer, TicketCategory  # noqa: F401
from app.models.fulfilment import (  # noqa: F401
    OutboxMessage,
    StaffEventAssignment,
    Ticket,
    TicketCheckin,
)
from app.models.lead import Enquiry, NewsletterSubscriber  # noqa: F401
from app.models.promo import PromoCode  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.site_setting import SiteSetting  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.venue import Venue  # noqa: F401
from app.models.waitlist import WaitlistEntry  # noqa: F401

__all__ = ["Base"]
