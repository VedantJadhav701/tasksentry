"""FastAPI application setup and entrypoint for TaskSentry local dashboard."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tasksentry.console.api import router as console_router
from tasksentry.dashboard.api import router

STATIC_DIR = Path(__file__).parent / "static"
CONSOLE_STATIC_DIR = Path(__file__).parent.parent / "console" / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI dashboard application."""
    app = FastAPI(
        title="TaskSentry Console",
        description="Local control plane and telemetry dashboard for TaskSentry.",
        version="0.1.0",
    )

    app.include_router(console_router)
    app.include_router(router)

    if CONSOLE_STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(CONSOLE_STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(CONSOLE_STATIC_DIR / "index.html"))

    if STATIC_DIR.is_dir():
        app.mount("/classic-static", StaticFiles(directory=str(STATIC_DIR)), name="classic-static")

        @app.get("/classic", include_in_schema=False)
        def classic_index() -> FileResponse:
            return FileResponse(str(STATIC_DIR / "index.html"))

    return app


app = create_app()


def run_dashboard(host: str = "127.0.0.1", port: int = 8321) -> None:
    """Launch the local uvicorn server binding strictly to the specified host/port."""
    from tasksentry.console.app import run_console

    run_console(host=host, port=port)


if __name__ == "__main__":
    run_dashboard()
