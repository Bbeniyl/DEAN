import os
import requests

# Compatibility module: DEAN historically imported this file as steel_client.
# The active provider is now Browserless.
BASE_URL = os.getenv("BROWSERLESS_BASE_URL", "https://production-sfo.browserless.io").rstrip("/")


def api_key():
    return (os.getenv("BROWSERLESS_API_KEY", "") or "").strip().strip('"').strip("'").strip("`")


def configured():
    return bool(api_key())


def _bql(query, timeout=30):
    key = api_key()
    if not key:
        return None, {"ok": False, "error": "browserless_not_configured"}
    try:
        r = requests.post(
            f"{BASE_URL}/chromium/bql",
            params={"token": key},
            headers={"Content-Type": "application/json"},
            json={"query": query},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, {"ok": False, "error": "browserless_request_failed", "message": str(exc)}
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {"message": (r.text or "")[:500]}
    if not r.ok:
        return r, {"ok": False, "status_code": r.status_code, "error": data}
    if data.get("errors"):
        return r, {"ok": False, "status_code": r.status_code, "error": data.get("errors")}
    return r, data


def create_session():
    # Free Browserless plans cap reconnect timeout at 10 seconds.
    query = """mutation StartDeanSession {
      goto(url: "https://www.google.com", waitUntil: domContentLoaded) { status }
      reconnect(timeout: 10000) {
        browserQLEndpoint
        browserWSEndpoint
        devtoolsFrontendUrl
        webSocketDebuggerUrl
      }
    }"""
    r, data = _bql(query, timeout=30)
    if r is None or not isinstance(data, dict) or data.get("ok") is False:
        return data if isinstance(data, dict) else {"ok": False, "error": "browserless_unknown_error"}
    rec = ((data.get("data") or {}).get("reconnect") or {})
    debug_url = rec.get("devtoolsFrontendUrl")
    return {
        "ok": True,
        "session_id": (rec.get("browserQLEndpoint") or "").rstrip("/").split("/")[-1] or None,
        "debug_url": debug_url,
        "browserql_endpoint": rec.get("browserQLEndpoint"),
        "browser_ws_endpoint": rec.get("browserWSEndpoint"),
        "viewer_ready": bool(debug_url),
        "provider": "browserless",
    }


def validate_key():
    key = api_key()
    if not key:
        return {"configured": False, "authenticated": False, "status_code": None, "provider": "browserless"}
    # A minimal BQL query verifies the token without logging or returning it.
    query = """query DeanBrowserlessHealth { version }"""
    r, data = _bql(query, timeout=15)
    if r is None:
        return {
            "configured": True,
            "authenticated": False,
            "status_code": None,
            "provider": "browserless",
            "error": (data or {}).get("message") or (data or {}).get("error"),
        }
    return {
        "configured": True,
        "authenticated": bool(r.ok and isinstance(data, dict) and not data.get("errors")),
        "status_code": r.status_code,
        "provider": "browserless",
        "error": data.get("errors") if isinstance(data, dict) and data.get("errors") else None,
    }
