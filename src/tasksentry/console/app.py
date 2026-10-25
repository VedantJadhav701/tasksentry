"""FastAPI application setup for the chat-first TaskSentry Console."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tasksentry.console.api import router as console_router
from tasksentry.dashboard.api import router as dashboard_router

STATIC_DIR = Path(__file__).parent / "static"


def create_console_app() -> FastAPI:
    """Create and configure the TaskSentry Console FastAPI application."""
    app = FastAPI(
        title="TaskSentry Console",
        description="Chat-first agent console with semantic routing and real-time observability.",
        version="0.1.0",
    )

    # Include both console chat API and dashboard analytics API
    app.include_router(console_router)
    app.include_router(dashboard_router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(STATIC_DIR / "index.html"))

    return app


app = create_console_app()


def run_console(host: str = "127.0.0.1", port: int = 8321) -> None:
    """Launch the local TaskSentry Console server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_console()
