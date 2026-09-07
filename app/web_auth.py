"""Server-rendered, bilingual invitation and account pages."""

import hmac
import secrets
from typing import Optional
from uuid import UUID

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import requests

from app.auth.invites import InviteCodeError
from app.auth.security import invite_lookup_hash, verify_password
from app.config import Settings
from app.db import build_session_factory
from app.i18n import TRANSLATIONS, alternate_locale, resolve_locale
from app.models import InviteCode
from app.services.accounts import AuthenticationError, change_password, create_login_session, current_user, register_user, reset_password_with_recovery_code, revoke_session
from app.services.subscriptions import SubscriptionValidationError, load_subscription, save_subscription
from app.services.destinations import DestinationValidationError, save_destination, send_test_webhook, validate_webhook
from app.services.news import public_news, public_source_url
from app.services.categories import category_choices, category_presets, update_category_preset
from app.services.dashboard import cancel_subscription, dashboard_summary, set_subscription_enabled
from app.services.admin_invites import (
    create_admin_invite,
    disable_admin_invite,
    list_admin_invites,
    update_admin_invite_note,
)
from app.services.admin_dashboard import (
    admin_recent_deliveries,
    admin_failed_deliveries,
    admin_subscription_rows,
    retry_failed_delivery,
    set_destination_enabled,
    set_admin_subscription_enabled,
)
from app.services.security_controls import (
    RateLimitError,
    enforce_rate_limit,
    recent_audit_events,
    record_audit_event,
)


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


def _client_identifier(request: Request) -> str:
    """Use proxy forwarding only from the local reverse proxy."""
    client_host = request.client.host if request.client else "unknown"
    if client_host in {"127.0.0.1", "::1"}:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return client_host


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
        response.set_cookie(CSRF_COOKIE, csrf_token, httponly=True, samesite="lax", secure=_settings(request).cookie_secure)
    return response


