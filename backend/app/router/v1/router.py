"""Aggregated v1 router.

Every v1 route is mounted here, so the public surface is described in exactly
one place. The `/api/v1` URL prefix is applied in `app/main.py` from settings;
a future v2 becomes `app/router/v2/` beside this package.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.router.v1 import (
    admin_archive,
    admin_artists,
    admin_catalogue,
    admin_commerce,
    admin_leads,
    admin_newsletters,
    admin_promos,
    admin_reports,
    admin_settings,
    archive,
    artists,
    auth,
    bookings,
    box_office,
    events,
    leads,
    notifications,
    scanner,
    system,
    users,
)

api_router = APIRouter()

# Public and customer surfaces.
api_router.include_router(system.router, prefix="/system")
api_router.include_router(auth.router, prefix="/auth")
api_router.include_router(users.router, prefix="/users")
api_router.include_router(events.router, prefix="/events")
api_router.include_router(bookings.router, prefix="/bookings")
api_router.include_router(bookings.tickets_router, prefix="/tickets")
api_router.include_router(bookings.webhook_router, prefix="/payments")
api_router.include_router(leads.router)
api_router.include_router(artists.router)
api_router.include_router(notifications.router, prefix="/notifications")
api_router.include_router(archive.router)

# Event staff scanner.
api_router.include_router(scanner.router, prefix="/scanner")
api_router.include_router(box_office.router, prefix="/box-office")

# Administrator surfaces.
api_router.include_router(admin_catalogue.router, prefix="/admin")
api_router.include_router(admin_commerce.router, prefix="/admin")
api_router.include_router(admin_reports.router, prefix="/admin")
api_router.include_router(admin_leads.router, prefix="/admin")
api_router.include_router(admin_promos.router, prefix="/admin")
api_router.include_router(admin_artists.router, prefix="/admin")
api_router.include_router(admin_archive.router, prefix="/admin")
api_router.include_router(admin_newsletters.router, prefix="/admin")
api_router.include_router(admin_settings.router, prefix="/admin")

# Still to come:
#   Phase 6  services, artists, portfolio, enquiries, notifications, reports
