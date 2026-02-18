"""RSS / Atom feed aggregator for deal and investor signals.

Monitors German-language M&A news feeds, industry publications, and
financial press for deal-flow and fundraising intelligence.  Uses only
stdlib (xml.etree) so no external dependency is required.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)

# -- Pre-configured feed URLs ------------------------------------------------

DEAL_FEEDS: dict[str, str] = {
    "finance_magazin": "https://www.finance-magazin.de/feed/",
    "unternehmeredition": "https://www.unternehmeredition.de/feed/",
    "m_and_a_review": "https://www.ma-review.de/feed/",
    "handelsblatt_unternehmen": "https://www.handelsblatt.com/contentexport/feed/unternehmen",
    "deutsche_startups": "https://www.deutsche-startups.de/feed/",
    "vc_magazin": "https://www.vc-magazin.de/feed/",
    "private_equity_wire": "https://www.privateequitywire.co.uk/rss.xml",
}

INVESTOR_FEEDS: dict[str, str] = {
    "private_funds_cfo": "https://www.privatefundscfo.com/feed/",
    "buyouts_insider": "https://www.buyoutsinsider.com/feed/",
    "vc_magazin": "https://www.vc-magazin.de/feed/",
}

# Keywords for filtering relevant items
DEAL_KEYWORDS = {
    "nachfolge", "übernahme", "beteiligung", "akquisition",
    "carve-out", "carveout", "mittelstand", "buyout",
    "familienunternehmen", "m&a", "unternehmensverkauf",
    "succession", "acquisition", "private equity",
}

INVESTOR_KEYWORDS = {
    "family office", "co-invest", "coinvest", "fundraising",
    "limited partner", "independent sponsor", "fundless sponsor",
    "beteiligungsgesellschaft", "kapitalanlage", "investor",
    "co-investment", "fondsauflage", "fund raising",
}


def _parse_feed(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 or Atom feed XML into a list of item dicts."""
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # RSS 2.0
    for item in root.iter("item"):
        entry: dict[str, str] = {}
        for tag in ("title", "link", "description", "pubDate", "category"):
            el = item.find(tag)
            if el is not None and el.text:
                entry[tag] = el.text.strip()
        if entry:
            items.append(entry)

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.iter("{http://www.w3.org/2005/Atom}entry"):
        entry = {}
        title_el = item.find("atom:title", ns)
        if title_el is not None and title_el.text:
            entry["title"] = title_el.text.strip()
        link_el = item.find("atom:link", ns)
        if link_el is not None:
            entry["link"] = link_el.get("href", "")
        summary_el = item.find("atom:summary", ns)
        if summary_el is not None and summary_el.text:
            entry["description"] = summary_el.text.strip()
        updated_el = item.find("atom:updated", ns)
        if updated_el is not None and updated_el.text:
            entry["pubDate"] = updated_el.text.strip()
        if entry:
            items.append(entry)

    return items


def _matches_keywords(item: dict, keywords: set[str]) -> bool:
    text = " ".join([
        item.get("title", ""),
        item.get("description", ""),
        item.get("category", ""),
    ]).lower()
    return any(kw in text for kw in keywords)


class RSSFeedAggregator:
    """Fetches and filters RSS feeds for PE-relevant news."""

    def __init__(self) -> None:
        self._http = APIClient(
            rate_limit=1.0,
            max_retries=2,
            timeout=15,
            cache_ttl=1800,  # 30 min
            name="RSS",
        )
        self._http.headers["Accept"] = "application/rss+xml, application/xml, text/xml"

    def fetch_feed(self, url: str) -> list[dict[str, str]]:
        """Fetch and parse a single RSS/Atom feed."""
        raw = self._http.get_safe(path="", params=None, default="")
        # APIClient uses base_url; for arbitrary URLs we override
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=self._http.headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            return _parse_feed(body)
        except Exception as exc:
            logger.warning("RSS: failed to fetch %s: %s", url, exc)
            return []

    def scan_deal_feeds(
        self,
        extra_feeds: Optional[dict[str, str]] = None,
        keywords: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        """Aggregate deal-signal items from all configured deal feeds."""
        feeds = dict(DEAL_FEEDS)
        if extra_feeds:
            feeds.update(extra_feeds)
        kws = keywords or DEAL_KEYWORDS

        all_items: list[dict] = []
        for feed_name, url in feeds.items():
            items = self.fetch_feed(url)
            for item in items:
                if _matches_keywords(item, kws):
                    item["feed_source"] = feed_name
                    all_items.append(item)

        logger.info("RSS: %d deal-signal items from %d feeds", len(all_items), len(feeds))
        return all_items

    def scan_investor_feeds(
        self,
        extra_feeds: Optional[dict[str, str]] = None,
        keywords: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        """Aggregate investor-signal items from all configured investor feeds."""
        feeds = dict(INVESTOR_FEEDS)
        if extra_feeds:
            feeds.update(extra_feeds)
        kws = keywords or INVESTOR_KEYWORDS

        all_items: list[dict] = []
        for feed_name, url in feeds.items():
            items = self.fetch_feed(url)
            for item in items:
                if _matches_keywords(item, kws):
                    item["feed_source"] = feed_name
                    all_items.append(item)

        logger.info("RSS: %d investor-signal items from %d feeds", len(all_items), len(feeds))
        return all_items
