# MandateLab - Buyer-Aligned Commerce Agent

## 5-6 Hour Hackathon MVP PRD

## 1. Product Thesis

MandateLab is a buyer-alignment and authorization layer for agentic commerce. It learns what “best” means for an individual buyer, converts a purchase request into an explicit mandate, and enables a commerce agent to find and execute the best permissible purchase.

The core objective is to:

> Maximize buyer utility while preventing known hard-constraint violations across the MVP’s supported fields and evaluation scenarios.

“Best deal” does not necessarily mean the cheapest product. It means the best buyer-specific trade-off across price, quality, brand, delivery, condition, returns, merchant trust, and other supported attributes.

MandateLab separates two responsibilities:

1. Commerce execution: finding and attempting to purchase a product.
2. Mandate authorization: independently determining whether the proposed transaction is permissible.

The commerce executor must not bypass or override the Mandate Decision Engine.

## 2. Product Differentiation

MandateLab is not another generic shopping assistant. It is the buyer-alignment and authorization layer for agents that spend money.

Its differentiation comes from:

- Cold-start preference learning for buyers with no transaction history
- Behavioral preference learning for existing buyers
- Explicit separation of hard mandates from soft preferences
- Buyer-specific ranking rather than cheapest-product ranking
- Deterministic enforcement of supported hard constraints
- Autonomous execution only within the buyer’s defined authority
- Final transaction revalidation immediately before checkout
- Explainable `APPROVE`, `REVIEW`, and `BLOCK` decisions
- Learning-ready event logging from recommendations, purchases, rejections, returns, and feedback

Commerce systems increasingly help agents discover and transact. MandateLab focuses on whether the agent is acting in the buyer’s interest and within the buyer’s rules.

## 3. Core User Journey

Example request:

> “I need noise-cancelling headphones under $250, new only, this week. Prefer Sony, but I care more about quality than delivery speed.”

MandateLab should:

1. Build or retrieve the Buyer Preference Profile.
2. Parse the current request into:
   - Hard constraints
   - Soft preferences
   - Authorization rules
   - Material ambiguities
3. Search a controlled product catalog.
4. Evaluate each candidate against the hard constraints.
5. Remove products that fail a hard constraint.
6. Identify meaningful trade-offs among the remaining products.
7. Rank permissible products using the buyer’s preferences.
8. Select the best option or ask one targeted question when uncertainty materially affects the decision.
9. Return `APPROVE`, `REVIEW`, or `BLOCK`.
10. Replan when a candidate is rejected and another permissible option may exist.
11. Refresh and revalidate the final cart immediately before checkout.
12. Complete a test or sandbox transaction only when authorized.
13. Store the mission outcome and buyer feedback as learning-ready events.

## 4. Decision Semantics

Every proposed transaction must receive one of three decisions.

### APPROVE

Return `APPROVE` when:

- Every supported hard constraint passes
- Required transaction information is known
- The purchase remains within autonomous authority
- No final cart change invalidates an earlier decision

The executor may complete the sandbox purchase.

### REVIEW

Return `REVIEW` when:

- No known hard constraint is violated, but required information is missing
- The product is permissible but exceeds the autonomous spending limit
- The request contains a material ambiguity
- A product, price, delivery, or substitution change requires renewed approval
- The user must choose between materially different valid trade-offs

The executor must pause until the user clarifies or approves the exact transaction.

### BLOCK

Return `BLOCK` when:

- A hard constraint fails
- The final price exceeds the buyer’s maximum authorized price
- The product condition, delivery, feature, merchant, or other supported attribute violates the mandate
- The proposed transaction differs from the approved transaction in a forbidden way

A blocked purchase cannot proceed. The agent may replan or ask the user to explicitly revise the mandate.

Human approval does not silently override a hard constraint. The user must revise the mandate before a previously prohibited transaction can become permissible.

## 5. Core Product Components

### 5.1 New Buyer Preference Learning - Owner: Luke

Goal: Create a useful Buyer Preference Profile without transaction history.

MVP:

