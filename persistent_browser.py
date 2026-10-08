import base64
import json
import os
import threading
import time
from urllib.parse import quote, urlparse, urlunparse

import websocket

BASE_URL = os.getenv("BROWSERLESS_BASE_URL", "").strip().rstrip("/")
TOKEN = (os.getenv("BROWSERLESS_API_KEY", "") or "").strip().strip('"').strip("'").strip("`")

_lock = threading.Lock()
_send_lock = threading.Lock()
_pending_lock = threading.Lock()
_pending = {}
_thread = None
_ws = None
_cdp_session_id = None
_next_id = 10
_latest_frame = None
_state = {
    "connected": False,
    "started": False,
    "last_error": "",
    "target_id": None,
    "viewer_ready": False,
}


def _is_self_hosted():
    return bool(BASE_URL) and "browserless.io" not in BASE_URL and "production-" not in BASE_URL


def _ws_url():
    p = urlparse(BASE_URL)
    scheme = "wss" if p.scheme == "https" else "ws"
    host = p.netloc or p.path
    return urlunparse((scheme, host, "/chromium", "", f"token={quote(TOKEN, safe='')}&timeout=86400000", ""))


def status():
    with _lock:
        return dict(_state)


def _set(**kwargs):
    with _lock:
        _state.update(kwargs)


def _new_id():
    global _next_id
    with _lock:
        _next_id += 1
        return _next_id


def _send(method, params=None, session_id=None):
    global _ws
    ws = _ws
    if not ws:
        raise RuntimeError("browser_not_connected")
    msg = {"id": _new_id(), "method": method, "params": params or {}}
    if session_id:
        msg["sessionId"] = session_id
    with _send_lock:
        ws.send(json.dumps(msg))
    return msg["id"]


