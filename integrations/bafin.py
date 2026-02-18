"""BaFin (Bundesanstalt für Finanzdienstleistungsaufsicht) integration.

BaFin is the German financial regulator.  Its public database lists all
regulated investment firms, asset managers, and KVGs (capital management
companies) operating in Germany.

The BaFin company database is accessible at:
  https://portal.mvp.bafin.de/database/InstInfo/

This client queries the public search interface for investment firms
that could be potential co-investors.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)


# BaFin entity categories relevant for PE/co-investment sourcing
RELEVANT_CATEGORIES = [
    "Kapitalverwaltungsgesellschaft",    # KVG – fund management companies
    "Finanzdienstleistungsinstitut",     # financial services institutions
    "Wertpapierinstitut",               # securities institutions
    "EU-Verwaltungsgesellschaft",        # EU-registered managers (passporting in)
]


class BaFinClient:
    """Query the BaFin regulated-entities database for investment firms."""

    def __init__(self) -> None:
        self._http = APIClient(
            base_url="https://portal.mvp.bafin.de",
            rate_limit=0.5,
            max_retries=2,
            cache_ttl=86400,  # data changes slowly
            name="BaFin",
        )
        self._http.headers["Accept"] = "text/html,application/xhtml+xml"

    def search_institutions(
        self,
        name: Optional[str] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search the BaFin institution database.

        Args:
            name: Company name (partial match).
            category: BaFin category (e.g. 'Kapitalverwaltungsgesellschaft').
            city: Filter by city.

        Returns:
            List of dicts with: name, bafin_id, category, city, address.
        """
        params: dict[str, Any] = {}
        if name:
            params["institutName"] = name
        if category:
            params["category"] = category
        if city:
            params["city"] = city

        raw = self._http.get_safe(
            "database/InstInfo/sucheForm.do",
            params=params,
            default="",
        )
        if not raw:
            return []

        return self._parse_results(raw)

    def _parse_results(self, html: str) -> list[dict[str, Any]]:
        """Extract institution records from BaFin HTML response."""
        results: list[dict[str, Any]] = []

        rows = re.findall(
            r"<tr[^>]*>(.*?)</tr>",
            html,
            re.DOTALL,
        )
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if len(cells) >= 3 and cells[0] and not cells[0].startswith("Nr"):
                bafin_id_match = re.search(r'InstId=(\d+)', row)
                results.append({
                    "name": cells[0],
                    "bafin_id": bafin_id_match.group(1) if bafin_id_match else "",
                    "category": cells[1] if len(cells) > 1 else "",
                    "city": cells[2] if len(cells) > 2 else "",
                    "address": cells[3] if len(cells) > 3 else "",
                    "country": "DE",
                    "source": "bafin.de",
                    "regulator": "BaFin",
                })

        logger.info("BaFin: parsed %d institutions", len(results))
        return results

    def search_kvgs(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Search specifically for Kapitalverwaltungsgesellschaften (KVGs).

        KVGs manage AIFs and UCITS in Germany and are prime candidates
        for co-investment partnerships.
        """
        return self.search_institutions(
            name=name,
            category="Kapitalverwaltungsgesellschaft",
        )

    def search_all_investor_types(
        self,
        name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search across all BaFin categories relevant for PE co-investment."""
        all_results: list[dict] = []
        seen_names: set[str] = set()

        for category in RELEVANT_CATEGORIES:
            results = self.search_institutions(name=name, category=category)
            for r in results:
                key = r.get("name", "").lower()
                if key not in seen_names:
                    seen_names.add(key)
                    all_results.append(r)

        logger.info("BaFin: %d unique institutions across all categories", len(all_results))
        return all_results
