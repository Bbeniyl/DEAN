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
        market._quote_cache.clear()
        market._quote_checked_at.clear()
        market._quote_fetching.clear()
        market._news = None
        market._news_at = 0
        market._news_fetching = False

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

    def test_chart_keeps_real_points_and_rejects_missing_or_future_points(self):
        payload = self.payload()
        payload['chart']['result'][0].update(timestamp=[1799999900,1799999960,1800000900],
            indicators={'quote':[{'close':[104,None,106]}]})
        quote = market.parse_quote(payload, 'AMZN','אמזון','מניה',now=1800000060)
        self.assertEqual(quote['history'], [[1799999900,104]])

    def test_commentary_handles_partial_and_old_data_without_a_forecast(self):
        self.assertEqual(market.explain_quote({'error':'missing'})['tone'],'unknown')
        self.assertEqual(market.explain_quote({'history':[[1000,100]]})['tone'],'unknown')
        q={'history':[[1000,100],[1300,101],[1900,102]],'stale':True}
        note=market.explain_quote(q)
        self.assertEqual(note['tone'],'up')
        self.assertAlmostEqual(note['window_change_percent'],2)
        self.assertIn('קודמים',note['interpretation'])
        self.assertEqual(note['method'],'סיכום נתוני מחיר בלבד')

    def test_commentary_detects_downward_and_flat_windows(self):
        self.assertEqual(market.explain_quote({'history':[[1000,102],[1900,100]]})['tone'],'down')
        self.assertEqual(market.explain_quote({'history':[[1000,100],[1900,100.01]]})['tone'],'flat')

    def test_news_dedup_dates_and_safe_links(self):
        body = b'''<rss><channel>
          <item><title>S&amp;P 500 market story</title><link>https://news.google.com/rss/articles/1</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate><source>Reuters</source></item>
          <item><title>S&amp;P 500 market story</title><link>https://news.google.com/rss/articles/2</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate></item>
          <item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate></item>
          <item><title>Old</title><link>https://news.google.com/rss/articles/3</link><pubDate>Mon, 12 Oct 2026 15:00:00 GMT</pubDate></item>
          <item><title>Florida leads the college basketball poll</title><link>https://news.google.com/rss/articles/4</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate></item>
        </channel></rss>'''
        now = market.parsedate_to_datetime('Mon, 19 Oct 2026 16:00:00 GMT').timestamp()
        items = market.parse_news(body, now)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]['verified'])
        self.assertIsNone(items[0]['event_time'])

    def test_news_coverage_never_claims_independent_verification(self):
        body = b'''<rss><channel>
          <item><title>S&amp;P 500 market story</title><link>https://news.google.com/rss/articles/1</link><pubDate>Mon, 19 Oct 2026 15:00:00 GMT</pubDate><source>Reuters</source></item>
          <item><title>S&amp;P 500 market story</title><link>https://news.google.com/rss/articles/2</link><pubDate>Mon, 19 Oct 2026 15:01:00 GMT</pubDate><source>AP</source></item>
        </channel></rss>'''
        now = market.parsedate_to_datetime('Mon, 19 Oct 2026 16:00:00 GMT').timestamp()
        items = market.parse_news(body, now)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source_count'], 2)
        self.assertFalse(items[0]['verified'])
        self.assertIn('עדיין צריך לבדוק', items[0]['verification_label'])

    def test_snapshot_uses_selected_assets_and_exposes_picker_catalog(self):
        def quote(instrument):
            return {'symbol':instrument[0], 'name':instrument[1], 'history':[], 'error':'offline'}
        with patch.object(market, 'get_quote', side_effect=quote), \
             patch.object(market, 'get_news', return_value={'items':[], 'error':None}):
            result = market.snapshot(['NVDA','BTC-USD','NVDA','not-valid'])
        self.assertEqual([q['symbol'] for q in result['quotes'][:2]], ['NVDA','BTC-USD'])
        self.assertEqual(len(result['quotes']), 6)
        self.assertIn({'symbol':'NVDA','name':'אנבידיה','kind':'מניה'}, result['catalog'])

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

    def test_market_snapshot_returns_immediately_and_deduplicates_refresh_jobs(self):
        with patch.object(market, '_start_daemon') as start:
            first = market.snapshot()
            second = market.snapshot()
            self.assertEqual(len(first['quotes']), 6)
            self.assertTrue(first['refreshing'])
            self.assertEqual(len(start.call_args_list), 7)
            self.assertEqual(len(second['quotes']), 6)
            self.assertEqual(len(start.call_args_list), 7)
            self.assertFalse(first['streaming'])

    def test_provider_failure_keeps_last_price_and_marks_it_stale(self):
        instrument = market.INSTRUMENTS[2]
        market._quote_cache['AMZN'] = {'symbol': 'AMZN', 'price': 105, 'stale': False}
        with patch.object(market, 'get_quote', return_value={'symbol':'AMZN','error':'offline'}):
            market._refresh_quote(instrument)
        self.assertEqual(market._quote_cache['AMZN']['price'], 105)
        self.assertTrue(market._quote_cache['AMZN']['provider_offline'])
        self.assertTrue(market._quote_cache['AMZN']['stale'])

    def test_hebrew_commands_and_home_page(self):
        self.assertEqual(maybe_handle_local_command('תזכור בדיקת עברית'), 'שמרתי בזיכרון: בדיקת עברית')
        with app.test_client() as c:
            with c.session_transaction() as session:
                session['authenticated'] = True
            r = c.get('/')
            self.assertEqual(r.status_code, 200)
            self.assertIn('מעקב שוק', r.get_data(as_text=True))

    def test_shared_view_requires_authentication_and_csrf(self):
        with app.test_client() as c:
            self.assertEqual(c.get('/api/market/shared-state').status_code,401)
            self.assertEqual(c.post('/api/market/view',json={}).status_code,401)
            with c.session_transaction() as session:
                session['authenticated']=True
            self.assertEqual(c.post('/api/market/view',json={}).status_code,403)

    def test_shared_view_saves_only_server_dataset_after_render_ack(self):
        one={'quotes':[{'symbol':'AMZN','price':105}], 'news':{'items':[]},'fetched_at':'first'}
        two={**one, 'fetched_at':'second'}
        with app.test_client() as c:
            with c.session_transaction() as session:
                session['authenticated']=True
                session['csrf']='test-csrf'
            with patch.object(market,'snapshot',return_value=one):
                response=c.get('/api/market?monitor_id=testing-monitor-unique')
            dataset=response.get_json()
            self.assertTrue(dataset['sharing_available'])
            sid=dataset['snapshot_id']
            body=dict(monitor_id='testing-monitor-unique',snapshot_id=sid,selected_symbol='AMZN',state='monitoring',payload={'price':999999})
            headers={'X-CSRF-Token':'test-csrf'}
            self.assertEqual(c.post('/api/market/view',json=body,headers=headers).status_code,200)
            saved=c.get('/api/market/shared-state').get_json()['view']
            self.assertEqual(saved['snapshot']['quotes'][0]['price'],105)
            self.assertEqual(saved['selected_symbol'],'AMZN')
            with patch.object(market,'snapshot',return_value=two):
                c.get('/api/market?monitor_id=testing-monitor-unique')
            self.assertEqual(c.post('/api/market/view',json=body,headers=headers).status_code,409)
            saved=c.get('/api/market/shared-state').get_json()['view']
            self.assertEqual(saved['snapshot']['fetched_at'],'first')

    def test_shared_view_validation(self):
        with app.test_client() as c:
            with c.session_transaction() as session:
                session['authenticated']=True
                session['csrf']='test-csrf'
            response=c.post('/api/market/view',json={'monitor_id':'bad'},headers={'X-CSRF-Token':'test-csrf'})
            self.assertEqual(response.status_code,400)


if __name__ == '__main__':
    unittest.main()
