"""Fetch dated news items, never substitute generic web directory snippets."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
from services.conversation_text import normalize

FEEDS = [('TRT Haber', 'https://www.trthaber.com/manset_articles.rss'),
         ('NTV', 'https://www.ntv.com.tr/gundem.rss')]


def topic_terms(query):
    generic = {'bugun', 'bugunun', 'guncel', 'haber', 'haberler', 'haberleri', 'haberlerini',
               'onemli', 'en', 'son', 'sondakika', 'dakika', 'gundem', 'gundemi', 'gunun',
               'bana', 'oku', 'okur', 'musun', 'bul', 'bulup', 'internetten', 'turkiye',
               'guncel', 'bir', 'kac', 'neler', 'nedir', 'var', 'ver', 've'}
    return [word for word in normalize(query).split() if len(word) > 2 and word not in generic]


def clean(text):
    return ' '.join(re.sub('<[^>]+>', ' ', unescape(text or '')).split())


def parse_feed(body, source, query, now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('Europe/Istanbul'))
    cutoff = (local.replace(hour=0, minute=0, second=0, microsecond=0)
              if 'bugun' in normalize(query) else now - timedelta(hours=24))
    terms = topic_terms(query)
    results = []
    root = ET.fromstring(body)
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    for item in root.findall('./channel/item') + root.findall('./entry'):
        title = clean(item.findtext('title'))
        snippet = clean(item.findtext('description') or item.findtext('summary') or item.findtext('content'))
        link = next((node for node in item.findall('link') if node.get('rel', 'alternate') == 'alternate'), None)
        url = ((link.get('href') or link.text or '') if link is not None else '').strip()
        try:
            date = item.findtext('pubDate')
            published = (parsedate_to_datetime(date) if date else
                         datetime.fromisoformat(item.findtext('published', '').replace('Z', '+00:00')))
            if published.tzinfo is None:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        if published < cutoff or published > now + timedelta(minutes=5):
            continue
        content = normalize(title + ' ' + snippet)
        if terms and not all(term[:5] in content for term in terms):
            continue
        if not title or not url.startswith(('https://', 'http://')):
            continue
        publisher = clean(item.findtext('source')) or source
        results.append(dict(title=title, snippet=snippet[:1200], url=url, source=publisher,
                            published=published.astimezone(ZoneInfo('Europe/Istanbul')).isoformat()))
    return results


def fetch_feed(entry, headers, query):
    source, url = entry
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=6) as response:
            body = response.read(2_000_000)
        results = parse_feed(body, source, query)
        print(f'NEWS FEED: {source} fresh_relevant={len(results)}', flush=True)
        return results
    except Exception as exc:
        print(f'NEWS FEED FAILED: {source}: {exc!r}', flush=True)
        return []


def search_news(query, limit, headers):
    feeds = list(FEEDS)
    if topic_terms(query):
        feeds.append(('Google News RSS', 'https://news.google.com/rss/search?' +
                      urllib.parse.urlencode({'q': query + ' when:1d', 'hl': 'tr', 'gl': 'TR', 'ceid': 'TR:tr'})))
    with ThreadPoolExecutor(max_workers=len(feeds)) as executor:
        groups = list(executor.map(lambda entry: fetch_feed(entry, headers, query), feeds))
    results, seen = [], set()
    # Preserve editorial ordering while including multiple sources.
    for row in zip_longest_groups(groups):
        key = normalize(row['title'])
        if key not in seen:
            seen.add(key)
            results.append(row)
        if len(results) >= limit:
            break
    return results


def zip_longest_groups(groups):
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                yield group[index]
