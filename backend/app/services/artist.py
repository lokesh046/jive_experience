"""Artists: the company's own list, shown on the homepage in an order the admin chooses."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, NotFoundError
from app.models.artist import Artist
from app.models.user import User
from app.repositories.artist import ArtistRepository
from app.schemas.artist import ArtistIn, ArtistOrder, ArtistUpdate
from app.services.audit import AuditService

HOME_LIMIT = 12


class ArtistService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.artists = ArtistRepository(session)
        self.audit = AuditService(session)

    async def list_all(self) -> Sequence[Artist]:
        return await self.artists.all_in_order()

    async def for_home(self) -> Sequence[Artist]:
        return await self.artists.visible_on_home(HOME_LIMIT)

    async def create(self, payload: ArtistIn, *, actor: User) -> Artist:
        artist = Artist(
            name=payload.name,
            note=payload.note,
            photo_url=payload.photo_url,
            show_on_home=payload.show_on_home,
            sort_order=await self.artists.next_position(),
        )
        self.artists.add(artist)
        await self.session.flush()
        await self.audit.record(
            "artist.created",
            entity_type="artist",
            entity_id=artist.id,
            actor=actor,
            after={"name": artist.name},
        )
        await self.session.commit()
        return artist

    async def update(self, artist_id: uuid.UUID, payload: ArtistUpdate, *, actor: User) -> Artist:
        artist = await self._get(artist_id)
        changes = payload.model_dump(exclude_unset=True)
        # A blank note or photo means "remove it"; a name can never be blank (the schema refuses).
        for field, value in changes.items():
            setattr(artist, field, value)
        await self.audit.record(
            "artist.updated",
            entity_type="artist",
            entity_id=artist.id,
            actor=actor,
            after={k: v for k, v in changes.items() if k != "photo_url"},
        )
        await self.session.commit()
        return artist

    async def delete(self, artist_id: uuid.UUID, *, actor: User) -> None:
        artist = await self._get(artist_id)
        await self.audit.record(
            "artist.deleted",
            entity_type="artist",
            entity_id=artist.id,
            actor=actor,
            before={"name": artist.name},
        )
        await self.artists.delete(artist)
        await self.session.commit()

    async def reorder(self, payload: ArtistOrder, *, actor: User) -> Sequence[Artist]:
        """Set the order from a full list of ids, so two admins cannot half-apply each other's."""
        current = {a.id: a for a in await self.artists.all_in_order()}
        if len(set(payload.ids)) != len(payload.ids) or set(payload.ids) != set(current):
            raise BusinessRuleError(
                "The list is out of date. Reload and try again.", code="ARTIST_ORDER_STALE"
            )
        for position, artist_id in enumerate(payload.ids):
            current[artist_id].sort_order = position
        await self.audit.record(
            "artist.reordered", entity_type="artist", entity_id=None, actor=actor
        )
        await self.session.commit()
        return await self.artists.all_in_order()

    async def _get(self, artist_id: uuid.UUID) -> Artist:
        artist = await self.artists.get(artist_id)
        if artist is None:
            raise NotFoundError("Artist not found.", code="ARTIST_NOT_FOUND")
        return artist