- Present up to 5-8 pairwise product comparisons, Tinder-style
- Use 4-5 comparisons in the live demo when sufficient
- Allow the user to select:
  - Product A
  - Product B
  - Either
  - Neither
- Design comparisons to expose trade-offs such as:
  - Price versus quality
  - Brand versus price
  - Delivery versus price
  - New versus refurbished
  - Return policy versus price
- Convert the responses into the common Buyer Preference Profile schema

Example output:

```text
Price sensitivity: MEDIUM
Quality importance: HIGH
Preferred brands: Sony > Bose
Delivery importance: LOW
Returns importance: HIGH
Refurbished allowed: NO
```

The system should learn from concrete trade-offs rather than asking users to assign arbitrary preference scores.

Any response that represents a strict prohibition, such as “never refurbished,” must be passed to the Mandate Engine as a possible hard rule rather than treated only as a ranking preference.

### 5.2 Existing Buyer Preference Learning - Owner: Sasa

Goal: Infer buyer preferences from previous behavior.

MVP inputs may use a small structured or synthetic history containing:

- Purchases
- Returns and cancellations
- Repeat purchases
- Brands and prices
- Accepted or rejected recommendations
- Product categories

The output must use the same Buyer Preference Profile schema as the cold-start module.

Purchase history is evidence, not ground truth. Current explicit intent always overrides learned behavior.

Preference hierarchy:

1. Current hard mandate
2. Current explicit preferences
3. Learned category preferences
4. General buyer preferences
5. Default assumptions

The MVP does not need to continuously retrain preference weights. It only needs to produce a profile and record later feedback as learning-ready data.

### 5.3 Mandate and Decision Engine - Owner: Prathmesh

Goal: Convert current intent and buyer preferences into an explicit mandate and a safe, buyer-specific decision.

Example mandate:

```text
GOAL
Buy noise-cancelling headphones

MUST
- New condition
- Noise cancelling
- Final price ≤ $250
- Delivery this week

PREFER
- Sony
- Higher sound quality
- Strong return policy

AUTHORITY
- Autonomous purchase allowed up to $200
- Human approval required from $200.01 to $250
- No product substitution without revalidation

MUST NOT
- Exceed $250
- Purchase refurbished or used products
- Execute when a required attribute is unknown

ASK OR REVIEW IF
- A material part of the request is ambiguous
- A hard constraint cannot be verified
- No permissible product exists
- A valid product exceeds autonomous authority
- The final cart differs from the approved transaction
```

Each supported constraint evaluation must return:

- `PASS`
- `FAIL`
- `UNKNOWN`

A product may enter the feasible set only when all supported hard constraints return `PASS`.

Decision flow:

```text
Buyer Profile + Current Intent
             ↓
    Structured Mandate
             ↓
    Candidate Products
             ↓
 Hard-Constraint Evaluation
             ↓
       Feasible Set
             ↓
Optional Dominance/Trade-off Filter
             ↓
Buyer-Specific Preference Ranking
             ↓
  APPROVE / REVIEW / BLOCK
```

The engine should use deterministic code for constraint enforcement. An LLM may extract structured intent, but it must not make the final arithmetic or policy-compliance decision.

A lightweight deterministic weighted scorer is sufficient for personalized ranking. Generic Pareto optimization is a stretch goal.

Every recommendation must explain:

- Which hard constraints passed
- Which products were rejected and why
- Which buyer preferences influenced the ranking
- Why the selected option is best for this buyer
- Whether human approval is required

### 5.4 Transaction Execution - Owner: Prathmesh

Goal: Execute the selected purchase without violating the mandate.

The executor and Decision Engine must remain separate modules, even though Prathmesh owns both.

Required executor actions:

- Search or retrieve products from the controlled catalog
- Inspect normalized product attributes
- Select the authorized product and variant
- Add the product to a simulated or sandbox cart
- Refresh final price and delivery information
- Send the final cart snapshot to the Decision Engine
- Execute only after `APPROVE` or valid human approval following `REVIEW`
- Abort or replan after `BLOCK`

Mandatory final validation must check:

