#!/usr/bin/env python3
"""Fetch top political headlines from multiple news sources using urllib."""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

DATA_DIR = Path(__file__).parent.parent / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# RSS feeds for political/world news
POLITICS_FEEDS = [
    ('Reuters World', 'https://www.rssboard.org/rss-news'),
    ('BBC World', 'http://feeds.bbci.co.uk/news/world/rss.xml'),
    ('NPR Politics', 'https://feeds.npr.org/1004/politics.xml'),
    ('AP Top News', 'https://rsshub.app/apnews/topics/politics'),
    ('The Guardian World', 'https://feeds.theguardian.com/theguardian/world/rss'),
]

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'

def parse_rss(url, source_name, max_items=15):
    """Parse RSS feed and return list of articles."""
    try:
        req = Request(url, headers={'User-Agent': USER_AGENT})
        resp = urlopen(req, timeout=15)
        content = resp.read()
        root = ElementTree.fromstring(content)
        
        articles = []
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            desc = (item.findtext('description') or '').strip()
            pub_date = (item.findtext('pubDate') or '').strip()
            
            if title and link and len(title) > 10:
                articles.append({
                    'title': title,
                    'url': link,
                    'source': source_name,
                    'description': desc[:120] if desc else '',
                    'published': pub_date,
                })
            if len(articles) >= max_items:
                break
        return articles
    except Exception as e:
        print(f"  ✗ {source_name}: {e}")
        return []


def fetch_politics():
    """Fetch political headlines from all feeds."""
    print("📰 Fetching political headlines...")
    
    all_articles = []
    for feed_name, feed_url in POLITICS_FEEDS:
        print(f"  → {feed_name}...")
        articles = parse_rss(feed_url, feed_name)
        all_articles.extend(articles)
        print(f"    Got {len(articles)} articles")
    
    # Deduplicate by URL
    seen = set()
    unique = []
    for a in all_articles:
        if a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)
    
    # Take top 20
    result = unique[:20]
    
    output = {
        'fetched_at': datetime.now().isoformat(),
        'total': len(result),
        'sources': list(set(a['source'] for a in result)),
        'articles': result,
    }
    
    filepath = DATA_DIR / 'politics-latest.json'
    filepath.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅ Saved {len(result)} articles to {filepath}")
    return output


if __name__ == '__main__':
    fetch_politics()