def _wait_for_response(ws, wanted_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ws.recv()
        if not raw:
            raise RuntimeError("browser websocket closed")
        event = json.loads(raw)
        if event.get("id") == wanted_id:
            return event
    raise TimeoutError("cdp response timeout")


def _dispatch_pending(event):
    rid = event.get("id") if isinstance(event, dict) else None
    if rid is None:
        return False
    with _pending_lock:
        item = _pending.get(rid)
        if not item:
            return False
        item["response"] = event
        item["event"].set()
        return True


def _send_wait(method, params=None, session_id=None, timeout=10):
    global _ws
    ws = _ws
    if not ws:
        raise RuntimeError("browser_not_connected")
    rid = _new_id()
    waiter = threading.Event()
    with _pending_lock:
        _pending[rid] = {"event": waiter, "response": None}
    msg = {"id": rid, "method": method, "params": params or {}}
    if session_id:
        msg["sessionId"] = session_id
    try:
        with _send_lock:
            ws.send(json.dumps(msg))
        if not waiter.wait(timeout):
            raise TimeoutError(f"cdp timeout: {method}")
        with _pending_lock:
            item = _pending.pop(rid, None)
        response = (item or {}).get("response") or {}
        if response.get("error"):
            raise RuntimeError(str(response.get("error"))[:180])
        return response
    finally:
        with _pending_lock:
            _pending.pop(rid, None)


def _runner():
    global _ws, _cdp_session_id, _latest_frame
    while True:
        ws = None
        try:
            _set(started=True, connected=False, viewer_ready=False, last_error="")
            ws = websocket.create_connection(_ws_url(), timeout=30, origin=BASE_URL)
            ws.settimeout(None)
            _ws = ws
            _set(connected=True, last_error="")

            create_id = _send("Target.createTarget", {"url": "https://www.google.com"})
            created = _wait_for_response(ws, create_id)
            target_id = ((created.get("result") or {}).get("targetId"))
            if not target_id:
                raise RuntimeError("target_not_created")
            _set(target_id=target_id)

            attach_id = _send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
            attached = _wait_for_response(ws, attach_id)
            session_id = ((attached.get("result") or {}).get("sessionId"))
            if not session_id:
                raise RuntimeError("target_not_attached")
            _cdp_session_id = session_id

            # Fixed viewport makes taps in the iPad viewer line up with the remote page.
            _send("Emulation.setDeviceMetricsOverride", {
                "width": 1024, "height": 700, "deviceScaleFactor": 1, "mobile": False
            }, session_id)
            _send("Page.enable", {}, session_id)
            _set(viewer_ready=True)

            # Capture the real shared page repeatedly. This is more reliable on
            # Render/iPad than CDP screencast events and still uses the same tab.
            while True:
                shot_id = _send("Page.captureScreenshot", {
                    "format": "jpeg",
                    "quality": 70,
                    "fromSurface": True,
                    "captureBeyondViewport": False
                }, session_id)
                deadline = time.time() + 12
                while time.time() < deadline:
                    raw = ws.recv()
                    if not raw:
                        raise RuntimeError("browser websocket closed")
                    try:
                        event = json.loads(raw)
                    except Exception:
                        continue
                    _dispatch_pending(event)
                    if event.get("id") == shot_id:
                        data = ((event.get("result") or {}).get("data"))
                        if data:
                            try:
                                frame = base64.b64decode(data)
                                with _lock:
                                    _latest_frame = frame
                            except Exception:
                                pass
                        break
                time.sleep(0.65)
        except Exception as exc:
            _set(connected=False, viewer_ready=False, last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
            _ws = None
            _cdp_session_id = None
            try:
                if ws:
                    ws.close()
            except Exception:
                pass
            time.sleep(3)


def wake_browser_service():
    """Wake the Browserless web service without exposing the token."""
    try:
        import requests as _requests
        if not BASE_URL or not TOKEN:
            return False
        r = _requests.get(BASE_URL + "/active", params={"token": TOKEN}, timeout=20)
        return r.status_code < 500
    except Exception:
        return False


def wait_until_ready(timeout=25):
    ensure_started()
    # Trigger Render wake-up immediately if the browser service is sleeping.
    wake_browser_service()
    deadline = time.time() + max(1, float(timeout))
    while time.time() < deadline:
        with _lock:
            ready = bool(_state.get("connected") and _state.get("viewer_ready") and _cdp_session_id)
        if ready:
            return True
        time.sleep(0.5)
    return False


def ensure_started():
    global _thread
    if not _is_self_hosted() or not TOKEN:
        return False
    with _lock:
        if _thread and _thread.is_alive():
            return True
        _thread = threading.Thread(target=_runner, daemon=True, name="dean-persistent-browser")
        _thread.start()
        return True


def latest_frame():
    with _lock:
        return _latest_frame


def navigate(url):
    if not url:
        return False
    value = str(url).strip()
    if not value.startswith(("http://", "https://", "data:")):
        value = "https://" + value
    if not _cdp_session_id and not wait_until_ready(30):
        return False
    try:
        r = _send_wait("Page.navigate", {"url": value}, _cdp_session_id, timeout=12)
        result = r.get("result") or {}
        if result.get("errorText"):
            _set(last_error=str(result.get("errorText"))[:180])
            return False
        return True
    except Exception as exc:
        _set(connected=False, viewer_ready=False, last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return False


def click(x, y):
    if not _cdp_session_id and not wait_until_ready(20):
        return False
    try:
        x = float(x); y = float(y)
        _send_wait("Input.dispatchMouseEvent", {"type":"mousePressed","x":x,"y":y,"button":"left","clickCount":1}, _cdp_session_id, 8)
        _send_wait("Input.dispatchMouseEvent", {"type":"mouseReleased","x":x,"y":y,"button":"left","clickCount":1}, _cdp_session_id, 8)
        return True
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return False


def scroll_by(delta_x=0, delta_y=0, x=512, y=350):
    if not _cdp_session_id and not wait_until_ready(20):
        return False
    try:
        _send_wait("Input.dispatchMouseEvent", {
            "type":"mouseWheel","x":float(x),"y":float(y),
            "deltaX":float(delta_x),"deltaY":float(delta_y),
        }, _cdp_session_id, 8)
        return True
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return False


def evaluate_js(expression):
    if not _cdp_session_id and not wait_until_ready(30):
        return None
    try:
        r = _send_wait("Runtime.evaluate", {
            "expression":str(expression),
            "userGesture":True,
            "awaitPromise":True,
            "returnByValue":True,
        }, _cdp_session_id, 10)
        result = ((r.get("result") or {}).get("result") or {})
        if result.get("subtype") == "error":
            return None
        return result.get("value")
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return None


def click_text(text):
    needle = str(text or "").strip()
    if not needle:
        return False
    js_needle = json.dumps(needle)
    expression = f"""
(() => {{
  const needle = {js_needle}.trim().toLowerCase();
  const els = Array.from(document.querySelectorAll(
    'a,button,[role="button"],input[type="button"],input[type="submit"],summary,label'
  ));
  const visible = el => {{
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  }};
  const txt = el => (
    el.innerText || el.textContent || el.value ||
    el.getAttribute('aria-label') || el.getAttribute('title') || ''
  ).trim().toLowerCase();
  let el = els.find(e => visible(e) && txt(e) === needle);
  if (!el) el = els.find(e => visible(e) && txt(e).includes(needle));
  if (!el) return false;
  el.scrollIntoView({{block:'center', inline:'center'}});
  el.click();
  return true;
}})()
"""
    return evaluate_js(expression) is True


def type_text(text):
    if not _cdp_session_id and not wait_until_ready(20):
        return False
    try:
        _send_wait("Input.insertText", {"text":str(text)}, _cdp_session_id, 8)
        return True
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return False


def press_key(key):
    if not _cdp_session_id and not wait_until_ready(20):
        return False
    key = str(key)
    try:
        _send_wait("Input.dispatchKeyEvent", {"type":"keyDown","key":key}, _cdp_session_id, 8)
        _send_wait("Input.dispatchKeyEvent", {"type":"keyUp","key":key}, _cdp_session_id, 8)
        return True
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return False


def _keep_browser_service_awake():
    """Keep the free Render browser service warm so its Chromium session does not hibernate."""
    import requests as _requests
    while True:
        try:
            if BASE_URL and TOKEN:
                _requests.get(
                    BASE_URL + "/active",
                    params={"token": TOKEN},
                    timeout=12,
                )
        except Exception:
            pass
        time.sleep(60)


def start_keepalive():
    t = threading.Thread(target=_keep_browser_service_awake, daemon=True, name="dean-browser-keepalive")
    t.start()
    return True
