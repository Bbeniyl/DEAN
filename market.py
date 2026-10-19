"""Read-only, on-demand market monitor. Never submits trading orders or AI calls."""
import json
import math
import re
import secrets
from contextlib import closing
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from flask import Blueprint, jsonify, render_template, request

INSTRUMENTS = (
    ("^GSPC", "S&P 500", "מדד מזומן"),
    ("^FCHI", "צרפת 40", "מדד מזומן"),
    ("AMZN", "אמזון", "מניה"),
    ("GC=F", "זהב", "חוזה עתידי — מועד החוזה לפי הספק"),
    ("CL=F", "נפט WTI", "חוזה עתידי — מועד החוזה לפי הספק"),
    ("KC=F", "קפה ערביקה", "חוזה עתידי — מועד החוזה לפי הספק"),
)
CACHE_SECONDS = 60
NEWS_SECONDS = 300
_lock = threading.Lock()
_cached = None
_cached_at = 0.0
_news = None
_news_at = 0.0


def iso(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp,
                                  timezone.utc).isoformat(timespec="seconds")


def fetch_bytes(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; DEAN-market-monitor/1.0)"})
    with urllib.request.urlopen(req, timeout=6) as response:
        body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("response_too_large")
    return body


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def parse_quote(payload, symbol, name, kind, now=None):
    now = time.time() if now is None else now
    chart = payload.get("chart", {})
    results = chart.get("result")
    if chart.get("error") or not results:
        raise ValueError("missing_quote")
    meta = results[0].get("meta", {})
    if meta.get("symbol", "").upper() != symbol.upper():
        raise ValueError("symbol_mismatch")
    price = finite(meta.get("regularMarketPrice"))
    stamp = finite(meta.get("regularMarketTime"))
    previous = finite(meta.get("chartPreviousClose"))
    if previous is None:
        previous = finite(meta.get("previousClose"))
    if price is None or price <= 0 or stamp is None or stamp > now + 60 or stamp < 946684800:
        raise ValueError("invalid_quote")
    age = max(0, int(now - stamp))
    result = results[0]
    history = []
    indicators = result.get('indicators', {}).get('quote', [])
    closes = indicators[0].get('close', []) if indicators else []
    for timestamp, close in zip(result.get('timestamp', []), closes):
        timestamp, close = finite(timestamp), finite(close)
        if timestamp and close and close > 0 and 946684800 < timestamp <= now + 60:
            history.append([timestamp, close])
    return {
        "symbol": symbol, "name": name, "kind": kind, "price": price,
        "currency": meta.get("currency", ""),
        "display_unit": {'^GSPC':'נקודות','^FCHI':'נקודות','AMZN':'דולר למניה',
                         'GC=F':'דולר לאונקיה','CL=F':'דולר לחבית','KC=F':'סנט לליברה'}.get(symbol, ''),
        "change_percent": (price / previous - 1) * 100 if previous and previous > 0 else None,
        "quote_time": iso(stamp), "age_seconds": age, "stale": age > 180,
        "exchange": meta.get("exchangeName", ""),
        "market_state": meta.get("marketState", "UNKNOWN"),
        "delay_seconds": None,
        "source": "Yahoo Finance — מקור ציבורי לא רשמי; עיכוב אינו מאומת",
        "source_url": "https://finance.yahoo.com/quote/" + urllib.parse.quote(symbol, safe=""),
        "error": None,
        "history": sorted(history, key=lambda p: p[0])[-420:],
    }


def get_quote(instrument):
    symbol, name, kind = instrument
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="")
    url += "?interval=1m&range=1d"
    try:
        return parse_quote(json.loads(fetch_bytes(url)), symbol, name, kind)
    except Exception:
        # Do not leak request internals, or replace unavailable prices with demo values.
        return {"symbol": symbol, "name": name, "kind": kind, "error": "לא התקבל מחיר תקין מהספק"}


def parse_news(body, now=None):
    now = time.time() if now is None else now
    root = ET.fromstring(body)
    items, seen = [], set()
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()[:400]
        link = (item.findtext("link") or "").strip()
        try:
            parsed = urllib.parse.urlparse(link)
            if parsed.scheme != "https" or parsed.hostname != "news.google.com":
                continue
            published = parsedate_to_datetime(item.findtext("pubDate") or "").timestamp()
        except (ValueError, TypeError, OverflowError):
            continue
        if not title or title.casefold() in seen or published > now + 60 or now - published > 86400:
            continue
        seen.add(title.casefold())
        source = item.find("source")
        items.append({"title": title, "url": link, "published_at": iso(published),
                      "source": source.text if source is not None else "מקור לא צוין",
                      "event_time": None, "verified": False})
    return sorted(items, key=lambda item: item["published_at"], reverse=True)[:12]


def get_news():
    query = '("S&P 500" OR "CAC 40" OR Amazon OR "arabica coffee" OR "gold price" OR "crude oil") (site:reuters.com OR site:apnews.com OR site:ft.com) when:1d'
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        items = parse_news(fetch_bytes(url))
        return {"items": items, "fetched_at": iso(), "error": None,
                "notice": "כותרות דרך Google News; תוכן הכתבות ושעת האירוע לא אומתו. הכותרות עשויות להיות באנגלית."}
    except Exception:
        return {"items": [], "fetched_at": iso(), "error": "מקור החדשות אינו זמין כרגע"}