- Correct product and variant
- Final landed price
- Product condition
- Required features
- Delivery requirement
- Merchant, if included in the mandate
- Forbidden substitution or cart changes
- Autonomous spending authority
- Whether an earlier approval still applies

Human approval must be attached to a specific cart snapshot. A material change to the product, variant, price, condition, merchant, or delivery invalidates the approval and requires revalidation.

### 5.5 Replanning

A rejected candidate should produce structured feedback that the commerce executor can use to search again.

Example:

```json
{
  "decision": "BLOCK",
  "violations": [
    {
      "code": "CONDITION_NOT_ALLOWED",
      "expected": "new",
      "actual": "refurbished"
    }
  ],
  "replan_constraints": {
    "condition": "new"
  }
}
```

For the MVP, one successful rejection-and-replanning cycle is sufficient.

## 6. Shared Data Contracts

The team must agree on the shared schemas before building individual modules.

### BuyerPreferenceProfile

Contains:

- Buyer identifier
- Category
- Price sensitivity
- Quality importance
- Delivery importance
- Return-policy importance
- Preferred and disliked brands
- Condition preferences
- Source of each preference
- Confidence, when applicable

### Mandate

Contains:

- Goal
- Hard constraints
- Soft preferences
- Authorization rules
- Material ambiguities
- Explicit versus inferred source
- Mandate version or identifier

### TransactionCandidate / CartSnapshot

Contains:

- Product and variant identifier
- Product name
- Brand
- Condition
- Features
- Merchant
- Item price
- Shipping and fees
- Final landed price
- Delivery date
- Return policy
- Timestamp

### DecisionResult

Contains:

- `APPROVE`, `REVIEW`, or `BLOCK`
- Constraint-level `PASS`, `FAIL`, or `UNKNOWN` results
- Violations
- Warnings
- Ranking explanation
- Approval requirement
- Replanning instructions
- Mandate and cart identifiers

Conceptual interfaces:

```text
build_profile(history_or_comparisons) → BuyerPreferenceProfile

parse_mandate(intent, profile) → Mandate

evaluate_candidate(candidate, mandate, profile) → DecisionResult

validate_precheckout(cart_snapshot, mandate, approval) → DecisionResult

execute_sandbox(cart_snapshot, decision) → TransactionOutcome
```

These may be implemented as functions or APIs depending on integration needs.

## 7. Learning and RL-Ready Logging

The MVP does not need to train an RL model.

It should log each shopping mission as a trajectory:

```text
Buyer state
→ Current intent
→ Mandate
→ Candidate products
→ Agent actions
→ Constraint decisions
→ Transaction outcome
→ Buyer feedback
→ Reward signals
```

Example reward dimensions:

- Successful permissible purchase
- Buyer-preference fit
- Economic value or savings
- Correct autonomous action
- Correct escalation
- Unnecessary user interruption
- Return, rejection, or cancellation

Hard failures include:

- Unauthorized purchase
- Hard-mandate violation
- Privacy violation
- Execution after an invalidated approval

Logging may use a simple JSON event file or in-memory event store.

Future extensions may use these trajectories for preference learning, contextual bandits, offline RL, and simulated RL.

## 8. MVP Scope

Build one end-to-end category: headphones or closely related consumer electronics.

Use:

- A controlled catalog of approximately 10-15 normalized products
- A simulated cart or supported sandbox store
- Structured or synthetic buyer histories
- No real-money payment
- No production browser automation requirement
- No production retailer integration requirement

The MVP must demonstrate both profile paths:

```text
Path A - New Buyer
Pairwise comparisons
→ Buyer Preference Profile

Path B - Existing Buyer
Sample purchase history
→ Buyer Preference Profile
```

Both paths converge into:

```text
Buyer Profile
+ Current Intent
→ Mandate
→ Product Set
→ Hard-Constraint Evaluation
→ Buyer-Specific Ranking
→ APPROVE / REVIEW / BLOCK
→ Replanning or Final Validation
→ Sandbox Transaction
→ Feedback Logging
```

### Out of Scope

