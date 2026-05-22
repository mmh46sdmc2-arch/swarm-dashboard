#!/usr/bin/env python3
"""Scrape recent news for BambooHR competitors from Google News RSS feeds."""

import json
import re
import time
import urllib.request
from datetime import datetime, timezone

DATA_DIR = "/Users/joshswarm/hermes-dashboard/data"
COMPETITORS = [
    {"name": "Rippling", "query": "Rippling HR platform"},
    {"name": "Gusto", "query": "Gusto payroll HR"},
    {"name": "Workday", "query": "Workday HCM"},
    {"name": "Personio", "query": "Personio HRIS"},
    {"name": "HiBob", "query": "HiBob HR platform"},
    {"name": "UKG", "query": "UKG workforce"},
    {"name": "ADP", "query": "ADP payroll HR"},
    {"name": "SAP SuccessFactors", "query": "SAP SuccessFactors"},
    {"name": "Oracle HCM Cloud", "query": "Oracle HCM Cloud"},
    {"name": "Deel", "query": "Deel contractor HR"},
]

GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en"


def fetch_google_news(query: str, max_items: int = 5) -> list[dict]:
    """Fetch recent news from Google News RSS feed."""
    url = GOOGLE_NEWS_URL.format(urllib.parse.quote(query))
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8")
    except Exception as e:
        return []

    items = []
    # Parse <item> blocks
    item_blocks = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
    for block in item_blocks[:max_items]:
        title_m = re.search(r"<title>(.*?)</title>", block)
        link_m = re.search(r"<link>(.*?)</link>", block)
        pubdate_m = re.search(r"<pubDate>(.*?)</pubDate>", block)
        source_m = re.search(r"<source.*?>(.*?)</source>", block)

        if title_m:
            title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()
            if title and len(title) > 10:
                items.append(
                    {
                        "title": title,
                        "link": link_m.group(1) if link_m else "",
                        "date": pubdate_m.group(1) if pubdate_m else "",
                        "source": source_m.group(1) if source_m else "Google News",
                    }
                )

    return items


def main():
    all_news = {}
    for i, comp in enumerate(COMPETITORS):
        print(f"[{i+1}/{len(COMPETITORS)}] Fetching news for {comp['name']}...")
        news = fetch_google_news(comp["query"], max_items=5)
        # Take top 3 most recent
        recent = news[:3]
        all_news[comp["name"]] = recent
        print(f"  → Found {len(recent)} recent articles")
        time.sleep(1)  # Be polite to Google

    # Write to JSON
    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "competitors": all_news,
    }
    path = f"{DATA_DIR}/competitor_news.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {path}")
    print(f"Total competitors with news: {sum(1 for v in all_news.values() if v)}")


if __name__ == "__main__":
    main()
