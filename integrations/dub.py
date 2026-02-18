"""DUB.de / Nachfolge.de integration – German business-for-sale platforms.

DUB (Deutsche Unternehmerbörse) is the largest marketplace for SME
transactions in Germany.  Nachfolge.de (by KfW/DIHK) focuses specifically
on succession / Nachfolge situations.

These platforms publish listings publicly; this client fetches and parses
them for deal-sourcing intelligence.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)


class DUBClient:
    """Fetches business-for-sale listings from DUB.de and Nachfolge.de."""

    def __init__(self) -> None:
        self._dub_http = APIClient(
            base_url="https://www.dub.de",
            rate_limit=0.5,
            max_retries=2,
            cache_ttl=3600,
            name="DUB.de",
        )
        self._dub_http.headers["Accept"] = "text/html"

        self._nachfolge_http = APIClient(
            base_url="https://www.nexxt-change.org",
            rate_limit=0.5,
            max_retries=2,
            cache_ttl=3600,
            name="nexxt-change",
        )
        self._nachfolge_http.headers["Accept"] = "text/html"

    def search_dub_listings(
        self,
        sector: Optional[str] = None,
        region: Optional[str] = None,
        min_revenue: Optional[float] = None,
        max_revenue: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Search DUB.de for business-for-sale listings.

        DUB.de uses a search interface with filters.  This client
        hits the public search and parses results.
        """
        params: dict[str, Any] = {"type": "sell"}
        if sector:
            params["branch"] = sector
        if region:
            params["region"] = region

        raw = self._dub_http.get_safe(
            "unternehmensnachfolge/verkauf",
            params=params,
            default="",
        )
        if not raw:
            return []

        return self._parse_dub_results(raw, min_revenue, max_revenue)

    def _parse_dub_results(
        self,
        html: str,
        min_revenue: Optional[float],
        max_revenue: Optional[float],
    ) -> list[dict[str, Any]]:
        """Extract listing data from DUB.de HTML."""
        listings: list[dict[str, Any]] = []

        # Extract listing cards — pattern depends on DUB's current markup
        blocks = re.findall(
            r'<div[^>]*class="[^"]*listing-card[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html,
            re.DOTALL,
        )
        for block in blocks:
            title_match = re.search(r"<h[23][^>]*>(.*?)</h[23]>", block, re.DOTALL)
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""

            # Try to extract revenue figure
            rev_match = re.search(r"Umsatz[:\s]*([0-9.,]+)\s*(Mio|Tsd|EUR)", block)
            revenue = None
            if rev_match:
                try:
                    val = float(rev_match.group(1).replace(".", "").replace(",", "."))
                    unit = rev_match.group(2)
                    if "Mio" in unit:
                        revenue = val * 1_000_000
                    elif "Tsd" in unit:
                        revenue = val * 1_000
                except ValueError:
                    pass

            if min_revenue and revenue and revenue < min_revenue:
                continue
            if max_revenue and revenue and revenue > max_revenue:
                continue

            location_match = re.search(r"Standort[:\s]*([\w\s-]+)", block)
            location = location_match.group(1).strip() if location_match else ""

            link_match = re.search(r'href="(/[^"]+)"', block)
            link = f"https://www.dub.de{link_match.group(1)}" if link_match else ""

            if title:
                listings.append({
                    "title": title,
                    "revenue_eur": revenue,
                    "location": location,
                    "url": link,
                    "source": "dub.de",
                    "is_succession": True,
                })

        logger.info("DUB.de: parsed %d listings", len(listings))
        return listings

    def search_nexxt_change(
        self,
        sector: Optional[str] = None,
        region: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search nexxt-change.org (IHK/KfW succession platform).

        nexxt-change.org is the successor to nachfolge.de, run by DIHK
        and KfW for matching succession seekers with successors.
        """
        params: dict[str, Any] = {"offer_type": "company"}
        if sector:
            params["sector"] = sector
        if region:
            params["region"] = region

        raw = self._nachfolge_http.get_safe(
            "Profilesuche/Suche",
            params=params,
            default="",
        )
        if not raw:
            return []

        return self._parse_nexxt_results(raw)

    def _parse_nexxt_results(self, html: str) -> list[dict[str, Any]]:
        """Extract listings from nexxt-change.org HTML."""
        listings: list[dict[str, Any]] = []

        blocks = re.findall(
            r'<div[^>]*class="[^"]*result-item[^"]*"[^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        for block in blocks:
            title_match = re.search(r"<h[234][^>]*>(.*?)</h[234]>", block, re.DOTALL)
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
            if title:
                listings.append({
                    "title": title,
                    "source": "nexxt-change.org",
                    "is_succession": True,
                })

        logger.info("nexxt-change: parsed %d listings", len(listings))
        return listings

    def scan_all(
        self,
        sectors: Optional[list[str]] = None,
        regions: Optional[list[str]] = None,
        min_revenue: Optional[float] = None,
        max_revenue: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Aggregate listings from both DUB.de and nexxt-change.org."""
        sectors = sectors or [None]  # type: ignore[list-item]
        regions = regions or [None]  # type: ignore[list-item]

        all_listings: list[dict] = []
        for sector in sectors:
            for region in regions:
                all_listings.extend(
                    self.search_dub_listings(sector, region, min_revenue, max_revenue)
                )
                all_listings.extend(
                    self.search_nexxt_change(sector, region)
                )

        logger.info("DUB+nexxt: %d total listings", len(all_listings))
        return all_listings
