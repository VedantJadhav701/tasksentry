"""FastAPI application setup and entrypoint for TaskSentry local dashboard."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tasksentry.dashboard.api import router

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI dashboard application."""
    app = FastAPI(
        title="TaskSentry Dashboard",
        description="Local control plane and telemetry dashboard for TaskSentry.",
        version="0.1.0",
    )

    app.include_router(router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(STATIC_DIR / "index.html"))

    return app


app = create_app()


def run_dashboard(host: str = "127.0.0.1", port: int = 8321) -> None:
    """Launch the local uvicorn server binding strictly to the specified host/port."""
    import uvicorn

    # Strict local-only binding by default
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_dashboard()
