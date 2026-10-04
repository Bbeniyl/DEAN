import os
import requests
from urllib.parse import quote

# Compatibility module: DEAN historically imported this file as steel_client.
# The active provider is Browserless.
BASE_URL = os.getenv("BROWSERLESS_BASE_URL", "https://production-sfo.browserless.io").rstrip("/")


def api_key():
    return (os.getenv("BROWSERLESS_API_KEY", "") or "").strip().strip('"').strip("'").strip("`")


def configured():
    return bool(api_key())


def _is_self_hosted():
    return "production-" not in BASE_URL and "browserless.io" not in BASE_URL


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
    key = api_key()
    if not key:
        return {"ok": False, "error": "browserless_not_configured"}

    # Self-hosted Browserless Docker ships with its own interactive Live Debugger.
    # Do not use BrowserQL here: the open-source self-hosted container does not
    # expose the hosted /chromium/bql endpoint.
    if _is_self_hosted():
        live_url = f"{BASE_URL}/debugger/?token={quote(key, safe='')}"
        return {
            "ok": True,
            "session_id": None,
            "debug_url": live_url,
            "live_url": live_url,
            "viewer_ready": True,
            "viewer_timeout_ms": None,
            "provider": "browserless-self-hosted",
        }

    # Browserless Cloud supports BrowserQL + liveURL.
    query = """mutation StartDeanSession {
      goto(url: "https://www.google.com", waitUntil: domContentLoaded) { status }
      liveURL(interactable: true, showBrowserInterface: true, resizable: true, quality: 70, timeout: 120000) {
        liveURL
        timeout
      }
    }"""
    r, data = _bql(query, timeout=30)
    if r is None or not isinstance(data, dict) or data.get("ok") is False:
        return data if isinstance(data, dict) else {"ok": False, "error": "browserless_unknown_error"}
    live = ((data.get("data") or {}).get("liveURL") or {})
    live_url = live.get("liveURL")
    if not live_url:
        return {"ok": False, "error": "browserless_live_url_missing", "response": data}
    return {
        "ok": True,
        "session_id": live.get("liveURLId"),
        "debug_url": live_url,
        "live_url": live_url,
        "viewer_ready": True,
        "viewer_timeout_ms": live.get("timeout"),
        "provider": "browserless",
    }


def validate_key():
    key = api_key()
    if not key:
        return {"configured": False, "authenticated": False, "status_code": None, "provider": "browserless"}

    if _is_self_hosted():
        try:
            r = requests.get(
                f"{BASE_URL}/json/version",
                params={"token": key},
                timeout=15,
            )
            return {
                "configured": True,
                "authenticated": bool(r.ok),
                "status_code": r.status_code,
                "provider": "browserless-self-hosted",
                "error": None if r.ok else (r.text or "")[:160],
            }
        except requests.RequestException as exc:
            return {
                "configured": True,
                "authenticated": False,
                "status_code": None,
                "provider": "browserless-self-hosted",
                "error": str(exc),
            }

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
