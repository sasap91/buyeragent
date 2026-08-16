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
