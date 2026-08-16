# MandateLab sandbox executor

This package is deliberately separate from the Mandate Decision Engine. It
simulates a completed purchase in memory and never contacts a retailer, payment
processor, or browser.

`InMemorySandboxExecutor.execute(cart, decision)` executes only when the decision:

- is `APPROVE`;
- requires no unresolved human approval;
- has no recorded violations;
- names the same candidate and cart ID;
- contains the exact cart fingerprint; and
- was evaluated no later than the execution attempt.

Every rejection returns a `TransactionOutcome` with status `NOT_EXECUTED` and a
stable reason code. Successful identical retries return the original outcome and
do not create another ledger record. Reusing a cart ID with a different decision
or fingerprint is rejected as `CART_ALREADY_EXECUTED`.

The convenience `execute_sandbox(cart, decision)` function creates a one-shot
executor. Pass a reusable executor through its `executor=` argument when ledger
history and duplicate protection must span multiple calls.
