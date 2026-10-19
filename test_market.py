import json
import os
import tempfile
import sys
import types
from unittest.mock import MagicMock
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('OPENAI_API_KEY', 'test-not-a-real-key')
os.environ.setdefault('DEAN_PASSWORD', 'test-password-only')
os.environ.setdefault('SECRET_KEY', 'testing-secret-key-at-least-32-characters')
_tmp = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = os.path.join(_tmp.name, 'test.sqlite3')

import market
browser_stub = types.ModuleType('persistent_browser')
for name in ['ensure_started', 'status', 'latest_frame', 'navigate', 'evaluate_js', 'click', 'click_text', 'scroll_by', 'type_text', 'press_key', 'reload_page', 'start_keepalive', 'wait_until_ready']:
    setattr(browser_stub, name, MagicMock())
sys.modules['persistent_browser'] = browser_stub
with patch('openai.OpenAI'), patch('threading.Thread.start'):
    from app import app, maybe_handle_local_command


class MarketTests(unittest.TestCase):
    def tearDown(self):
        market._cached = None
        market._cached_at = 0
        market._news = None
        market._news_at = 0

    def payload(self, **values):
        meta = dict(symbol='AMZN', regularMarketPrice=105, chartPreviousClose=100,
                    regularMarketTime=1_800_000_000, currency='USD')
        meta.update(values)
        return {'chart': {'result': [{'meta': meta}], 'error': None}}

    def test_change_timestamp_and_delay_are_explicit(self):
        q = market.parse_quote(self.payload(), 'AMZN', 'אמזון', 'מניה', now=1_800_000_060)
        self.assertAlmostEqual(q['change_percent'], 5)
        self.assertEqual(q['age_seconds'], 60)
        self.assertFalse(q['stale'])
        self.assertIsNone(q['delay_seconds'])
        self.assertEqual(q['quote_time'], market.iso(1_800_000_000))

    def test_old_price_is_not_live(self):
        q = market.parse_quote(self.payload(), 'AMZN', 'אמזון', 'מניה', now=1_800_000_600)
        self.assertTrue(q['stale'])

    def test_bad_prices_and_wrong_symbols_are_rejected(self):
        for values in [{'regularMarketPrice': float('nan')}, {'regularMarketPrice': -1},
                       {'regularMarketTime': 1_800_000_900}, {'symbol': 'OTHER'}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                market.parse_quote(self.payload(**values), 'AMZN', 'אמזון', 'מניה', now=1_800_000_060)

    def test_news_dedup_dates_and_safe_links(self):
        body = b'''<rss><channel>
          <item><title>Market story</title><link>https://news.google.com/rss/articles/1</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate><source>Reuters</source></item>
          <item><title>Market story</title><link>https://news.google.com/rss/articles/2</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate></item>
          <item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate></item>
          <item><title>Old</title><link>https://news.google.com/rss/articles/3</link><pubDate>Mon, 12 Oct 2026 15:00:00 GMT</pubDate></item>
        </channel></rss>'''
        now = market.parsedate_to_datetime('Mon, 19 Oct 2026 16:00:00 GMT').timestamp()
        items = market.parse_news(body, now)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]['verified'])
        self.assertIsNone(items[0]['event_time'])

    def test_provider_failure_is_not_fake_quote(self):
        with patch.object(market, 'fetch_bytes', side_effect=TimeoutError):
            quote = market.get_quote(market.INSTRUMENTS[0])
            self.assertTrue(quote['error'])
            self.assertNotIn('price', quote)

    def test_authentication_and_csrf(self):
        with app.test_client() as c:
            self.assertEqual(c.get('/market').status_code, 302)
            self.assertEqual(c.get('/api/market').status_code, 401)
            with c.session_transaction() as session:
                session['authenticated'] = True
            self.assertEqual(c.get('/market').status_code, 200)
            self.assertEqual(c.post('/api/chat', json={'message': 'test'}).status_code, 403)

    def test_shared_cache_avoids_repeated_network_requests(self):
        with patch.object(market, 'get_quote', return_value={'error': 'unavailable'}) as quote, \
             patch.object(market, 'get_news', return_value={'items': [], 'error': None}) as news:
            first = market.snapshot()
            self.assertIs(first, market.snapshot())
            self.assertEqual(quote.call_count, 6)
            self.assertEqual(news.call_count, 1)
            self.assertFalse(first['streaming'])

    def test_hebrew_commands_and_home_page(self):
        self.assertEqual(maybe_handle_local_command('תזכור בדיקת עברית'), 'שמרתי בזיכרון: בדיקת עברית')
        with app.test_client() as c:
            with c.session_transaction() as session:
                session['authenticated'] = True
            r = c.get('/')
            self.assertEqual(r.status_code, 200)
            self.assertIn('מעקב שוק', r.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
