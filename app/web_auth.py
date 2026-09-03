"""Server-rendered, bilingual invitation and account pages."""

import hmac
import secrets
from typing import Optional

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth.invites import InviteCodeError
from app.auth.security import invite_lookup_hash, verify_password
from app.config import Settings
from app.db import build_session_factory
from app.i18n import TRANSLATIONS, alternate_locale, resolve_locale
from app.models import InviteCode
from app.services.accounts import AuthenticationError, create_login_session, current_user, register_user, revoke_session


CSRF_COOKIE = "newsday_csrf"
INVITE_COOKIE = "newsday_invite"
SESSION_COOKIE = "newsday_session"
INVITE_MAX_AGE_SECONDS = 15 * 60


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", Settings.from_environment())


def _session(request: Request):
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        settings = _settings(request)
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required for account pages")
        factory = build_session_factory(settings.database_url)
    return factory()


def _require_csrf(request: Request, submitted: str) -> None:
    expected = request.cookies.get(CSRF_COOKIE)
    if not expected or not hmac.compare_digest(expected, submitted):
        raise ValueError("请求已失效，请刷新页面后重试")


def _invite_serializer(settings: Settings) -> URLSafeTimedSerializer:
    if not settings.app_session_secret:
        raise RuntimeError("APP_SESSION_SECRET is required for account pages")
    return URLSafeTimedSerializer(settings.app_session_secret, salt="newsday-invite")


def _pending_invite(request: Request) -> Optional[str]:
    raw = request.cookies.get(INVITE_COOKIE)
    if not raw:
        return None
    try:
        return _invite_serializer(_settings(request)).loads(raw, max_age=INVITE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def _render(request: Request, template, locale: str, **extra):
    resolved = resolve_locale(locale)
    csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    response = template.TemplateResponse(request=request, name="account.html", context={
        "locale": resolved, "alternate_locale": alternate_locale(resolved), "csrf_token": csrf_token, "text": TRANSLATIONS[resolved], **extra
    })
    if not request.cookies.get(CSRF_COOKIE):
        response.set_cookie(CSRF_COOKIE, csrf_token, httponly=True, samesite="lax", secure=False)
    return response


def install_account_routes(app, templates) -> None:
    @app.get("/{locale}/invite/", response_class=HTMLResponse, include_in_schema=False)
    def invite_page(request: Request, locale: str):
        return _render(request, templates, locale, page="invite", error=None)

    @app.post("/{locale}/invite/", response_class=HTMLResponse, include_in_schema=False)
    def verify_invite(request: Request, locale: str, invite_code: str = Form(...), csrf_token: str = Form(...)):
        try:
            _require_csrf(request, csrf_token)
            settings = _settings(request)
            session = _session(request)
            try:
                code = invite_code.strip().upper()
                lookup = invite_lookup_hash(code, settings.invite_lookup_key)
                invite = session.query(InviteCode).filter(InviteCode.lookup_hash == lookup).one_or_none()
                if invite is None or not invite.enabled or not verify_password(invite.secret_hash, code):
                    raise InviteCodeError("邀请码无效或不可用")
                if invite.max_uses is not None and invite.used_count >= invite.max_uses:
                    raise InviteCodeError("邀请码无效或不可用")
            finally:
                session.close()
        except (InviteCodeError, ValueError):
            return _render(request, templates, locale, page="invite", error="邀请码无效或不可用。")
        response = RedirectResponse(url=f"/{resolve_locale(locale)}/register/", status_code=303)
        response.set_cookie(INVITE_COOKIE, _invite_serializer(_settings(request)).dumps(code), httponly=True, samesite="lax", secure=False, max_age=INVITE_MAX_AGE_SECONDS)
        return response

    @app.get("/{locale}/register/", response_class=HTMLResponse, include_in_schema=False)
    def register_page(request: Request, locale: str):
        if not _pending_invite(request):
            return RedirectResponse(url=f"/{resolve_locale(locale)}/invite/", status_code=303)
        return _render(request, templates, locale, page="register", error=None)

    @app.post("/{locale}/register/", response_class=HTMLResponse, include_in_schema=False)
    def register(request: Request, locale: str, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
        code = _pending_invite(request)
        if not code:
            return RedirectResponse(url=f"/{resolve_locale(locale)}/invite/", status_code=303)
        try:
            _require_csrf(request, csrf_token)
            session = _session(request)
            try:
                user, recovery_code = register_user(session, code, _settings(request).invite_lookup_key, username, password)
                token = create_login_session(session, username, password)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except (InviteCodeError, ValueError):
            return _render(request, templates, locale, page="register", error="无法创建账户，请检查用户名、密码和邀请码。")
        response = _render(request, templates, locale, page="recovery", error=None, recovery_code=recovery_code, username=user.username)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=False, max_age=14 * 24 * 3600)
        response.delete_cookie(INVITE_COOKIE)
        return response

    @app.get("/{locale}/login/", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request, locale: str):
        return _render(request, templates, locale, page="login", error=None)

    @app.post("/{locale}/login/", response_class=HTMLResponse, include_in_schema=False)
    def login(request: Request, locale: str, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
        try:
            _require_csrf(request, csrf_token)
            session = _session(request)
            try:
                token = create_login_session(session, username, password)
                session.commit()
            finally:
                session.close()
        except (AuthenticationError, ValueError):
            return _render(request, templates, locale, page="login", error="用户名或密码不正确。")
        response = RedirectResponse(url=f"/{resolve_locale(locale)}/dashboard/", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=False, max_age=14 * 24 * 3600)
        return response

    @app.get("/{locale}/dashboard/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard(request: Request, locale: str):
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
            if not user:
                return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
            return _render(request, templates, locale, page="dashboard", error=None, username=user.username)
        finally:
            session.close()

    @app.post("/{locale}/logout/", include_in_schema=False)
    def logout(request: Request, locale: str, csrf_token: str = Form(...)):
        _require_csrf(request, csrf_token)
        session = _session(request)
        try:
            revoke_session(session, request.cookies.get(SESSION_COOKIE))
            session.commit()
        finally:
            session.close()
        response = RedirectResponse(url=f"/{resolve_locale(locale)}/", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response