- Real-money payment
- Production transaction-data integrations
- Multi-retailer production support
- Generic browser purchasing
- Full RL training
- Long-term memory infrastructure
- Negotiation
- Production security or identity infrastructure
- Generic optimization across every product category

### Stretch Goals

- Generic Pareto optimization
- Multiple autonomous replanning cycles
- Automatic preference-weight updates
- Advanced confidence calibration
- Prompt-injection resistance demonstrations
- Multi-category support
- Rich audit dashboard

## 9. Evaluation Scenarios

The MVP should be tested against at least the following scenarios:

1. Two buyers receive different recommendations from the same catalog.
2. Current explicit intent overrides historical preferences.
3. An attractive product is blocked because it violates a hard constraint.
4. A permissible product returns `REVIEW` because it exceeds autonomous authority.
5. Missing condition or delivery information prevents autonomous execution.
6. A rejected product produces a successful replanning attempt.
7. A final price, delivery, or product change is detected before checkout.
8. A valid and authorized sandbox transaction completes successfully.

## 10. Success Criteria

The demo must prove four core capabilities.

### Personalization

Two buyers can receive different “best” recommendations from the same product set.

### Intent Adaptation

Current explicit intent can override learned or historical behavior.

### Mandate Safety

An otherwise attractive product is rejected when it violates a hard rule, and uncertain hard-constraint data does not silently pass.

### Controlled Execution

The agent completes a permissible sandbox transaction and stops, escalates, or replans when authorization is insufficient.

MVP metrics:

- Zero hard-mandate violations across the predefined test suite
- No execution after `BLOCK`
- No execution after unresolved `REVIEW`
- No more than eight cold-start comparisons
- Working end-to-end sandbox purchase
- At least one successful replanning demonstration
- Recommendation explanations tied to both buyer preferences and mandate constraints

## 11. Ownership

### Luke

- Cold-start pairwise comparison experience
- Cold-start Buyer Preference Profile generation
- Output compatibility with the shared schema

### Sasa

- Synthetic existing-buyer history
- Behavioral preference inference
- Output compatibility with the shared schema

### Prathmesh

- Shared mandate and transaction decision schemas
- Intent-to-mandate conversion
- Hard-constraint validation
- Authorization and escalation logic
- Personalized candidate ranking
- Decision explanations
- Replanning response contract
- Pre-checkout validation
- Sandbox transaction execution

### Shared

- Product catalog and normalized fixtures
- UI integration
- End-to-end integration testing
- Evaluation scenarios
- Demo preparation

Prathmesh is the directly responsible owner for the mandate schema and decision contract because all other modules depend on these interfaces.

## 12. Recommended Build Order

1. Freeze the four shared data contracts.
2. Create the normalized product catalog and buyer fixtures.
3. Build deterministic hard-constraint validation.
4. Build both preference-profile generators in parallel.
5. Add lightweight buyer-specific ranking.
6. Implement `APPROVE`, `REVIEW`, and `BLOCK`.
7. Connect the controlled search and sandbox cart.
8. Add final pre-checkout revalidation.
9. Add one rejection-and-replanning flow.
10. Add explanations and event logging.
11. Run the evaluation scenarios.
12. Freeze features and rehearse the demo.

The final 60-90 minutes should be reserved for integration, testing, and demo preparation rather than new features.

## 13. Demo Flow

1. Show two buyers with different preference profiles.
2. Give both buyers the same product catalog.
3. Enter a current purchase request.
4. Show the generated mandate.
5. Show an attractive product rejected by a hard constraint.
6. Show the agent replan using the rejection reason.
7. Show different best products for the two buyers.
8. Show one transaction requiring human approval.
9. Change the final price or delivery information.
10. Demonstrate final validation catching the change.
11. Complete one authorized sandbox purchase.
12. Show the recorded trajectory and buyer feedback.

## 14. Demo Message

> Same products. Different buyer. Different best decision. Same mandate discipline.

Core product claim:

> MandateLab learns what “best” means for you-and gives your buyer agent the intelligence and boundaries to act on it.

Short pitch:

> MandateLab is the buyer-alignment and authorization layer for agents that spend money.
