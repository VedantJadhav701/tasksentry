"""Standalone console server:  uvicorn webapp.server:app --port 8080   (run from the zip/repo root).

Serves the web console and the onboarding API. Needs only: fastapi, uvicorn, pydantic.
For cloud-model assist, run Ollama locally with access to beam:cloud (OLLAMA_HOST to override).
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from tasksentry.onboarding.api import router

HERE = Path(__file__).parent
app = FastAPI(title="TaskSentry Console")
app.include_router(router)


@app.get("/api/onboard/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sample", response_class=PlainTextResponse)
def sample() -> str:
    return (HERE / "sample_ticket.json").read_text()


app.mount("/", StaticFiles(directory=HERE, html=True), name="web")
