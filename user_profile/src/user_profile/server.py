"""Standalone entry point for isolated cold-start UI work.

The production path is `uv run mandatelab-api`, which mounts this package's
router at POST /api/update on port 8000. This script serves the same router
alone on port 8001 so the Vite app can be developed without the full stack.
"""

from __future__ import annotations

from user_profile.router import standalone_app

__all__ = ["main", "standalone_app"]


def main() -> None:
    import uvicorn

    print(
        "Cold-start POST /api/update is mounted on mandatelab-api (port 8000).\n"
        "Serving the same router alone on port 8001 for isolated UI work."
    )
    uvicorn.run(
        "user_profile.server:standalone_app",
        host="127.0.0.1",
        port=8001,
        reload=False,
    )


if __name__ == "__main__":
    main()
