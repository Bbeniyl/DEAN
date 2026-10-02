import os
import requests

STEEL_API_KEY = os.getenv("STEEL_API_KEY", "").strip()
BASE_URL = "https://api.steel.dev/v1"

def configured():
    return bool(STEEL_API_KEY)

def create_session():
    if not STEEL_API_KEY:
        return {"ok": False, "error": "steel_not_configured"}
    r = requests.post(
        f"{BASE_URL}/sessions",
        headers={
            "steel-api-key": STEEL_API_KEY,
            "Content-Type": "application/json",
        },
        json={"debugConfig": {"interactive": True}},
        timeout=30,
    )
    data = r.json() if r.content else {}
    if not r.ok:
        return {"ok": False, "status_code": r.status_code, "error": data}
    return {
        "ok": True,
        "session_id": data.get("id"),
        "debug_url": data.get("debugUrl") or data.get("sessionViewerUrl"),
    }
