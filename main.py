"""Convenience entry point for IDEs and ``uv run python main.py``."""

import uvicorn

from app.core.config import Settings

if __name__ == "__main__":
    settings = Settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
