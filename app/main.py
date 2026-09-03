"""Public, bilingual FastAPI entry point for Newsday."""

from pathlib import Path
from typing import Union

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.i18n import TRANSLATIONS, alternate_locale, resolve_locale
from app.web_auth import install_account_routes


APP_DIRECTORY = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=APP_DIRECTORY / "templates")

app = FastAPI(title="Newsday", version="0.1.0", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=APP_DIRECTORY / "static"), name="static")
install_account_routes(app, templates)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Make Chinese the default public experience without guessing location."""
    return RedirectResponse(url="/zh/", status_code=307)


@app.get("/healthz", response_class=JSONResponse)
def healthz() -> dict[str, str]:
    """Liveness endpoint; dependency checks will be added with the data layer."""
    return {"status": "ok"}


@app.get("/readyz", response_class=JSONResponse)
def readyz() -> JSONResponse:
    """Confirm configuration and database availability without exposing secrets."""
    settings = getattr(app.state, "settings", None)
    if settings is None:
        from app.config import Settings

        settings = Settings.from_environment()
    missing = settings.missing_required_values()
    if missing:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "configuration"})
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        from app.db import build_session_factory

        factory = build_session_factory(settings.database_url)
    session = factory()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database"})
    finally:
        session.close()
    return JSONResponse(content={"status": "ready"})


@app.get(
    "/{locale}/",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def home(request: Request, locale: str) -> Union[HTMLResponse, RedirectResponse]:
    """Render the public home page in a supported locale."""
    resolved_locale = resolve_locale(locale)
    if resolved_locale != locale:
        return RedirectResponse(url=f"/{resolved_locale}/", status_code=307)

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "locale": resolved_locale,
            "alternate_locale": alternate_locale(resolved_locale),
            "text": TRANSLATIONS[resolved_locale],
        },
    )
