from __future__ import annotations

from typing import Protocol, TypeVar

from mandatelab_contracts.models import BuyerPreferenceProfile


ProfileInputT = TypeVar("ProfileInputT", contravariant=True)


class PreferenceProfileBuilder(Protocol[ProfileInputT]):
    """Shared boundary implemented by either preference-learning path.

    Luke may bind ``ProfileInputT`` to pairwise-comparison input, while Sasa may
    bind it to purchase-history input. Both paths must return the same validated
    buyer-profile contract.
    """

    def build_profile(
        self, source: ProfileInputT, /
    ) -> BuyerPreferenceProfile:
        """Build a shared buyer profile from module-specific source data."""

