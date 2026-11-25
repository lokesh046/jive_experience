"""Plain names for the background jobs, so a person reading the jobs page knows what each is."""

from __future__ import annotations

JOBS: dict[str, str] = {
    "payment.captured": "Finish a captured payment",
    "booking.confirmed": "Issue tickets",
    "tickets.issued": "Email the tickets",
    "booking.cancelled": "Cancellation email",
    "booking.reminder": "Event reminder",
    "booking.abandoned": "Left-before-paying email",
    "refund.process": "Send a refund to the payment provider",
    "refund.completed": "Refund email",
    "event.cancelled": "Refund an event's bookings",
    "enquiry.received": "New enquiry emails",
    "newsletter.subscribed": "Newsletter welcome email",
    "newsletter.send": "Newsletter email",
    "waitlist.available": "Waitlist email",
    "notification.email": "Alert email",
    "notification.push": "Browser notification",
}

SCHEDULES: dict[str, str] = {
    "release_holds": "Return expired ticket holds to sale",
    "expire_bookings": "Close bookings whose hold ran out",
    "recover_locks": "Recover jobs a stopped worker left behind",
    "reminders": "Queue event reminder emails",
    "abandoned": "Queue left-before-paying emails",
    "doors": "Tell gate staff doors are opening",
    "waitlist": "Tell the waitlist when tickets return",
    "reconcile": "Check payments and refunds with the provider",
    "cleanup": "Clear old notifications and finished jobs",
}


def job_label(topic: str) -> str:
    return JOBS.get(topic, topic)
