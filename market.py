"""Read-only, on-demand market monitor. Never submits trading orders or AI calls."""
import json
import math
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from flask import Blueprint, jsonify, render_template

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
    return {
        "symbol": symbol, "name": name, "kind": kind, "price": price,
        "currency": meta.get("currency", ""),
        "change_percent": (price / previous - 1) * 100 if previous and previous > 0 else None,
        "quote_time": iso(stamp), "age_seconds": age, "stale": age > 180,
        "exchange": meta.get("exchangeName", ""),
        "market_state": meta.get("marketState", "UNKNOWN"),
        "delay_seconds": None,
        "source": "Yahoo Finance — מקור ציבורי לא רשמי; עיכוב אינו מאומת",
        "source_url": "https://finance.yahoo.com/quote/" + urllib.parse.quote(symbol, safe=""),
        "error": None,
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


def register_market(app, require_login):
    bp = Blueprint("market", __name__, template_folder="templates")

    @bp.get("/market")
    @require_login
    def page():
        return render_template("market.html")

    @bp.get("/api/market")
    @require_login
    def data():
        response = jsonify(snapshot())
        response.headers["Cache-Control"] = "no-store"
        return response

    app.register_blueprint(bp)
