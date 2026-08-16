from __future__ import annotations

from decimal import Decimal

from mandatelab_contracts import (
    AuthorizationPolicy,
    BuyerPreferenceProfile,
    HardConstraint,
    Mandate,
    MandateSource,
    Money,
    PurchaseIntent,
)


GOAL_INFERRED_FROM_RAW_TEXT = "GOAL_INFERRED_FROM_RAW_TEXT"
CATEGORY_INFERRED_FROM_PROFILE = "CATEGORY_INFERRED_FROM_PROFILE"
AUTHORIZATION_DEFAULTED_FROM_POLICY = "AUTHORIZATION_DEFAULTED_FROM_POLICY"
AUTHORIZATION_MISSING_SAFE_ZERO_APPLIED = (
    "AUTHORIZATION_MISSING_SAFE_ZERO_APPLIED"
)
PROFILE_RULE_REQUIRES_CONFIRMATION = "PROFILE_RULE_REQUIRES_CONFIRMATION"


class MandateConversionError(ValueError):
    """Raised when intent and profile cannot safely form one buyer mandate."""


def _safe_zero_authorization() -> AuthorizationPolicy:
    return AuthorizationPolicy(
        autonomous_spend_limit=Money(amount=Decimal("0")),
        maximum_authorized_total=Money(amount=Decimal("0")),
        substitution_allowed=False,
    )


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _profile_matches_category(
    profile: BuyerPreferenceProfile, category: str
) -> bool:
    return profile.category.casefold() == category.casefold()


def _profile_constraints(
    profile: BuyerPreferenceProfile,
    explicit_constraints: list[HardConstraint],
    ambiguities: list[str],
) -> list[HardConstraint]:
    explicit_kinds = {constraint.kind for constraint in explicit_constraints}
    converted: list[HardConstraint] = []

    for candidate in profile.hard_rule_candidates:
        if candidate.kind in explicit_kinds:
            continue
        if candidate.requires_confirmation:
            ambiguities.append(
                f"{PROFILE_RULE_REQUIRES_CONFIRMATION}:{candidate.candidate_id}"
            )
            continue
        converted.append(
            HardConstraint(
                constraint_id=f"profile:{candidate.candidate_id}",
                kind=candidate.kind,
                operator=candidate.operator,
                expected=candidate.expected,
                source=MandateSource.CONFIRMED_PROFILE_RULE,
                confidence=candidate.confidence,
            )
        )

    return converted


def parse_mandate(
    intent: PurchaseIntent,
    profile: BuyerPreferenceProfile,
    *,
    default_authorization: AuthorizationPolicy | None = None,
    mandate_id: str | None = None,
    version: int = 1,
) -> Mandate:
    """Convert structured intent and a shared profile into an explicit mandate.

    This function performs deterministic precedence and fallback handling only.
    Natural-language extraction belongs outside this boundary.
    """

    if intent.buyer_id != profile.buyer_id:
        raise MandateConversionError(
            "intent and profile buyer_id must match: "
            f"{intent.buyer_id!r} != {profile.buyer_id!r}"
        )

    ambiguities = list(intent.material_ambiguities)

    if intent.goal is None:
        goal = intent.raw_text
        ambiguities.append(GOAL_INFERRED_FROM_RAW_TEXT)
    else:
        goal = intent.goal

    if intent.category is None:
        category = profile.category
        ambiguities.append(CATEGORY_INFERRED_FROM_PROFILE)
    else:
        category = intent.category

    if intent.authorization is not None:
        authorization = intent.authorization
    elif default_authorization is not None:
        authorization = default_authorization
        ambiguities.append(AUTHORIZATION_DEFAULTED_FROM_POLICY)
    else:
        authorization = _safe_zero_authorization()
        ambiguities.append(AUTHORIZATION_MISSING_SAFE_ZERO_APPLIED)

    hard_constraints = list(intent.hard_constraints)
    if _profile_matches_category(profile, category):
        hard_constraints.extend(
            _profile_constraints(profile, hard_constraints, ambiguities)
        )

    return Mandate(
        mandate_id=mandate_id or f"mandate:{intent.intent_id}",
        version=version,
        buyer_id=intent.buyer_id,
        goal=goal,
        category=category,
        hard_constraints=hard_constraints,
        soft_preferences=list(intent.soft_preferences),
        authorization=authorization,
        material_ambiguities=_deduplicate(ambiguities),
        created_at=intent.created_at,
    )
