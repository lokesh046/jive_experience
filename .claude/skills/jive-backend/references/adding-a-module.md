# Adding a feature or endpoint

## One file per layer, all named for the feature

Adding events, for example:

```
app/models/event.py         the table
app/schemas/event.py        the request/response contracts
app/repositories/event.py   the queries   (subclass BaseRepository)
app/services/event.py       the rules     (owns the transaction)
app/router/v1/events.py     the routes    (thin)
```

Build them in that order — each layer only depends on the one below it.

## Steps

1. **`app/models/<feature>.py`** — the table. Mixins: `UUIDPrimaryKeyMixin`,
   `TimestampMixin`.
2. Register it in `app/db/registry.py`, or Alembic will not see it.
3. `make migration m="..."` — then **read the generated file** and fix it.
4. **`app/schemas/<feature>.py`** — separate input and output models. Never
   return an ORM object directly; never accept a client-supplied price, total
   or status.
5. **`app/repositories/<feature>.py`** — subclass `BaseRepository[Model]`, set
   `model`, add only the queries specific to this feature.
6. **`app/services/<feature>.py`** — the business rules and the transaction
   boundary.
7. **`app/router/v1/<feature>s.py`** — route declarations only. No helper
   functions, no response classes, no limiter definitions: if you need one,
   it belongs in `app/dependencies.py` or `app/schemas/`.
8. Add a `…ServiceDep` to `app/dependencies.py` and mount the router in
   `app/router/v1/router.py`.
9. Tests, then `make check`.

## Repository

`BaseRepository` already gives you `get`, `get_or_fail`, `find_one`, `exists`,
`count`, `list`, `paginate`, `add`, `delete`, `flush`. Write only what is
specific:

```python
# app/repositories/event.py
class EventRepository(BaseRepository[Event]):
    model = Event

    async def published_slug(self, slug: str) -> Event | None:
        return await self.find_one(
            Event.slug == slug, Event.status == EventStatus.PUBLISHED
        )
```

## Service

The service owns the transaction. `get_db` never commits for you.

```python
# app/services/event.py
class EventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.events = EventRepository(session)

    async def publish(self, event_id: UUID, actor: User) -> Event:
        event = await self.events.get_or_fail(event_id)
        if event.status is not EventStatus.DRAFT:
            raise BusinessRuleError("Only a draft event can be published.")
        event.status = EventStatus.PUBLISHED
        await self.session.commit()
        return event
```

Raise the shared errors from `app/core/errors.py` — `NotFoundError`,
`ConflictError`, `BusinessRuleError`, `PermissionDeniedError`,
`AuthenticationError` — so every failure comes back in one envelope with a
stable `code`. Define a module-specific subclass only when the client needs to
distinguish that case (e.g. `TicketAlreadyUsedError`).

## Router

```python
# app/router/v1/events.py
router = APIRouter(tags=["events"])

@router.post("/{event_id}/publish", response_model=EventOut)
async def publish_event(
    event_id: UUID,
    session: DbSession,
    actor: RequireAdmin,          # from app/dependencies.py
) -> Event:
    return await EventService(session).publish(event_id, actor)
```

Rules:

- No `try/except` for control flow — the shared handlers do that.
- No business logic, no raw queries.
- Paginated list endpoints take `Pagination` and return `Page[Schema]` built
  from `repository.paginate(...)`.
- Admin-only routes carry the admin dependency. Staff routes additionally
  check the event assignment — a staff member may only touch events assigned
  to them.

## Public vs admin endpoints

Keep them separate even for the same resource. A public event response must
not expose draft events, internal notes, cost figures or customer data. Two
schemas and two routes are clearer and safer than one with conditionals.
