"""The groups of notifications, who sees each, and how each is delivered by default.

A *category* is what a person switches on or off. The in-app bell is always available; email
is a second channel that either replaces nothing (customer emails such as tickets and refunds
always go out and are not in this list) or is the alert email an administrator can turn on.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.user import UserRole


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    label: str
    description: str
    roles: tuple[UserRole, ...]
    in_app_default: bool = True
    email_default: bool = False
    # False: the email for this group is not controlled here (it is always sent, or never).
    email_choice: bool = False
    # True: this system sends an alert email for the group (administrators and gate staff).
    alert_email: bool = False


CATEGORIES: tuple[Category, ...] = (
    Category(
        "bookings",
        "Your bookings",
        "Tickets ready, cancellations and refunds. Ticket and refund emails always go out.",
        (UserRole.CUSTOMER,),
    ),
    Category(
        "reminders",
        "Event reminders",
        "A nudge before a night you have tickets for.",
        (UserRole.CUSTOMER,),
        email_default=True,
        email_choice=True,
    ),
    Category(
        "waitlist",
        "Waitlist",
        "When tickets you were waiting for come back on sale.",
        (UserRole.CUSTOMER,),
        email_default=True,
        email_choice=True,
    ),
    Category(
        "payments",
        "Payments and refunds",
        "A payment or refund that failed or needed the safety net. These need a person.",
        (UserRole.ADMIN,),
        email_default=True,
        email_choice=True,
        alert_email=True,
    ),
    Category(
        "sales",
        "Sales",
        "A night nearly full or sold out.",
        (UserRole.ADMIN,),
        email_choice=True,
        alert_email=True,
    ),
    Category(
        "enquiries",
        "Enquiries",
        "A new private-booking enquiry.",
        (UserRole.ADMIN,),
        email_choice=True,
        alert_email=True,
    ),
    Category(
        "system",
        "System",
        "Something behind the scenes failed after several tries, like an email that did not send.",
        (UserRole.ADMIN,),
        email_default=True,
        email_choice=True,
        alert_email=True,
    ),
    Category(
        "gate",
        "At the gate",
        "Doors opening soon on a night you are working, and tickets that should not get in.",
        (UserRole.EVENT_STAFF, UserRole.ADMIN),
        email_choice=True,
        alert_email=True,
    ),
)

BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}
CHANNELS = ("in_app", "email")


def categories_for(role: UserRole) -> list[Category]:
    return [c for c in CATEGORIES if role in c.roles]
