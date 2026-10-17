from datetime import datetime, timezone
from unittest.mock import patch
import unittest

from services.news import parse_feed, topic_terms
from services.web import WebSearchService
from services.assistant import AssistantService

NOW = datetime(2026, 10, 16, 20, 30, tzinfo=timezone.utc)


def feed(date='Fri, 16 Oct 2026 20:00:00 +0300', title='ÖSYM sınavları erteledi', link='https://www.trthaber.com/haber/gundem/sinav-123.html'):
    return f'<rss><channel><item><title>{title}</title><link>{link}</link><description>&lt;p&gt;Sınavlar yağış nedeniyle ertelendi.&lt;/p&gt;</description><pubDate>{date}</pubDate></item></channel></rss>'.encode()


class NewsTests(unittest.TestCase):
    def test_general_news_uses_real_dated_headlines(self):
        self.assertEqual(topic_terms('bugünün önemli haberleri'), [])
        results = parse_feed(feed(), 'TRT Haber', 'bugünün önemli haberleri', NOW)
        self.assertEqual(results[0]['source'], 'TRT Haber')
        self.assertEqual(results[0]['published'], '2026-10-16T20:00:00+03:00')
        self.assertEqual(results[0]['snippet'], 'Sınavlar yağış nedeniyle ertelendi.')

    def test_atom_feed_has_real_publication_date_and_link(self):
        body = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Latest news</title><published>2026-10-16T23:00:00+03:00</published><link rel="alternate" href="https://ntv.com.tr/story/123"/><summary>Actual report</summary></entry></feed>'
        results = parse_feed(body, 'NTV', 'bugünün haberleri', NOW)
        self.assertEqual(results[0]['url'], 'https://ntv.com.tr/story/123')
        self.assertEqual(results[0]['snippet'], 'Actual report')

    def test_stale_undated_and_future_items_rejected(self):
        for date in ('Thu, 15 Oct 2026 20:00:00 +0300', '', 'Sat, 17 Oct 2026 20:00:00 +0300'):
            self.assertEqual(parse_feed(feed(date=date), 'TRT Haber', 'bugünün haberleri', NOW), [])

    def test_topic_relevance_is_preserved(self):
        self.assertTrue(parse_feed(feed(), 'TRT Haber', 'ÖSYM haberleri', NOW))
        self.assertFalse(parse_feed(feed(), 'TRT Haber', 'futbol haberleri', NOW))

    def test_news_does_not_fall_back_to_general_web_pages(self):
        service = WebSearchService()
        with patch('services.web.search_news', return_value=[]) as news, patch.object(service, '_search_bing') as bing:
            self.assertEqual(service.search('bugünün haberleri', news=True), [])
        news.assert_called_once()
        bing.assert_not_called()

    def test_news_context_includes_date_source_and_actual_summary(self):
        assistant = AssistantService()
        results = parse_feed(feed(), 'TRT Haber', 'bugünün haberleri', NOW)
        with patch.object(assistant, '_web_plan', return_value={'source': 'news', 'query': 'bugünün haberleri'}), patch.object(assistant.web, 'search', return_value=results):
            context = assistant._web_context('Haberleri oku', 'bugünün haberleri')
        self.assertIn('Yayın: 2026-10-16', context)
        self.assertIn('Kaynak: TRT Haber', context)
        self.assertIn('Sınavlar yağış nedeniyle ertelendi', context)

    def test_source_failure_does_not_discard_other_sources(self):
        from services.news import search_news
        results = parse_feed(feed(), 'TRT Haber', 'bugünün haberleri', NOW)
        with patch('services.news.fetch_feed', side_effect=lambda entry, *args: results if entry[0] == 'TRT Haber' else []):
            self.assertEqual(len(search_news('bugünün haberleri', 3, {})), 1)


if __name__ == '__main__':
    unittest.main()
