"""
OAuth 2.0 авторизация VK API: redirect на oauth.vk.com и обмен code → access_token.
Документация: https://dev.vk.com/api/access-token/authcode-flow-user
"""
from __future__ import annotations

import html
from urllib.parse import urlencode

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import settings
from app.services.vk_oauth_state import create_state, verify_and_consume

router = APIRouter(
    prefix="/auth/vk-oauth",
    tags=["🔐 Authentication & User"],
)

VK_AUTHORIZE_URL = "https://oauth.vk.com/authorize"
VK_ACCESS_TOKEN_URL = "https://oauth.vk.com/access_token"


def _oauth_config_ok() -> bool:
    return bool(
        settings.vk_oauth_client_id.strip()
        and settings.vk_oauth_client_secret.strip()
        and settings.vk_oauth_redirect_uri.strip()
    )


def _ensure_oauth_ui() -> None:
    if not settings.vk_oauth_ui_enabled:
        raise HTTPException(
            status_code=404,
            detail="VK OAuth отключён. Задайте VK_OAUTH_UI_ENABLED=true и параметры приложения VK.",
        )


@router.get("/", response_class=HTMLResponse)
@router.get("", response_class=HTMLResponse)
async def vk_oauth_landing():
    """Страница «Войти через VK» (OAuth)."""
    _ensure_oauth_ui()
    if not _oauth_config_ok():
        return HTMLResponse(
            status_code=503,
            content=MISSING_CONFIG_HTML,
        )
    return HTMLResponse(content=LANDING_HTML)


@router.get("/start")
async def vk_oauth_start(request: Request):
    """Редирект на страницу подтверждения прав VK."""
    _ensure_oauth_ui()
    if not _oauth_config_ok():
        raise HTTPException(
            status_code=503,
            detail="Заполните VK_OAUTH_CLIENT_ID, VK_OAUTH_CLIENT_SECRET и VK_OAUTH_REDIRECT_URI",
        )
    state = create_state()
    params = {
        "client_id": settings.vk_oauth_client_id.strip(),
        "display": "page",
        "redirect_uri": settings.vk_oauth_redirect_uri.strip(),
        "scope": settings.vk_oauth_scope.strip(),
        "response_type": "code",
        "v": "5.131",
        "state": state,
    }
    url = f"{VK_AUTHORIZE_URL}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", response_class=HTMLResponse)
async def vk_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """Обработка ответа VK после согласия пользователя."""
    _ensure_oauth_ui()
    if not _oauth_config_ok():
        return HTMLResponse(status_code=503, content=MISSING_CONFIG_HTML)

    if error:
        msg = html.escape(error_description or error)
        return HTMLResponse(
            content=ERROR_HTML.format(message=msg),
            status_code=400,
        )

    if not code:
        raise HTTPException(status_code=400, detail="Параметр code отсутствует")

    if not verify_and_consume(state):
        raise HTTPException(status_code=400, detail="Неверный или просроченный state")

    params = {
        "client_id": settings.vk_oauth_client_id.strip(),
        "client_secret": settings.vk_oauth_client_secret.strip(),
        "redirect_uri": settings.vk_oauth_redirect_uri.strip(),
        "code": code,
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(VK_ACCESS_TOKEN_URL, params=params) as resp:
            data = await resp.json(content_type=None)

    if isinstance(data, dict) and data.get("error"):
        err = data.get("error_description") or data.get("error")
        return HTMLResponse(
            content=ERROR_HTML.format(message=html.escape(str(err))),
            status_code=400,
        )

    token = data.get("access_token", "")
    uid = data.get("user_id", "")
    expires = data.get("expires_in", "")
    scope = data.get("scope", "")
    return HTMLResponse(
        content=SUCCESS_HTML.format(
            token=html.escape(str(token)),
            user_id=html.escape(str(uid)),
            expires_in=html.escape(str(expires)),
            scope=html.escape(str(scope)),
        )
    )


LANDING_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Вход через VK (OAuth)</title>
  <style>
    :root { color-scheme: dark; --bg:#121218; --card:#1c1c26; --accent:#5181b8; --text:#e8e8ef; --muted:#9898a8; }
    body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 1.5rem; line-height: 1.5; }
    .card { background: var(--card); border-radius: 12px; padding: 1.25rem; max-width: 480px; margin: 0 auto; }
    h1 { font-size: 1.2rem; margin: 0 0 0.75rem; }
    p { color: var(--muted); font-size: 0.9rem; margin: 0.5rem 0; }
    a.btn { display: inline-block; background: var(--accent); color: #fff; text-decoration: none; padding: 0.65rem 1.25rem; border-radius: 8px; font-weight: 600; margin-top: 0.75rem; }
    code { font-size: 0.8rem; word-break: break-all; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Вход через VK</h1>
    <p>Откроется страница VK: войдите и разрешите доступ приложению. После этого вы вернётесь сюда и получите <strong>access_token</strong> для API.</p>
    <p>В настройках приложения VK укажите тот же <strong>Redirect URI</strong>, что в переменной <code>VK_OAUTH_REDIRECT_URI</code> (например <code>…/api/auth/vk-oauth/callback</code>).</p>
    <a class="btn" href="/api/auth/vk-oauth/start">Продолжить с VK</a>
  </div>
</body>
</html>
"""

MISSING_CONFIG_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/><title>VK OAuth</title></head>
<body style="font-family:system-ui;padding:2rem;background:#121218;color:#e8e8ef;">
<p>Задайте в .env: <code>VK_OAUTH_CLIENT_ID</code>, <code>VK_OAUTH_CLIENT_SECRET</code>, <code>VK_OAUTH_REDIRECT_URI</code>.</p>
</body></html>
"""

ERROR_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"/><title>Ошибка VK</title></head>
<body style="font-family:system-ui;padding:2rem;background:#121218;color:#e57373;">
<p><strong>Не удалось авторизоваться</strong></p>
<p>{message}</p>
<p><a href="./" style="color:#8ebfff;">Назад</a></p>
</body></html>
"""

SUCCESS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Токен получен</title>
  <style>
    :root {{ color-scheme: dark; --bg:#121218; --card:#1c1c26; --text:#e8e8ef; --muted:#9898a8; }}
    body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 1.5rem; }}
    .card {{ background: var(--card); border-radius: 12px; padding: 1.25rem; max-width: 560px; margin: 0 auto; }}
    code {{ display: block; background: #0e0e14; padding: 0.75rem; border-radius: 8px; word-break: break-all; font-size: 0.82rem; margin: 0.5rem 0; }}
    .muted {{ color: var(--muted); font-size: 0.9rem; }}
    a {{ color: #8ebfff; }}
  </style>
</head>
<body>
  <div class="card">
    <h1 style="font-size:1.2rem;">Авторизация успешна</h1>
    <p class="muted">Скопируйте значение в <code>VK_TOKEN</code> в .env (если подходят запрошенные права).</p>
    <p><strong>user_id:</strong> {user_id}</p>
    <p><strong>expires_in:</strong> {expires_in}</p>
    <p><strong>scope:</strong> {scope}</p>
    <p><strong>access_token</strong></p>
    <code id="t">{token}</code>
    <p><a href="./">← К началу</a></p>
  </div>
</body>
</html>
"""
