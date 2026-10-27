"""FastAPI application setup for the chat-first TaskSentry Console."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tasksentry.console.api import router as console_router
from tasksentry.console.api_v2 import router as telecom_v2_router
from tasksentry.console.domain_api import router as domain_router
from tasksentry.dashboard.api import router as dashboard_router
from tasksentry.onboarding.api import router as onboarding_router

STATIC_DIR = Path(__file__).parent / "static"
WEBAPP_DIR = Path(__file__).resolve().parents[3] / "webapp"


def create_console_app() -> FastAPI:
    """Create and configure the TaskSentry Console FastAPI application."""
    app = FastAPI(
        title="TaskSentry Console",
        description="Chat-first agent console with semantic routing, Bayesian RCA, and onboarding.",
        version="0.2.0",
    )

    # Include console chat API, dashboard analytics, telecom v2, and onboarding APIs
    app.include_router(console_router)
    app.include_router(dashboard_router)
    app.include_router(telecom_v2_router)
    app.include_router(onboarding_router)
    app.include_router(domain_router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        # Keep the original chat/telecom console available while the modern
        # universal onboarding console becomes the primary landing page.
        app.mount("/classic", StaticFiles(directory=str(STATIC_DIR), html=True), name="classic")

    if WEBAPP_DIR.is_dir():
        app.mount("/webapp", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(str(WEBAPP_DIR / "index.html"))

        @app.get("/style.css", include_in_schema=False)
        def webapp_style() -> FileResponse:
            return FileResponse(str(WEBAPP_DIR / "style.css"))

        @app.get("/app.js", include_in_schema=False)
        def webapp_script() -> FileResponse:
            return FileResponse(str(WEBAPP_DIR / "app.js"))

        @app.get("/sample_ticket.json", include_in_schema=False)
        def webapp_sample() -> FileResponse:
            return FileResponse(str(WEBAPP_DIR / "sample_ticket.json"))
    elif STATIC_DIR.is_dir():

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
