"""Config-aware local entry point for the TalkPath server."""

import uvicorn

from talkpath.config import get_settings


def run() -> None:
    """Start the FastAPI application with TalkPath settings."""

    settings = get_settings()
    uvicorn.run(
        "talkpath.api.app:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
    )


if __name__ == "__main__":
    run()
