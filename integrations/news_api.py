"""News API integration for deal-signal detection.

Scans news articles for M&A signals, succession announcements, carve-outs,
and investor activity across the DACH region.

Supports:
- NewsAPI.org (free tier: 100 req/day, 1-month history)
- GNews API (alternative, 100 req/day free)

Both are configured via API key in config.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)


# -- Keyword sets for signal detection ----------------------------------------

DEAL_SIGNAL_KEYWORDS_DE = [
    "Nachfolge Mittelstand",
    "Unternehmensnachfolge",
    "Unternehmensverkauf",
    "Firmenübernahme GmbH",
    "Carve-out Deutschland",
    "M&A Mittelstand",
    "Private Equity Deutschland",
    "Beteiligung Mittelstand",
    "Übernahme Familienunternehmen",
    "Nachfolger gesucht",
]

DEAL_SIGNAL_KEYWORDS_EN = [
    "German Mittelstand acquisition",
    "SME buyout Germany",
    "succession planning Germany",
    "private equity DACH",
    "carve-out Germany",
]

INVESTOR_SIGNAL_KEYWORDS = [
    "family office DACH investment",
    "co-investment Germany",
    "independent sponsor Germany",
    "PE fundraising DACH",
    "family office Deutschland Beteiligung",
    "Co-Invest Mittelstand",
]


class NewsAPIClient:
    """Fetches and filters news articles for PE deal and investor signals."""

    def __init__(
        self,
        newsapi_key: Optional[str] = None,
        gnews_key: Optional[str] = None,
    ) -> None:
        self._newsapi_key = newsapi_key
        self._gnews_key = gnews_key

        if newsapi_key:
            self._newsapi = APIClient(
                base_url="https://newsapi.org/v2",
                headers={"X-Api-Key": newsapi_key},
                rate_limit=0.5,
                cache_ttl=3600,
                name="NewsAPI",
            )
        else:
            self._newsapi = None

        if gnews_key:
            self._gnews = APIClient(
                base_url="https://gnews.io/api/v4",
                rate_limit=0.5,
                cache_ttl=3600,
                name="GNews",
            )
        else:
            self._gnews = None

    @property
    def is_configured(self) -> bool:
        return self._newsapi is not None or self._gnews is not None

    def search_newsapi(
        self,
        query: str,
        language: str = "de",
        sort_by: str = "publishedAt",
        page_size: int = 20,
        from_days_ago: int = 30,
    ) -> list[dict[str, Any]]:
        """Search articles via NewsAPI.org."""
        if not self._newsapi:
            return []
        from_date = (datetime.utcnow() - timedelta(days=from_days_ago)).strftime("%Y-%m-%d")
        params = {
            "q": query,
            "language": language,
            "sortBy": sort_by,
            "pageSize": page_size,
            "from": from_date,
        }
        data = self._newsapi.get_safe("everything", params=params, default={})
        return data.get("articles", []) if isinstance(data, dict) else []

    def search_gnews(
        self,
        query: str,
        language: str = "de",
        country: str = "de",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search articles via GNews API."""
        if not self._gnews:
            return []
        params = {
            "q": query,
            "lang": language,
            "country": country,
            "max": max_results,
            "token": self._gnews_key,
        }
        data = self._gnews.get_safe("search", params=params, default={})
        return data.get("articles", []) if isinstance(data, dict) else []

    def _search(self, query: str, language: str = "de", max_results: int = 10) -> list[dict]:
        """Search across all configured news sources."""
        articles: list[dict] = []
        articles.extend(self.search_newsapi(query, language=language, page_size=max_results))
        articles.extend(self.search_gnews(query, language=language, max_results=max_results))
        return articles

    def scan_deal_signals(
        self,
        extra_keywords: Optional[list[str]] = None,
        language: str = "de",
        max_per_keyword: int = 10,
    ) -> list[dict[str, Any]]:
        """Scan news for M&A / succession / deal signals in Germany.

        Returns a list of article dicts, each tagged with the signal keyword.
        """
        keywords = list(DEAL_SIGNAL_KEYWORDS_DE)
        if language == "en" or language == "de":
            keywords.extend(DEAL_SIGNAL_KEYWORDS_EN)
        if extra_keywords:
            keywords.extend(extra_keywords)

        all_articles: list[dict] = []
        seen_urls: set[str] = set()

        for kw in keywords:
            articles = self._search(kw, language=language, max_results=max_per_keyword)
            for article in articles:
                url = article.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    article["signal_keyword"] = kw
                    all_articles.append(article)

        logger.info("NewsAPI: found %d deal-signal articles", len(all_articles))
        return all_articles

    def scan_investor_signals(
        self,
        extra_keywords: Optional[list[str]] = None,
        max_per_keyword: int = 10,
    ) -> list[dict[str, Any]]:
        """Scan news for co-investor / fundraising signals in DACH."""
        keywords = list(INVESTOR_SIGNAL_KEYWORDS)
        if extra_keywords:
            keywords.extend(extra_keywords)

        all_articles: list[dict] = []
        seen_urls: set[str] = set()

        for kw in keywords:
            for lang in ("de", "en"):
                articles = self._search(kw, language=lang, max_results=max_per_keyword)
                for article in articles:
                    url = article.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        article["signal_keyword"] = kw
                        all_articles.append(article)

        logger.info("NewsAPI: found %d investor-signal articles", len(all_articles))
        return all_articles
