import base64
import functools
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
_page_lock = threading.RLock()
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
    "current_url": "about:blank",
    "frame_at": 0,
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
        out = dict(_state)
        frame_at = float(out.get("frame_at") or 0)
        frame_age = (time.time() - frame_at) if frame_at else None
        out["frame_age"] = round(frame_age, 2) if frame_age is not None else None
        if frame_age is None or frame_age > 4.0:
            out["viewer_ready"] = False
        out["frame_fresh"] = bool(frame_age is not None and frame_age <= 4.0)
        return out


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
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
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


def _serialized_page_action(action):
    @functools.wraps(action)
    def run(*args, **kwargs):
        # Chromium's screenshot can stall if navigation replaces the renderer
        # while capture is in flight. Keep page-changing actions separate.
        if not _cdp_session_id and not wait_until_ready(30):
            return False
        with _page_lock:
            if not _cdp_session_id:
                _set(last_error="browser_disconnected")
                return False
            result = action(*args, **kwargs)
            if result:
                _settle_page()
            return result
    return run


def _settle_page():
    time.sleep(.25)
    try:
        with _lock:
            target_id = _state.get("target_id")
        if target_id:
            _send_wait("Target.activateTarget", {"targetId": target_id}, timeout=10)
        _send_wait("Page.bringToFront", {}, _cdp_session_id, timeout=10)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if evaluate_js("document.readyState") == "complete":
                return
            time.sleep(.25)
    except Exception:
        # Action success remains independently verified by its own CDP reply.
        # The receiver/capture worker will report a connection failure if any.
        return


