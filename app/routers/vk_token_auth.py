from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.models.schemas import (
    VkTokenAuthCaptchaBody,
    VkTokenAuthStart,
    VkTokenAuthStatusResponse,
    VkTokenAuthTwoFactorBody,
)
from app.services.vk_token_auth import submit_2fa, submit_captcha, vk_auth_sessions

router = APIRouter(
    prefix="/auth/vk",
    tags=["🔐 Authentication & User"],
)


def _ensure_enabled() -> None:
    if not settings.vk_auth_ui_enabled:
        raise HTTPException(
            status_code=404,
            detail="VK login UI отключён. Задайте VK_AUTH_UI_ENABLED=true в .env",
        )


def _status_payload(session) -> VkTokenAuthStatusResponse:
    return VkTokenAuthStatusResponse(
        session_id=session.id,
        status=session.status,
        captcha_img=session.captcha_img,
        error=session.error,
        token=session.token,
        user_agent=session.user_agent,
    )


@router.get("/", response_class=HTMLResponse)
@router.get("", response_class=HTMLResponse)
async def vk_auth_page():
    """Веб-форма для входа VK (TokenReceiver) и получения токена."""
    _ensure_enabled()
    return HTMLResponse(content=VK_AUTH_HTML)


@router.post("/session", response_model=VkTokenAuthStatusResponse)
async def vk_auth_start(body: VkTokenAuthStart):
    """
    Начать авторизацию по логину/паролю VK ([TokenReceiver](https://issamansur.github.io/vkpymusic/api/tokenreceiver/)).
    Дальше опросите GET `/session/{id}`; при `need_captcha` отправьте ключ на `/session/{id}/captcha`.
    """
    _ensure_enabled()
    session = await vk_auth_sessions.create(
        login=body.login,
        password=body.password,
        client=body.client,
    )
    vk_auth_sessions.spawn_auth_task(session)
    return _status_payload(session)


@router.get("/session/{session_id}", response_model=VkTokenAuthStatusResponse)
async def vk_auth_poll(session_id: str):
    _ensure_enabled()
    session = await vk_auth_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена или истекла")
    return _status_payload(session)


@router.post("/session/{session_id}/captcha", response_model=VkTokenAuthStatusResponse)
async def vk_auth_captcha(session_id: str, body: VkTokenAuthCaptchaBody):
    _ensure_enabled()
    ok = await submit_captcha(session_id, body.key.strip())
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Капча не ожидается или сессия недействительна",
        )
    session = await vk_auth_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return _status_payload(session)


@router.post("/session/{session_id}/2fa", response_model=VkTokenAuthStatusResponse)
async def vk_auth_2fa(session_id: str, body: VkTokenAuthTwoFactorBody):
    _ensure_enabled()
    ok = await submit_2fa(session_id, body.code)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Код 2FA не ожидается или сессия недействительна",
        )
    session = await vk_auth_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return _status_payload(session)


@router.delete("/session/{session_id}")
async def vk_auth_cancel(session_id: str):
    _ensure_enabled()
    deleted = await vk_auth_sessions.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return {"status": "cancelled"}