def install_account_routes(app, templates) -> None:
    def render_admin(request, locale, invites, subscribers, deliveries, failed_deliveries, presets, audits, error=None):
        resolved = resolve_locale(locale); token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        response = templates.TemplateResponse(request=request, name="admin.html", context={"locale":resolved,"alternate_locale":alternate_locale(resolved),"text":TRANSLATIONS[resolved],"csrf_token":token,"invites":invites,"subscribers":subscribers,"deliveries":deliveries,"failed_deliveries":failed_deliveries,"presets":presets,"audits":audits,"error":error})
        if not request.cookies.get(CSRF_COOKIE): response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="lax", secure=_settings(request).cookie_secure)
        return response

    @app.get("/{locale}/admin/", response_class=HTMLResponse, include_in_schema=False)
    def admin_page(request: Request, locale: str):
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
            if not user or not _settings(request).is_admin(user.username): return RedirectResponse(url=f"/{resolve_locale(locale)}/", status_code=303)
            return render_admin(request, locale, list_admin_invites(session), admin_subscription_rows(session), admin_recent_deliveries(session), admin_failed_deliveries(session), category_presets(session), recent_audit_events(session))
        finally: session.close()

    @app.post("/{locale}/admin/", response_class=HTMLResponse, include_in_schema=False)
    def admin_create(
        request: Request,
        locale: str,
        action: str = Form("create"),
        invite_id: str = Form(""),
        invite_note: str = Form(""),
        user_id: str = Form(""),
        subscription_enabled: str = Form(""),
        delivery_job_id: str = Form(""),
        destination_id: str = Form(""),
        destination_enabled: str = Form(""),
        category_key: str = Form(""),
        label_zh: str = Form(""),
        label_en: str = Form(""),
        sort_order: str = Form(""),
        category_enabled: str = Form(""),
        code: str = Form(""),
        max_uses: str = Form(""),
        csrf_token: str = Form(...),
    ):
        _require_csrf(request, csrf_token); session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
            if not user or not _settings(request).is_admin(user.username): return RedirectResponse(url=f"/{resolve_locale(locale)}/", status_code=303)
            try:
                if action == "disable":
                    if not disable_admin_invite(session, UUID(invite_id)):
                        raise ValueError
                    record_audit_event(session, user.id, "invite_disabled", "invite", invite_id)
                elif action == "update_invite_note":
                    if not update_admin_invite_note(session, UUID(invite_id), invite_note):
                        raise ValueError
                    record_audit_event(session, user.id, "invite_note_updated", "invite", invite_id)
                elif action == "set_subscription":
                    if subscription_enabled not in {"true", "false"} or not set_admin_subscription_enabled(session, UUID(user_id), subscription_enabled == "true"):
                        raise ValueError
                    record_audit_event(session, user.id, "subscription_enabled_changed", "user", user_id)
                elif action == "retry_delivery":
                    if not retry_failed_delivery(session, UUID(delivery_job_id)):
                        raise ValueError
                    record_audit_event(session, user.id, "delivery_retry_requested", "delivery_job", delivery_job_id)
                elif action == "set_destination":
                    if destination_enabled not in {"true", "false"} or not set_destination_enabled(session, UUID(destination_id), destination_enabled == "true"):
                        raise ValueError
                    record_audit_event(session, user.id, "destination_enabled_changed", "destination", destination_id)
                elif action == "update_category":
                    if category_enabled not in {"true", "false"} or not update_category_preset(session, category_key, label_zh=label_zh, label_en=label_en, sort_order=int(sort_order), enabled=category_enabled == "true"):
                        raise ValueError
                    record_audit_event(session, user.id, "category_preset_updated", "category", category_key)
                elif action == "create":
                    invite = create_admin_invite(session, code, _settings(request).invite_lookup_key, int(max_uses) if max_uses else None, invite_note)
                    record_audit_event(session, user.id, "invite_created", "invite", invite.id)
                else:
                    raise ValueError
                session.commit()
            except ValueError:
                session.rollback(); return render_admin(request, locale, list_admin_invites(session), admin_subscription_rows(session), admin_recent_deliveries(session), admin_failed_deliveries(session), category_presets(session), recent_audit_events(session), error="管理操作无效。")
            return render_admin(request, locale, list_admin_invites(session), admin_subscription_rows(session), admin_recent_deliveries(session), admin_failed_deliveries(session), category_presets(session), recent_audit_events(session))
        finally: session.close()

    def render_subscription(request: Request, locale: str, user, error=None, saved=False):
        resolved = resolve_locale(locale)
        session = _session(request)
        try:
            subscription = load_subscription(session, user.id)
            limits = {item.category: item.item_limit for item in subscription.categories} if subscription else {}
            times = [item.local_time.strftime("%H:%M") for item in subscription.schedules] if subscription else ["08:00", "", ""]
            categories = category_choices(session, resolved, include_disabled=True)
        finally:
            session.close()
        csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        response = templates.TemplateResponse(request=request, name="subscription.html", context={"locale": resolved, "alternate_locale": alternate_locale(resolved), "text": TRANSLATIONS[resolved], "csrf_token": csrf_token, "categories": categories, "selected": limits, "limits": limits, "times": (times + ["", "", ""])[:3], "error": error, "saved": saved})
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, csrf_token, httponly=True, samesite="lax", secure=_settings(request).cookie_secure)
        return response

    @app.get("/{locale}/news/", response_class=HTMLResponse, include_in_schema=False)
    def news_page(request: Request, locale: str, category: Optional[str] = None):
        resolved = resolve_locale(locale)
        session = _session(request)
        try:
            items = public_news(session, category)
            labels = category_choices(session, resolved)
        finally:
            session.close()
        return templates.TemplateResponse(request=request, name="news.html", context={"locale": resolved, "alternate_locale": alternate_locale(resolved), "text": TRANSLATIONS[resolved], "categories": labels, "items": items, "source_url": public_source_url})
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
                enforce_rate_limit(session, "invite", _client_identifier(request), settings.app_session_secret, maximum=10)
                session.commit()
                code = invite_code.strip().upper()
                lookup = invite_lookup_hash(code, settings.invite_lookup_key)
                invite = session.query(InviteCode).filter(InviteCode.lookup_hash == lookup).one_or_none()
                if invite is None or not invite.enabled or not verify_password(invite.secret_hash, code):
                    raise InviteCodeError("邀请码无效或不可用")
                if invite.max_uses is not None and invite.used_count >= invite.max_uses:
                    raise InviteCodeError("邀请码无效或不可用")
            finally:
                session.close()
        except RateLimitError:
            return _render(request, templates, locale, page="invite", error="尝试过于频繁，请 15 分钟后再试。")
        except (InviteCodeError, ValueError):
            return _render(request, templates, locale, page="invite", error="邀请码无效或不可用。")
        response = RedirectResponse(url=f"/{resolve_locale(locale)}/register/", status_code=303)
        response.set_cookie(INVITE_COOKIE, _invite_serializer(_settings(request)).dumps(code), httponly=True, samesite="lax", secure=_settings(request).cookie_secure, max_age=INVITE_MAX_AGE_SECONDS)
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
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=_settings(request).cookie_secure, max_age=14 * 24 * 3600)
        response.delete_cookie(INVITE_COOKIE)
        return response

    @app.get("/{locale}/login/", response_class=HTMLResponse, include_in_schema=False)
    def login_page(request: Request, locale: str):
        return _render(request, templates, locale, page="login", error=None)

    @app.get("/{locale}/recovery/", response_class=HTMLResponse, include_in_schema=False)
    def recovery_page(request: Request, locale: str):
        return _render(request, templates, locale, page="recovery_reset", error=None)

    @app.post("/{locale}/recovery/", response_class=HTMLResponse, include_in_schema=False)
    def recovery(request: Request, locale: str, username: str = Form(...), recovery_code: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
        try:
            _require_csrf(request, csrf_token); session = _session(request)
            try:
                enforce_rate_limit(session, "recovery", username.strip().casefold(), _settings(request).app_session_secret, maximum=5)
                session.commit()
                new_code = reset_password_with_recovery_code(session, username, recovery_code, password)
                if not new_code: raise ValueError("invalid")
                session.commit()
            finally: session.close()
        except RateLimitError:
            return _render(request, templates, locale, page="recovery_reset", error="尝试过于频繁，请 15 分钟后再试。")
        except ValueError:
            return _render(request, templates, locale, page="recovery_reset", error="恢复码、用户名或新密码无效。")
        return _render(request, templates, locale, page="recovery", error=None, recovery_code=new_code, username=username)

    @app.post("/{locale}/login/", response_class=HTMLResponse, include_in_schema=False)
    def login(request: Request, locale: str, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
        try:
            _require_csrf(request, csrf_token)
            session = _session(request)
            try:
                enforce_rate_limit(session, "login", f"{_client_identifier(request)}:{username.strip().casefold()}", _settings(request).app_session_secret, maximum=5)
                session.commit()
                token = create_login_session(session, username, password)
                session.commit()
            finally:
                session.close()
        except RateLimitError:
            return _render(request, templates, locale, page="login", error="尝试过于频繁，请 15 分钟后再试。")
        except (AuthenticationError, ValueError):
            return _render(request, templates, locale, page="login", error="用户名或密码不正确。")
        response = RedirectResponse(url=f"/{resolve_locale(locale)}/dashboard/", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=_settings(request).cookie_secure, max_age=14 * 24 * 3600)
        return response

    @app.get("/{locale}/dashboard/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard(request: Request, locale: str):
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
            if not user:
                return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
            subscription, next_time, jobs = dashboard_summary(session, user.id)
            message = ""
            error = ""
            if request.query_params.get("password_changed") == "1":
                message = "密码已更新，其他登录会话已失效。"
            elif request.query_params.get("cancelled") == "1":
                message = "订阅已取消，未来投递已停止。"
            elif request.query_params.get("password_error") == "1":
                error = "当前密码或新密码无效。"
            elif request.query_params.get("cancel_error") == "1":
                error = "请确认取消订阅后再提交。"
            return _render(request, templates, locale, page="dashboard", error=error, message=message, username=user.username, subscription=subscription, next_time=next_time, jobs=jobs)
        finally:
            session.close()

    @app.post("/{locale}/dashboard/password/", response_class=HTMLResponse, include_in_schema=False)
    def update_password(
        request: Request,
        locale: str,
        current_password: str = Form(...),
        new_password: str = Form(...),
        csrf_token: str = Form(...),
    ):
        try:
            _require_csrf(request, csrf_token)
            session = _session(request)
            try:
                user = current_user(session, request.cookies.get(SESSION_COOKIE))
                if not user:
                    return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
                changed_user = change_password(session, user.id, current_password, new_password)
                token = create_login_session(session, changed_user.username, new_password)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except (AuthenticationError, ValueError):
            return RedirectResponse(url=f"/{resolve_locale(locale)}/dashboard/?password_error=1", status_code=303)
        response = RedirectResponse(url=f"/{resolve_locale(locale)}/dashboard/?password_changed=1", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=_settings(request).cookie_secure, max_age=14 * 24 * 3600)
        return response

    @app.post("/{locale}/dashboard/subscription/", include_in_schema=False)
    def toggle_subscription(request: Request, locale: str, csrf_token: str = Form(...)):
        _require_csrf(request, csrf_token)
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
            if not user: return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
            subscription, _, _ = dashboard_summary(session, user.id)
            if subscription:
                set_subscription_enabled(session, user.id, not subscription.enabled); session.commit()
        finally:
            session.close()
        return RedirectResponse(url=f"/{resolve_locale(locale)}/dashboard/", status_code=303)

    @app.post("/{locale}/dashboard/cancel/", include_in_schema=False)
    def cancel_dashboard_subscription(
        request: Request,
        locale: str,
        confirm_cancel: str = Form(""),
        delete_credentials: str = Form(""),
        csrf_token: str = Form(...),
    ):
        _require_csrf(request, csrf_token)
        if confirm_cancel != "yes":
            return RedirectResponse(url=f"/{resolve_locale(locale)}/dashboard/?cancel_error=1", status_code=303)
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
            if not user:
                return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
            cancel_subscription(session, user.id, delete_credentials=delete_credentials == "yes")
            session.commit()
        finally:
            session.close()
        return RedirectResponse(url=f"/{resolve_locale(locale)}/dashboard/?cancelled=1", status_code=303)

    @app.get("/{locale}/subscription/", response_class=HTMLResponse, include_in_schema=False)
    def subscription_page(request: Request, locale: str):
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
        finally:
            session.close()
        if not user:
            return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
        return render_subscription(request, locale, user)

    @app.post("/{locale}/subscription/", response_class=HTMLResponse, include_in_schema=False)
    async def save_subscription_page(request: Request, locale: str):
        form = await request.form()
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
            if not user:
                return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
            try:
                _require_csrf(request, str(form.get("csrf_token", "")))
                selections = {key.removeprefix("category_"): int(form.get("limit_" + key.removeprefix("category_"), "0")) for key in form.keys() if key.startswith("category_")}
                save_subscription(session, user.id, selections, [str(form.get("time_1", "")), str(form.get("time_2", "")), str(form.get("time_3", ""))])
                session.commit()
            except (SubscriptionValidationError, ValueError):
                session.rollback()
                return render_subscription(request, locale, user, error="配置无效：请检查主题数量、每类条数和发送时间。")
        finally:
            session.close()
        return render_subscription(request, locale, user, saved=True)

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

    def render_destination(request: Request, locale: str, error=None, message=None):
        resolved = resolve_locale(locale)
        csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        response = templates.TemplateResponse(request=request, name="destination.html", context={"locale": resolved, "alternate_locale": alternate_locale(resolved), "text": TRANSLATIONS[resolved], "csrf_token": csrf_token, "error": error, "message": message})
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, csrf_token, httponly=True, samesite="lax", secure=_settings(request).cookie_secure)
        return response

    @app.get("/{locale}/destination/", response_class=HTMLResponse, include_in_schema=False)
    def destination_page(request: Request, locale: str):
        session = _session(request)
        try:
            user = current_user(session, request.cookies.get(SESSION_COOKIE))
        finally:
            session.close()
        if not user:
            return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
        return render_destination(request, locale)

    @app.post("/{locale}/destination/", response_class=HTMLResponse, include_in_schema=False)
    def destination_action(request: Request, locale: str, kind: str = Form(...), webhook: str = Form(...), action: str = Form(...), csrf_token: str = Form(...)):
        try:
            _require_csrf(request, csrf_token)
            session = _session(request)
            try:
                user = current_user(session, request.cookies.get(SESSION_COOKIE))
                if not user:
                    return RedirectResponse(url=f"/{resolve_locale(locale)}/login/", status_code=303)
                if action == "test_and_save":
                    enforce_rate_limit(session, "webhook_test", str(user.id), _settings(request).app_session_secret, maximum=5)
                    session.commit()
                    validate_webhook(kind, webhook)
                    send_test_webhook(kind, webhook)
                    save_destination(session, user.id, kind, webhook, _settings(request).webhook_encryption_key, verified=True)
                    session.commit()
                    return render_destination(request, locale, message="测试成功，Webhook 已加密保存并可用于投递。")
                raise DestinationValidationError("操作无效")
            finally:
                session.close()
        except RateLimitError:
            return render_destination(request, locale, error="测试过于频繁，请 15 分钟后再试。")
        except (DestinationValidationError, ValueError, requests.RequestException):
            return render_destination(request, locale, error="无法完成操作，请检查平台与 Webhook 地址。")
