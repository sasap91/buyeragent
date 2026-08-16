# MandateLab cold-start profile

Luke's Bayesian comparison model learns buyer preferences from accepted and
rejected products. `ColdStartProfileBuilder` converts its observable behavior
into `mandatelab_contracts.BuyerPreferenceProfile`.

Price, quality, and brand signals carry `COLD_START` source and confidence.
Attributes the comparison catalog cannot observe—delivery, returns, merchant
trust, and condition—remain explicitly unknown rather than being guessed.

The frontend's `POST /api/update` route is provided by
`user_profile.server.router` and mounted into the shared MandateLab FastAPI
application. Its response remains compatible with the existing weights and
plots UI and additionally includes the shared profile under `profile`.
