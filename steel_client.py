import os
import re
import requests

BASE_URL = "https://api.steel.dev/v1"


def _normalize_api_key(raw):
    """Accept a plain key or common copy/paste forms without exposing the secret."""
    value = (raw or "").strip()
    if not value:
        return ""

    if value.upper().startswith("STEEL_API_KEY="):
        value = value.split("=", 1)[1].strip()

    value = value.strip().strip('"').strip("'").strip("`").strip()

    if any(ch.isspace() for ch in value):
        tokens = re.findall(r"[A-Za-z0-9._-]{16,}", value)
        if tokens:
            value = max(tokens, key=len)

    return value.strip()


def api_key():
    return _normalize_api_key(os.getenv("STEEL_API_KEY", ""))


def configured():
    return bool(api_key())


def create_session():
    key = api_key()
    if not key:
        return {"ok": False, "error": "steel_not_configured"}

    try:
        r = requests.post(
            f"{BASE_URL}/sessions",
            headers={
                "steel-api-key": key,
                "Content-Type": "application/json",
            },
            json={
                "debugConfig": {
                    "interactive": True,
                    "systemCursor": True,
                }
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": "steel_request_failed",
            "message": str(exc),
        }

    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {"message": (r.text or "")[:500]}

    if not r.ok:
        return {
            "ok": False,
            "status_code": r.status_code,
            "error": data,
        }

    debug_url = data.get("debugUrl") or data.get("sessionViewerUrl")
    return {
        "ok": True,
        "session_id": data.get("id"),
        "debug_url": debug_url,
        "viewer_ready": bool(debug_url),
    }
