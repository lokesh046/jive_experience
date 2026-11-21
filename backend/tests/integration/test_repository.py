"""The shared repository base, exercised through the user repository.

Every module reuses `BaseRepository`, so a bug here would be a bug in all of
them — it is tested once, here, rather than in each module.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.pagination import PageParams
from app.models.user import User, UserRole, UserStatus
from app.repositories.user import UserRepository
from tests.integration.conftest import unique_email, unique_phone

pytestmark = pytest.mark.integration


def make_customer(phone: str | None = None, name: str | None = None) -> User:
    return User(
        role=UserRole.CUSTOMER,
        status=UserStatus.ACTIVE,
        email=unique_email("repo"),
        phone_e164=phone,
        full_name=name,
    )


@pytest.fixture
def repo(db_session: AsyncSession) -> UserRepository:
    return UserRepository(db_session)


async def test_add_then_get(repo: UserRepository) -> None:
    user = repo.add(make_customer(unique_phone()))
    await repo.flush()

    assert user.id is not None
    assert await repo.get(user.id) is user


async def test_get_returns_none_for_a_missing_row(repo: UserRepository) -> None:
    assert await repo.get(uuid.uuid4()) is None


async def test_get_or_fail_raises_the_standard_not_found(repo: UserRepository) -> None:
    missing = uuid.uuid4()
    with pytest.raises(NotFoundError) as excinfo:
        await repo.get_or_fail(missing)

    error = excinfo.value
    assert error.code == "NOT_FOUND"
    assert error.status_code == 404
    assert error.details == {"id": str(missing)}
    assert "User" in error.message


async def test_find_one_and_exists(repo: UserRepository) -> None:
    phone_two = unique_phone()
    missing = unique_phone()
    repo.add(make_customer(phone_two))
    await repo.flush()

    assert await repo.by_phone(phone_two) is not None
    assert await repo.by_phone(missing) is None
    assert await repo.exists(User.phone_e164 == phone_two)
    assert not await repo.exists(User.phone_e164 == missing)


async def test_email_lookup_is_case_insensitive_on_input(repo: UserRepository) -> None:
    email = unique_email("ops")
    repo.add(User(role=UserRole.ADMIN, status=UserStatus.ACTIVE, email=email))
    await repo.flush()

    assert await repo.by_email(email.upper()) is not None


async def test_count_filters(repo: UserRepository) -> None:
    before = await repo.count_by_role(UserRole.CUSTOMER)
    repo.add(make_customer())
    repo.add(make_customer())
    await repo.flush()

    assert await repo.count_by_role(UserRole.CUSTOMER) == before + 2


async def test_list_orders_and_limits(repo: UserRepository) -> None:
    for index in range(5):
        repo.add(make_customer(unique_phone(), name=f"user-{index}"))
    await repo.flush()

    rows = await repo.list(
        User.full_name.like("user-%"),
        order_by=[User.full_name.desc()],
        limit=2,
    )
    assert [row.full_name for row in rows] == ["user-4", "user-3"]


async def test_paginate_returns_the_page_and_the_full_total(repo: UserRepository) -> None:
    for index in range(7):
        repo.add(make_customer(unique_phone(), name=f"page-{index}"))
    await repo.flush()

    where = User.full_name.like("page-%")
    rows, total = await repo.paginate(
        PageParams(page=2, size=3), where, order_by=[User.full_name.asc()]
    )

    assert total == 7, "total must count every match, not just this page"
    assert [row.full_name for row in rows] == ["page-3", "page-4", "page-5"]


async def test_paginate_past_the_last_page_is_empty_not_an_error(
    repo: UserRepository,
) -> None:
    rows, total = await repo.paginate(PageParams(page=99, size=20), User.full_name == "nobody")
    assert rows == []
    assert total == 0


async def test_delete(repo: UserRepository) -> None:
    phone_del = unique_phone()
    user = repo.add(make_customer(phone_del))
    await repo.flush()

    await repo.delete(user)
    await repo.flush()

    assert await repo.by_phone(phone_del) is None