def snapshot():
    global _cached, _cached_at, _news, _news_at
    with _lock:
        now = time.monotonic()
        if _cached is not None and now - _cached_at < CACHE_SECONDS:
            return _cached
        with ThreadPoolExecutor(max_workers=6) as pool:
            quotes = list(pool.map(get_quote, INSTRUMENTS))
        if _news is None or now - _news_at >= NEWS_SECONDS:
            _news = get_news()
            _news_at = time.monotonic()
        _cached = {"fetched_at": iso(), "quotes": quotes, "news": _news,
                   "refresh_seconds": CACHE_SECONDS, "streaming": False,
                   "notice": "רענון כל דקה בזמן שהמסך פתוח. נתוני ייחוס בלבד, לא שערי Plus500. אין חיבור לחשבון או ביצוע עסקאות."}
        _cached_at = time.monotonic()
        return _cached


class SharedMonitorStore:
    """Latest delivered and browser-acknowledged dataset, never browser credentials."""
    def __init__(self, get_db, postgres=False):
        self.get_db = get_db
        self.placeholder = '%s' if postgres else '?'
        with closing(get_db()) as con, con:
            con.execute('''CREATE TABLE IF NOT EXISTS market_monitor_views(
                monitor_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL,
                payload TEXT NOT NULL, delivered_at TEXT NOT NULL,
                viewed_at TEXT, selected_symbol TEXT, screen_state TEXT,
                acknowledged_payload TEXT, updated_at TEXT NOT NULL)''')

    def delivered(self, monitor_id, payload):
        snapshot_id = secrets.token_urlsafe(18)
        stamp = iso()
        marks = ','.join([self.placeholder] * 5)
        # Keep the last acknowledged data until the next render is acknowledged.
        with closing(self.get_db()) as con, con:
            con.execute(f'''INSERT INTO market_monitor_views
                (monitor_id,snapshot_id,payload,delivered_at,updated_at)
                VALUES({marks}) ON CONFLICT(monitor_id) DO UPDATE SET
                snapshot_id=excluded.snapshot_id,payload=excluded.payload,
                delivered_at=excluded.delivered_at,updated_at=excluded.updated_at''',
                (monitor_id, snapshot_id, json.dumps(payload, ensure_ascii=False), stamp, stamp))
        return snapshot_id

    def acknowledge(self, monitor_id, snapshot_id, selected_symbol, state):
        p = self.placeholder
        stamp = iso()
        with closing(self.get_db()) as con, con:
            cursor = con.execute(f'''UPDATE market_monitor_views SET
                viewed_at={p},selected_symbol={p},screen_state={p},
                acknowledged_payload=payload,updated_at={p}
                WHERE monitor_id={p} AND snapshot_id={p}''',
                (stamp, selected_symbol, state, stamp, monitor_id, snapshot_id))
            return cursor.rowcount == 1

    def latest(self):
        with closing(self.get_db()) as con, con:
            row = con.execute('''SELECT monitor_id,viewed_at,selected_symbol,screen_state,
                acknowledged_payload FROM market_monitor_views
                WHERE viewed_at IS NOT NULL ORDER BY viewed_at DESC LIMIT 1''').fetchone()
        if row is None:
            return None
        return {'monitor_id': row['monitor_id'], 'viewed_at': row['viewed_at'],
                'selected_symbol': row['selected_symbol'], 'screen_state': row['screen_state'],
                'snapshot': json.loads(row['acknowledged_payload'])}


def valid_monitor_id(value):
    return isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9-]{12,64}', value) is not None


def register_market(app, require_login, require_csrf=None, csrf_token=None, get_db=None, postgres=False):
    bp = Blueprint("market", __name__, template_folder="templates")
    shared = None
    if get_db:
        try:
            shared = SharedMonitorStore(get_db, postgres)
        except Exception:
            app.logger.error('Market snapshot storage is unavailable')

    @bp.get("/market")
    @require_login
    def page():
        response = app.make_response(render_template("market.html", csrf=csrf_token() if csrf_token else ''))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.get("/api/market")
    @require_login
    def data():
        result = dict(snapshot())
        monitor_id = request.args.get('monitor_id', '')
        result['sharing_available'] = shared is not None
        if shared and valid_monitor_id(monitor_id):
            try:
                result['snapshot_id'] = shared.delivered(monitor_id, result)
            except Exception:
                result['sharing_available'] = False
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    if shared and require_csrf:
        @bp.post('/api/market/view')
        @require_csrf
        def acknowledge_view():
            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                return jsonify(error='invalid_view'), 400
            monitor_id, snapshot_id = body.get('monitor_id'), body.get('snapshot_id')
            symbol, state = body.get('selected_symbol'), body.get('state')
            if (not valid_monitor_id(monitor_id) or not isinstance(snapshot_id, str)
                    or len(snapshot_id) > 64 or symbol not in {x[0] for x in INSTRUMENTS}
                    or state not in {'monitoring', 'paused', 'stopped'}):
                return jsonify(error='invalid_view'), 400
            try:
                if not shared.acknowledge(monitor_id, snapshot_id, symbol, state):
                    return jsonify(error='snapshot_changed'), 409
                return jsonify(ok=True, saved_at=iso())
            except Exception:
                return jsonify(error='storage_unavailable'), 503

        @bp.get('/api/market/shared-state')
        @require_login
        def shared_state():
            response = jsonify(view=shared.latest())
            response.headers['Cache-Control'] = 'no-store'
            return response

    app.register_blueprint(bp)
