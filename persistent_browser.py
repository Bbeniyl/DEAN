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
    return urlunparse((scheme, host, "/chromium", "", f"token={quote(TOKEN, safe='')}", ""))


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
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    sid = _cdp_session_id
    if not sid:
        return False
    _send("Page.navigate", {"url": value}, sid)
    return True


def click(x, y):
    sid = _cdp_session_id
    if not sid:
        return False
    x = float(x)
    y = float(y)
    _send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1}, sid)
    _send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1}, sid)
    return True


def type_text(text):
    sid = _cdp_session_id
    if not sid:
        return False
    _send("Input.insertText", {"text": str(text)}, sid)
    return True


def press_key(key):
    sid = _cdp_session_id
    if not sid:
        return False
    key = str(key)
    _send("Input.dispatchKeyEvent", {"type": "keyDown", "key": key}, sid)
    _send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key}, sid)
    return True
