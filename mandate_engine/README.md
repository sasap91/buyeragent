# MandateLab engine

This package currently contains only deterministic hard-constraint evaluation.
It does not make `APPROVE`, `REVIEW`, or `BLOCK` decisions and does not rank or
execute candidates.

## Constraint contract

| Constraint kind | Operator | Expected value | Candidate field |
| --- | --- | --- | --- |
| `MAX_LANDED_PRICE` | `LTE` | `Money` | `final_landed_price` |
| `ALLOWED_CONDITION` | `IN` | `list[str]` | `condition` |
| `REQUIRED_FEATURES` | `CONTAINS_ALL` | `list[str]` | `features` |
| `DELIVERY_BY` | `ON_OR_BEFORE` | `date` | `delivery_date` |
| `ALLOWED_MERCHANT` | `IN` | `list[str]` | `merchant` |
| `PRODUCT_ID` | `EQ` | `str` | `product_id` |
| `VARIANT_ID` | `EQ` | `str` | `variant_id` |

Missing candidate data returns `UNKNOWN`. A known mismatch returns `FAIL`, and
a verified match returns `PASS`. Invalid operator/value combinations raise
`ConstraintDefinitionError` because they are malformed mandates, not uncertain
catalog data. String membership and feature comparisons are case-insensitive;
product and variant identifiers use exact matching.

The evaluator reports the observed fact independently of policy: the
constraint's `required` flag does not change `PASS`/`FAIL`/`UNKNOWN`. Later
decision logic will use that flag when choosing `APPROVE`, `REVIEW`, or `BLOCK`.
`PRODUCT_ID` cannot be `UNKNOWN` because it is required by the shared
`TransactionCandidate` schema. Monetary comparison is amount-only because every
`Money` value is USD in the MVP.

`evaluate_constraints` preserves mandate order. `is_feasible` returns true only
when every supplied result is `PASS`; an empty result collection is feasible.

## Preference-profile integration

Luke's cold-start module and Sasa's history module should each structurally
implement `mandatelab_contracts.PreferenceProfileBuilder[TheirInputType]`:

```python
def build_profile(source: TheirInputType, /) -> BuyerPreferenceProfile: ...
```

The input stays module-specific. The returned Pydantic model is the shared
boundary. Example targets are in `contracts/examples/` and
`mandate_engine/fixtures/`.

## Intent-to-mandate conversion

`parse_mandate(intent, profile)` accepts an already structured `PurchaseIntent`;
it does not parse natural language or call an LLM. Current intent constraints
override profile hard-rule candidates of the same kind. A profile candidate is
promoted to a mandate constraint only when `requires_confirmation` is false and
the profile category matches the mandate category.

Missing goal and category values receive deterministic fallbacks and material
ambiguity codes. Missing authorization uses a caller-supplied default policy or,
when none exists, a zero-dollar safe policy. Both authorization fallbacks are
marked as material ambiguities so later decision logic cannot authorize silently.
Learned soft preferences remain in the separate buyer profile; only current
intent soft preferences are copied into the mandate.

## Candidate decisions

`evaluate_candidate(candidate, mandate)` evaluates the mandate constraints and
authorization policy without ranking the candidate. Decision precedence is:

1. Any known hard-constraint failure or spend above the maximum authorized
   total returns `BLOCK`.
2. Required unknown constraint data, missing final landed price, material
   ambiguity, or spend above the autonomous limit returns `REVIEW`.
3. Otherwise the result is `APPROVE`.

An unknown result for a constraint whose `required` field is false is retained
as a warning but does not prevent approval. Every `REVIEW` requires human action.
A `BLOCK` includes violations and a structured replanning instruction that
excludes the rejected candidate. Candidate evaluation does not validate an
earlier cart approval; final pre-checkout validation remains a later stage.

## Final pre-checkout validation

`compute_cart_fingerprint(candidate, material_fields)` creates a canonical SHA-256
fingerprint of the material fields configured by `AuthorizationPolicy`.
`validate_precheckout(cart, mandate, approval)` recomputes that fingerprint,
reruns all constraints and spending limits, and validates any approval against
the exact mandate ID, mandate version, cart ID, fingerprint, and validity window.

A valid approval may convert `REVIEW` to `APPROVE` only when the sole review
condition is spend above the autonomous limit but within the maximum authorized
total. It cannot override `BLOCK`, a required `UNKNOWN`, missing final price, or
material mandate ambiguity. A changed cart, stale fingerprint, expired approval,
future-dated approval, or identifier mismatch returns `REVIEW` and requires a new
exact-cart approval.
