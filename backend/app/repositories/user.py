"""User queries.

Everything generic (get, count, paginate, add, delete) comes from
`BaseRepository`; only the lookups specific to users are written here.
"""

from __future__ import annotations

from app.models.user import User, UserRole
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def by_email(self, email: str) -> User | None:
        """Lookup for Google sign-in and for admin/staff login."""
        return await self.find_one(User.email == email.lower())

    async def by_google_sub(self, google_sub: str) -> User | None:
        """Lookup by Google's stable subject identifier.

        Preferred over the email: a Google account's email address can change,
        the subject cannot.
        """
        return await self.find_one(User.google_sub == google_sub)

    async def by_phone(self, phone_e164: str) -> User | None:
        """Lookup by phone number, which is unique when present."""
        return await self.find_one(User.phone_e164 == phone_e164)

    async def email_taken(self, email: str) -> bool:
        return await self.exists(User.email == email.lower())

    async def count_by_role(self, role: UserRole) -> int:
        return await self.count(User.role == role)
