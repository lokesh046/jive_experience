"""The cancellation and refund policy: tiers of "at least N hours before → P percent"."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, model_validator

MAX_TIERS = 6


class PolicyTier(BaseModel):
    hours_before: Annotated[int, Field(ge=0, le=24 * 365)]
    percent: Annotated[int, Field(ge=0, le=100)]


class CancellationPolicy(BaseModel):
    """Stored on an event, or as the site default.

    A customer who cancels at least `hours_before` hours ahead gets `percent`
    of what they paid; the most generous tier they qualify for applies. Tiers
    are kept sorted from earliest to latest, and the refund may not grow as the
    event gets closer: a policy that pays more for a late cancellation is a
    typo, not a policy.
    """

    tiers: Annotated[list[PolicyTier], Field(max_length=MAX_TIERS)]

    @model_validator(mode="after")
    def _check(self) -> CancellationPolicy:
        self.tiers = sorted(self.tiers, key=lambda t: -t.hours_before)
        hours = [t.hours_before for t in self.tiers]
        if len(set(hours)) != len(hours):
            raise ValueError("Two tiers cannot start at the same number of hours.")
        for earlier, later in zip(self.tiers, self.tiers[1:], strict=False):
            if later.percent > earlier.percent:
                raise ValueError("A later cancellation cannot refund more than an earlier one.")
        return self


class DefaultPolicyIn(BaseModel):
    """`policy: null` clears the default, so events without their own policy fall back to
    "contact support"."""

    policy: CancellationPolicy | None = None


class DefaultPolicyOut(BaseModel):
    policy: CancellationPolicy | None = None