def _runner():
    global _ws, _cdp_session_id, _latest_frame
    while True:
        ws = None
        try:
            with _lock:
                _latest_frame = None
            _set(started=True, connected=False, viewer_ready=False, target_id=None, current_url="https://dean-agent-5y18.onrender.com/browser-start", frame_at=0, last_error="")
            # Wake the HTTP service before attempting a WebSocket handshake.
            wake_browser_service()
            ws = websocket.create_connection(_ws_url(), timeout=30, origin=BASE_URL)
            # Initialization must time out too; an unresponsive socket must not
            # trap this only reconnect thread forever.
            ws.settimeout(2.0)
            _ws = ws
            _set(connected=True, last_error="")

            create_id = _send("Target.createTarget", {"url": "https://dean-agent-5y18.onrender.com/browser-start"})
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
            _send("Page.bringToFront", {}, session_id)
            ws.settimeout(2.0)
            _set(viewer_ready=False)

            # One receiver continuously dispatches CDP replies. Screenshot
            # requests run separately so a slow capture cannot stall user replies.
            threading.Thread(target=_capture_frames, args=(ws, session_id),
                             daemon=True, name="dean-browser-frames").start()
            while True:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    raise RuntimeError("browser websocket closed")
                event = json.loads(raw)
                _dispatch_pending(event)
                params = event.get("params") or {}
                if event.get("method") == "Page.frameNavigated":
                    frame_info = params.get("frame") or {}
                    if not frame_info.get("parentId") and frame_info.get("url"):
                        _set(current_url=str(frame_info["url"]))
                elif event.get("method") == "Page.navigatedWithinDocument" and params.get("url"):
                    _set(current_url=str(params["url"]))
        except Exception as exc:
            with _lock:
                _latest_frame = None
            _set(connected=False, viewer_ready=False, target_id=None, frame_at=0, last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
            _ws = None
            _cdp_session_id = None
            with _pending_lock:
                for item in _pending.values():
                    item["response"] = {"error": {"message": "browser_disconnected"}}
                    item["event"].set()
            try:
                if ws:
                    ws.close()
            except Exception:
                pass
            time.sleep(3)


def _capture_frames(ws, session_id):
    global _latest_frame
    failed_since = None
    while _ws is ws:
        try:
            with _page_lock:
                if _ws is not ws:
                    return
                # Cross-site navigation can replace the renderer. Keep this page
                # in the foreground before asking Chromium for its visible surface.
                with _lock:
                    target_id = _state.get("target_id")
                if target_id:
                    _send_wait("Target.activateTarget", {"targetId": target_id}, timeout=10)
                _send_wait("Page.bringToFront", {}, session_id, timeout=10)
                result = _send_wait("Page.captureScreenshot", {
                    "format": "jpeg", "quality": 60, "fromSurface": True,
                    "captureBeyondViewport": False,
                }, session_id, timeout=30).get("result") or {}
                data = result.get("data")
                if not data:
                    raise RuntimeError("screenshot_empty")
                frame = base64.b64decode(data, validate=True)
                if not frame:
                    raise RuntimeError("screenshot_empty")
                with _lock:
                    if _ws is not ws:
                        return
                    _latest_frame = frame
                    _state.update(viewer_ready=True, frame_at=time.time(), last_error="")
                failed_since = None
            time.sleep(1)
        except Exception as exc:
            if _ws is ws:
                _set(viewer_ready=False, last_error="screenshot: " + type(exc).__name__)
                # Chromium can reject capture briefly during navigation/reload.
                # A capture error alone must not destroy the user's whole page.
                if isinstance(exc, RuntimeError):
                    if failed_since is None:
                        failed_since = time.monotonic()
                        print("BROWSER_FRAME_RETRY", str(exc)[:180], flush=True)
                    if time.monotonic() - failed_since < 30:
                        time.sleep(1)
                        continue
                print("BROWSER_FRAME_RECONNECT", type(exc).__name__, str(exc)[:180], flush=True)
                try:
                    ws.close()
                except Exception:
                    pass
            return


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
    # The reconnect thread performs wake-up. Do not block every user action
    # behind an extra HTTP request when the existing connection is ready.
    deadline = time.monotonic() + max(1, float(timeout))
    while time.monotonic() < deadline:
        with _lock:
            ready = bool(_state.get("connected") and _state.get("viewer_ready")
                         and _cdp_session_id and time.time() - _state.get("frame_at", 0) <= 4.0)
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
        frame = _latest_frame
        frame_at = float(_state.get("frame_at") or 0)
    if not frame or not frame_at or (time.time() - frame_at) > 4.0:
        return None
    return frame


@_serialized_page_action
def navigate(url):
    if not url:
        return False
    value = str(url).strip()
    if not value.startswith(("http://", "https://", "data:")):
        value = "https://" + value
    if not _cdp_session_id and not wait_until_ready(30):
        return False
    try:
        r = _send_wait("Page.navigate", {"url": value}, _cdp_session_id, timeout=30)
        result = r.get("result") or {}
        if result.get("errorText"):
            _set(last_error=str(result.get("errorText"))[:180])
            return False
        # Verify that Chromium actually moved to the requested destination.
        expected = value
        expected_host = urlparse(expected).netloc.lower() if expected.startswith(("http://","https://")) else ""
        deadline = time.time() + 10
        actual = ""
        matched = False
        while time.time() < deadline:
            actual = str(evaluate_js("location.href") or "")
            if expected.startswith("data:") and actual.startswith("data:"):
                matched = True
                break
            if expected_host:
                actual_host = urlparse(actual).netloc.lower() if actual.startswith(("http://","https://")) else ""
                if actual_host and (
                    actual_host == expected_host
                    or actual_host.endswith("." + expected_host)
                    or expected_host.endswith("." + actual_host)
                ):
                    matched = True
                    break
            elif actual == expected:
                matched = True
                break
            time.sleep(0.25)
        if not matched:
            _set(current_url=actual or _state.get("current_url",""), last_error="navigation_not_verified")
            return False
        _set(current_url=actual, last_error="")
        return True
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return False


@_serialized_page_action
def reload_page():
    if not _cdp_session_id and not wait_until_ready(20):
        return False
    try:
        _send_wait("Page.reload", {"ignoreCache": False}, _cdp_session_id, 10)
        deadline = time.time() + 8
        while time.time() < deadline:
            actual = str(evaluate_js("location.href") or "")
            if actual:
                _set(current_url=actual)
                return True
            time.sleep(0.2)
        _set(last_error="reload_not_verified")
        return False
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return False


@_serialized_page_action
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
        }, _cdp_session_id, 20)
        result = ((r.get("result") or {}).get("result") or {})
        if result.get("subtype") == "error":
            return None
        return result.get("value")
    except Exception as exc:
        _set(last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
        return None


@_serialized_page_action
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


@_serialized_page_action
def press_key(key):
    if not _cdp_session_id and not wait_until_ready(20):
        return False
    key = str(key)
    try:
        if key == "Enter":
            params={"key":"Enter","code":"Enter","windowsVirtualKeyCode":13,"nativeVirtualKeyCode":13}
            _send_wait("Input.dispatchKeyEvent", {"type":"rawKeyDown", **params}, _cdp_session_id, 8)
            _send_wait("Input.dispatchKeyEvent", {"type":"char","text":"\r","unmodifiedText":"\r", **params}, _cdp_session_id, 8)
            _send_wait("Input.dispatchKeyEvent", {"type":"keyUp", **params}, _cdp_session_id, 8)
        else:
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
