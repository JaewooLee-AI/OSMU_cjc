"""Keyword-based news discovery (Google News RSS + Naver News search).

Complements the manual "paste a URL" flow in News Curation: the admin picks
SEO keywords (reused from Brand Kit) instead of hunting for article links
by hand. No API keys required for either source.

Naver News is scraped from the public search results page (not the official
Open API) — this is intentionally the same low-effort approach the prior cjc_blog_v2 project
uses. It's fragile to Naver markup changes; migrating to the official
Naver Search API is a known future improvement, not done here.
"""
from __future__ import annotations

import urllib.parse

import feedparser
import requests
from bs4 import BeautifulSoup

from core import repo

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def fetch_google_news_rss(keyword: str, max_results: int = 5) -> list[dict]:
    """Google News RSS search — no API key needed, returns Korean results."""
    encoded = urllib.parse.quote(keyword)
    rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        resp = requests.get(rss_url, headers=_HEADERS, timeout=10)
        feed = feedparser.parse(resp.content)
    except Exception:
        return []

    articles = []
    for entry in feed.entries[:max_results]:
        source = getattr(entry, "source", None)
        articles.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": source.get("title", "Google News") if source else "Google News",
                "published": entry.get("published", ""),
                "summary": BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(strip=True),
            }
        )
    return articles


def fetch_naver_news_search(keyword: str, max_results: int = 5) -> list[dict]:
    """Scrapes Naver's public news search results page."""
    encoded = urllib.parse.quote(keyword)
    search_url = f"https://search.naver.com/search.naver?where=news&query={encoded}&sort=0"
    try:
        resp = requests.get(search_url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return []

    articles = []
    for item in soup.select("div.news_wrap")[:max_results]:
        title_tag = item.select_one("a.news_tit")
        if not title_tag:
            continue
        press_tag = item.select_one("a.info.press") or item.select_one(".press")
        summary_tag = item.select_one(".news_dsc") or item.select_one(".api_txt_lines")
        articles.append(
            {
                "title": title_tag.get_text(strip=True),
                "url": title_tag.get("href", ""),
                "source": press_tag.get_text(strip=True) if press_tag else "Naver News",
                "published": "",
                "summary": summary_tag.get_text(strip=True) if summary_tag else "",
            }
        )
        if len(articles) >= max_results:
            break
    return articles


def search_news_by_keywords(keywords: list[str], limit_per_keyword: int = 2) -> list[dict]:
    """Searches Google News + Naver News for each keyword, dedups against
    URLs already queued in osmu_campaigns, and dedups results against each
    other by URL."""
    known_urls = repo.list_known_source_urls()
    seen_urls = set(known_urls)
    results = []

    for keyword in keywords:
        for article in fetch_google_news_rss(keyword, max_results=limit_per_keyword) + fetch_naver_news_search(
            keyword, max_results=limit_per_keyword
        ):
            url = article.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            article["matched_keyword"] = keyword
            results.append(article)

    return results
