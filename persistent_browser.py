import json
import os
import threading
import time
from urllib.parse import quote, urlparse, urlunparse

import websocket

BASE_URL = os.getenv("BROWSERLESS_BASE_URL", "").strip().rstrip("/")
TOKEN = (os.getenv("BROWSERLESS_API_KEY", "") or "").strip().strip('"').strip("'").strip("`")

_lock = threading.Lock()
_thread = None
_state = {"connected": False, "started": False, "last_error": "", "target_id": None}


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


def _runner():
    while True:
        ws = None
        try:
            _set(started=True, connected=False, last_error="")
            ws = websocket.create_connection(
                _ws_url(),
                timeout=20,
                origin=BASE_URL,
            )
            _set(connected=True, last_error="")

            # Create DEAN's long-lived working tab and open Google.
            msg_id = 1
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Target.createTarget",
                "params": {"url": "https://www.google.com"}
            }))

            # Wait for our createTarget response, while keeping the browser session attached.
            while True:
                raw = ws.recv()
                if not raw:
                    raise RuntimeError("browser websocket closed")
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                if event.get("id") == msg_id:
                    target_id = ((event.get("result") or {}).get("targetId"))
                    _set(target_id=target_id)
                    break

            # Keep the CDP socket alive indefinitely. Browserless TIMEOUT=-1 means
            # the browser remains alive as long as this socket stays connected.
            while True:
                raw = ws.recv()
                if raw is None:
                    raise RuntimeError("browser websocket closed")
        except Exception as exc:
            _set(connected=False, last_error=f"{type(exc).__name__}: {str(exc)[:180]}")
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
