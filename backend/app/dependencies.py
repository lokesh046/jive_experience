"""Shared FastAPI dependencies.

The seam between the routes and everything behind them. `app/api/` holds only
routes; all wiring — sessions, settings, service construction, identity, role
guards and rate limits — lives here.

Layering:

    api ──▶ dependencies ──▶ services ──▶ repositories ──▶ models
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.pagination import PageParams
from app.core.rate_limit import RateLimiter, client_ip
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.repositories.user import UserRepository
from app.services.audit import AuditService
from app.services.auth import AuthService, RequestContext
from app.services.booking import BookingService
from app.services.cache import CatalogueCache
from app.services.catalogue import CatalogueService
from app.services.google_oauth import GoogleOAuthClient
from app.services.inventory import InventoryService
from app.services.leads import LeadService
from app.services.outbox import OutboxService
from app.services.payment import PaymentService
from app.services.payment_provider import PaymentProvider, get_payment_provider
from app.services.promo import PromoService
from app.services.refund import RefundService
from app.services.reports import ReportService
from app.services.settings import SettingsService
from app.services.staff import StaffService
from app.services.ticket import TicketService
from app.services.user import UserService
from app.services.waitlist import WaitlistService

logger = structlog.get_logger(__name__)


# ------------------------------------------------------------ infrastructure ---


def get_app_settings(request: Request) -> Settings:
    """Settings of the running application instance."""
    settings: Settings = request.app.state.settings
    return settings


DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
RedisClient = Annotated[Redis, Depends(get_redis)]
Pagination = Annotated[PageParams, Depends()]


def get_request_context(request: Request) -> RequestContext:
    """Caller IP and user agent, recorded against new sessions."""
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:400] or None,
    )


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


# ------------------------------------------------------------------ services ---

_google_client: GoogleOAuthClient | None = None


def get_google_client(settings: AppSettings) -> GoogleOAuthClient:
    """Process-wide Google client, so the JWKS cache is shared."""
    global _google_client
    if _google_client is None:
        _google_client = GoogleOAuthClient(settings)
    return _google_client


def set_google_client(client: GoogleOAuthClient | None) -> None:
    """Replace the client. Used by tests to inject a stub."""
    global _google_client
    _google_client = client


def get_auth_service(
    session: DbSession,
    settings: AppSettings,
    redis: RedisClient,
    google: Annotated[GoogleOAuthClient, Depends(get_google_client)],
) -> AuthService:
    return AuthService(session, settings, google, redis)


def get_user_service(session: DbSession, settings: AppSettings) -> UserService:
    return UserService(session, settings)


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(session)


def get_cache(redis: RedisClient) -> CatalogueCache:
    return CatalogueCache(redis)


CacheDep = Annotated[CatalogueCache, Depends(get_cache)]


def get_payment_adapter(settings: AppSettings) -> PaymentProvider:
    """The configured gateway adapter.

    Until a provider is chosen this is the refusing default, which fails
    loudly rather than pretending a payment succeeded.
    """
    return get_payment_provider(settings.payment_provider)


PaymentProviderDep = Annotated[PaymentProvider, Depends(get_payment_adapter)]


def get_catalogue_service(session: DbSession, cache: CacheDep) -> CatalogueService:
    return CatalogueService(session, cache)


def get_settings_service(session: DbSession, cache: CacheDep) -> SettingsService:
    return SettingsService(session, cache)


def get_lead_service(
    session: DbSession, outbox: Annotated[OutboxService, Depends(get_outbox_service)]
) -> LeadService:
    return LeadService(session, outbox)


def get_waitlist_service(
    session: DbSession, outbox: Annotated[OutboxService, Depends(get_outbox_service)]
) -> WaitlistService:
    return WaitlistService(session, outbox)


def get_promo_service(session: DbSession) -> PromoService:
    return PromoService(session)


def get_outbox_service(session: DbSession) -> OutboxService:
    return OutboxService(session)


def get_inventory_service(session: DbSession, settings: AppSettings) -> InventoryService:
    return InventoryService(session, settings.reservation_hold_seconds)


def get_booking_service(
    session: DbSession,
    settings: AppSettings,
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
    outbox: Annotated[OutboxService, Depends(get_outbox_service)],
) -> BookingService:
    return BookingService(session, settings, inventory, outbox)


def get_refund_service(
    session: DbSession,
    settings: AppSettings,
    provider: PaymentProviderDep,
    outbox: Annotated[OutboxService, Depends(get_outbox_service)],
) -> RefundService:
    return RefundService(session, settings, provider, outbox)


def get_payment_service(
    session: DbSession,
    settings: AppSettings,
    provider: PaymentProviderDep,
    bookings: Annotated[BookingService, Depends(get_booking_service)],
    refunds: Annotated[RefundService, Depends(get_refund_service)],
) -> PaymentService:
    return PaymentService(session, settings, provider, bookings, refunds)


def get_ticket_service(
    session: DbSession,
    outbox: Annotated[OutboxService, Depends(get_outbox_service)],
) -> TicketService:
    return TicketService(session, outbox)


def get_report_service(session: DbSession, settings: AppSettings) -> ReportService:
    return ReportService(session, settings)


def get_staff_service(session: DbSession) -> StaffService:
    return StaffService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
CatalogueServiceDep = Annotated[CatalogueService, Depends(get_catalogue_service)]
InventoryServiceDep = Annotated[InventoryService, Depends(get_inventory_service)]
BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
RefundServiceDep = Annotated[RefundService, Depends(get_refund_service)]
TicketServiceDep = Annotated[TicketService, Depends(get_ticket_service)]
StaffServiceDep = Annotated[StaffService, Depends(get_staff_service)]
ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
OutboxServiceDep = Annotated[OutboxService, Depends(get_outbox_service)]
LeadServiceDep = Annotated[LeadService, Depends(get_lead_service)]
WaitlistServiceDep = Annotated[WaitlistService, Depends(get_waitlist_service)]
PromoServiceDep = Annotated[PromoService, Depends(get_promo_service)]
SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]


# ------------------------------------------------------------------- identity ---

# auto_error=False so a missing header produces our own error envelope rather
# than Starlette's bare 403.
bearer_scheme = HTTPBearer(auto_error=False, description="Backend-issued access token")
BearerToken = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def get_current_user(
    credentials: BearerToken,
    session: DbSession,
    settings: AppSettings,
) -> User:
    """Resolve the caller from the bearer access token.

    The account is re-read from the database on every request rather than
    trusted from the token's claims. That one row answers every question that
    must be current — does the account still exist, is it still active, what
    role does it have now, and has the session been revoked — so a suspension
    or a "sign out everywhere" takes effect on the very next request instead
    of whenever the access token happens to expire.

    It costs one indexed primary-key lookup, and no second query: checking the
    session against `refresh_tokens` instead would add a round trip to every
    authenticated call.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError(
            "Authentication required.",
            code="UNAUTHENTICATED",
            details={"scheme": "bearer"},
        )

    claims = decode_access_token(credentials.credentials, settings=settings)

    user = await UserRepository(session).get(claims.user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.", code="ACCOUNT_NOT_FOUND")
    if user.status is UserStatus.SUSPENDED:
        raise PermissionDeniedError("This account has been suspended.", code="ACCOUNT_SUSPENDED")
    if user.status is not UserStatus.ACTIVE:
        raise AuthenticationError("This account is no longer active.", code="ACCOUNT_DEACTIVATED")

    # Revocation. A stateless token cannot be withdrawn, so every token issued
    # before the account's cutoff is refused instead. "Sign out everywhere",
    # suspension and a role change all set that cutoff, which makes them take
    # effect on the next request rather than whenever the token expires.
    #
    # Free: the user row is already loaded for the status checks above.
    # Looking the session up in `refresh_tokens` instead would add a round
    # trip to every authenticated request.
    if user.sessions_valid_from and claims.issued_at < user.sessions_valid_from:
        logger.info("revoked_session_rejected", user_id=str(user.id))
        raise AuthenticationError(
            "This session has been signed out. Please sign in again.",
            code="SESSION_REVOKED",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Dependency factory restricting an endpoint to the given roles."""
    allowed = frozenset(roles)

    async def _guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            logger.info(
                "permission_denied",
                user_id=str(user.id),
                role=user.role.value,
                required=[role.value for role in sorted(allowed)],
            )
            raise PermissionDeniedError(
                "You do not have permission to perform this action.",
                details={"required_role": [role.value for role in sorted(allowed)]},
            )
        return user

    return _guard


# The guards every router uses.
RequireAdmin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
RequireStaff = Annotated[User, Depends(require_roles(UserRole.EVENT_STAFF))]
RequireCustomer = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]
RequireAdminOrStaff = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.EVENT_STAFF))]


# ---------------------------------------------------------------- rate limits ---

# Authentication limits fail **closed**: if Redis is unavailable the request is
# refused rather than leaving an unmetered window for credential stuffing or
# automated account creation. Browse endpoints fail open instead, so a cache
# outage cannot take the public site down.
_settings = get_settings()

OAuthRateLimit = Depends(
    RateLimiter(
        times=_settings.oauth_rate_limit_times,
        seconds=_settings.oauth_rate_limit_seconds,
        scope="auth:oauth",
        fail_open=False,
    )
)
# Public forms: a few submissions an hour per address is plenty for a person and not for a bot.
FormRateLimit = Depends(
    RateLimiter(times=6, seconds=3600, scope="public:form", identifier=client_ip, fail_open=True)
)
RefreshRateLimit = Depends(
    RateLimiter(times=60, seconds=60, scope="auth:refresh", identifier=client_ip, fail_open=False)
)
