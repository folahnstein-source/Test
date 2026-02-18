"""FINMA (Swiss Financial Market Supervisory Authority) integration.

FINMA publishes a public register of all authorised financial institutions
in Switzerland, including asset managers, fund management companies, and
securities firms.

Register: https://www.finma.ch/en/authorisation/self-regulatory-organisations-sros/sro-member-search/
Institute search: https://www.finma.ch/en/authorisation/institution-search/
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)

# FINMA categories relevant for co-investment sourcing
RELEVANT_CATEGORIES = [
    "Asset manager of collective assets",     # Fund managers
    "Manager of collective assets",           # CISA managers
    "Fund management company",                # Swiss fund management
    "Securities firm",                        # Securities dealers
    "Bank",                                   # Swiss banks (some with PE desks)
    "Insurance company",                      # Insurers with PE allocation
]


class FINMAClient:
    """Query the FINMA institution register for Swiss financial entities."""

    def __init__(self) -> None:
        self._http = APIClient(
            base_url="https://www.finma.ch",
            rate_limit=0.5,
            max_retries=2,
            cache_ttl=86400,
            name="FINMA",
        )
        self._http.headers["Accept"] = "text/html,application/xhtml+xml"

    def search_institutions(
        self,
        name: Optional[str] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search the FINMA institution register.

        Args:
            name: Institution name (partial match).
            category: FINMA category.
            city: Filter by city.

        Returns:
            List of dicts with: name, finma_id, category, city, country.
        """
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if category:
            params["category"] = category
        if city:
            params["city"] = city

        raw = self._http.get_safe(
            "en/authorisation/institution-search/",
            params=params,
            default="",
        )
        if not raw:
            return []

        return self._parse_results(raw)

    def _parse_results(self, html: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if len(cells) >= 2 and cells[0] and not cells[0].lower().startswith("name"):
                finma_id_match = re.search(r'id=(\d+)', row)
                results.append({
                    "name": cells[0],
                    "finma_id": finma_id_match.group(1) if finma_id_match else "",
                    "category": cells[1] if len(cells) > 1 else "",
                    "city": cells[2] if len(cells) > 2 else "",
                    "country": "CH",
                    "source": "finma.ch",
                    "regulator": "FINMA",
                })

        logger.info("FINMA: parsed %d institutions", len(results))
        return results

    def search_asset_managers(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Search for Swiss-licenced asset managers (PE / VC / FoF)."""
        results: list[dict] = []
        for cat in ("Asset manager of collective assets", "Manager of collective assets"):
            results.extend(self.search_institutions(name=name, category=cat))
        return results

    def search_all_investor_types(
        self,
        name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search across all FINMA categories relevant for co-investment."""
        all_results: list[dict] = []
        seen_names: set[str] = set()

        for category in RELEVANT_CATEGORIES:
            results = self.search_institutions(name=name, category=category)
            for r in results:
                key = r.get("name", "").lower()
                if key not in seen_names:
                    seen_names.add(key)
                    all_results.append(r)

        logger.info("FINMA: %d unique institutions across all categories", len(all_results))
        return all_results
