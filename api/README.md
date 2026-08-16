# MandateLab API

This package is the HTTP composition boundary for the deterministic MandateLab
engine and sandbox executor. Routes validate API envelopes and call the public
package interfaces; they do not implement authorization or ranking policy.

Run from the repository root after `uv sync`:

```bash
uv run mandatelab-api
```

Interactive OpenAPI documentation is then available at
`http://127.0.0.1:8000/docs`.

All routes are versioned under `/api/v1`, leaving Luke's cold-start `/api/update`
route available for UI integration without a path collision.