VK_AUTH_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>VK токен — авторизация</title>
  <style>
    :root { color-scheme: dark; --bg:#121218; --card:#1c1c26; --accent:#5181b8; --text:#e8e8ef; --muted:#9898a8; }
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 1.5rem; line-height: 1.45; }
    h1 { font-size: 1.25rem; margin: 0 0 1rem; font-weight: 600; }
    .card { background: var(--card); border-radius: 12px; padding: 1.25rem; max-width: 420px; margin: 0 auto; }
    label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 0.35rem; }
    input { width: 100%; padding: 0.65rem 0.75rem; border-radius: 8px; border: 1px solid #333; background: #0e0e14; color: var(--text); margin-bottom: 0.9rem; }
    button { background: var(--accent); color: #fff; border: none; padding: 0.65rem 1rem; border-radius: 8px; cursor: pointer; font-weight: 600; width: 100%; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .note { font-size: 0.8rem; color: var(--muted); margin-top: 1rem; }
    .err { color: #e57373; font-size: 0.9rem; margin-top: 0.5rem; }
    .ok { margin-top: 1rem; padding: 0.75rem; background: #1a2e1a; border-radius: 8px; word-break: break-all; font-size: 0.85rem; }
    .cap img { max-width: 100%; border-radius: 8px; margin: 0.5rem 0; }
    .row { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-end; }
    .row input { margin-bottom: 0; flex: 1; min-width: 120px; }
    .row button { width: auto; min-width: 120px; }
    .status { font-size: 0.85rem; color: var(--muted); margin-bottom: 0.75rem; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Авторизация VK (для токена API)</h1>
    <p class="status" id="st">Введите данные аккаунта ВКонтакте.</p>
    <form id="f">
      <label for="login">Телефон или email</label>
      <input id="login" name="login" autocomplete="username" required />
      <label for="password">Пароль</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button type="submit" id="go">Войти</button>
    </form>
    <div id="cap" class="cap" style="display:none;">
      <label>Капча</label>
      <div id="capImg"></div>
      <div class="row">
        <input id="capKey" placeholder="Текст с картинки" />
        <button type="button" id="capBtn">Отправить</button>
      </div>
    </div>
    <div id="twofa" style="display:none;">
      <label>Код подтверждения (SMS / приложение)</label>
      <div class="row">
        <input id="twofaCode" placeholder="Код" />
        <button type="button" id="twofaBtn">Отправить</button>
      </div>
    </div>
    <div id="err" class="err" style="display:none;"></div>
    <div id="success" class="ok" style="display:none;"></div>
    <p class="note">Используйте только свой аккаунт. Токен и User-Agent можно скопировать в .env (<code>VK_TOKEN</code>, <code>VK_USER_AGENT</code>). Сессии хранятся в памяти сервера и истекают через 30 минут.</p>
  </div>
<script>
const api = (path, opt) => fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opt));
let sid = null;
let pollTimer = null;

function showErr(t) {
  const e = document.getElementById('err');
  e.textContent = t || '';
  e.style.display = t ? 'block' : 'none';
}
function setStatus(t) { document.getElementById('st').textContent = t; }

async function poll() {
  if (!sid) return;
  const r = await fetch('/api/auth/vk/session/' + sid);
  if (!r.ok) return;
  const j = await r.json();
  showErr('');
  setStatus('Статус: ' + j.status);
  document.getElementById('cap').style.display = j.status === 'need_captcha' ? 'block' : 'none';
  document.getElementById('twofa').style.display = j.status === 'need_2fa' ? 'block' : 'none';
  if (j.status === 'need_captcha' && j.captcha_img) {
    document.getElementById('capImg').innerHTML = '<img src="' + j.captcha_img + '" alt="captcha" />';
  }
  if (j.status === 'success' && j.token) {
    clearInterval(pollTimer);
    document.getElementById('f').style.display = 'none';
    document.getElementById('cap').style.display = 'none';
    document.getElementById('twofa').style.display = 'none';
    document.getElementById('success').style.display = 'block';
    document.getElementById('success').innerHTML =
      '<strong>Готово.</strong><br/><br/>VK_TOKEN:<br/><code>' + j.token + '</code><br/><br/>VK_USER_AGENT:<br/><code>' + (j.user_agent || '') + '</code>';
    setStatus('Успех');
  }
  if (j.status === 'failed' || j.status === 'cancelled') {
    clearInterval(pollTimer);
    showErr(j.error || j.status);
    document.getElementById('go').disabled = false;
  }
}

document.getElementById('f').onsubmit = async (ev) => {
  ev.preventDefault();
  showErr('');
  document.getElementById('go').disabled = true;
  const login = document.getElementById('login').value.trim();
  const password = document.getElementById('password').value;
  const res = await api('/api/auth/vk/session', {
    method: 'POST',
    body: JSON.stringify({ login, password, client: 'Kate' }),
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) {
    showErr(j.detail || 'Ошибка запуска сессии');
    document.getElementById('go').disabled = false;
    return;
  }
  sid = j.session_id;
  setStatus('Статус: ' + j.status);
  pollTimer = setInterval(poll, 1000);
  poll();
};

document.getElementById('capBtn').onclick = async () => {
  const key = document.getElementById('capKey').value.trim();
  if (!key || !sid) return;
  const res = await api('/api/auth/vk/session/' + sid + '/captcha', {
    method: 'POST',
    body: JSON.stringify({ key }),
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) showErr(j.detail || 'Ошибка капчи');
  document.getElementById('capKey').value = '';
};

document.getElementById('twofaBtn').onclick = async () => {
  const code = document.getElementById('twofaCode').value.trim();
  if (!code || !sid) return;
  const res = await api('/api/auth/vk/session/' + sid + '/2fa', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) showErr(j.detail || 'Ошибка кода');
  document.getElementById('twofaCode').value = '';
};
</script>
</body>
</html>
"""
