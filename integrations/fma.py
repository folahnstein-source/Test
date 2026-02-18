"""FMA (Finanzmarktaufsicht) integration – Austrian financial regulator.

The FMA maintains a public register of all regulated financial entities
in Austria, including investment firms, AIFMs, and KAGs.

Register: https://www.fma.gv.at/en/search-company-database/
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)

# FMA entity types relevant for co-investment
RELEVANT_TYPES = [
    "AIFM",                              # Alternative Investment Fund Managers
    "Wertpapierfirma",                    # Securities firms
    "Verwaltungsgesellschaft",            # Management companies
    "Kreditinstitut",                     # Credit institutions (some do PE)
    "Pensionskasse",                      # Pension funds
    "Versicherungsunternehmen",           # Insurers with PE allocations
]


class FMAClient:
    """Query the Austrian FMA company database for regulated investors."""

    def __init__(self) -> None:
        self._http = APIClient(
            base_url="https://www.fma.gv.at",
            rate_limit=0.5,
            max_retries=2,
            cache_ttl=86400,
            name="FMA",
        )
        self._http.headers["Accept"] = "text/html,application/xhtml+xml"

    def search_entities(
        self,
        name: Optional[str] = None,
        entity_type: Optional[str] = None,
        city: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search the FMA company database.

        Args:
            name: Company name (partial match).
            entity_type: FMA entity category (e.g. 'AIFM').
            city: Filter by city.

        Returns:
            List of dicts with: name, fma_id, entity_type, city, country.
        """
        params: dict[str, Any] = {}
        if name:
            params["company_name"] = name
        if entity_type:
            params["type"] = entity_type
        if city:
            params["city"] = city

        raw = self._http.get_safe(
            "en/search-company-database/",
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
                fma_id_match = re.search(r'id=(\d+)', row)
                results.append({
                    "name": cells[0],
                    "fma_id": fma_id_match.group(1) if fma_id_match else "",
                    "entity_type": cells[1] if len(cells) > 1 else "",
                    "city": cells[2] if len(cells) > 2 else "",
                    "country": "AT",
                    "source": "fma.gv.at",
                    "regulator": "FMA",
                })

        logger.info("FMA: parsed %d entities", len(results))
        return results

    def search_aifms(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """Search specifically for Austrian AIFMs (PE / VC fund managers)."""
        return self.search_entities(name=name, entity_type="AIFM")

    def search_all_investor_types(
        self,
        name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search across all FMA categories relevant for co-investment."""
        all_results: list[dict] = []
        seen_names: set[str] = set()

        for etype in RELEVANT_TYPES:
            results = self.search_entities(name=name, entity_type=etype)
            for r in results:
                key = r.get("name", "").lower()
                if key not in seen_names:
                    seen_names.add(key)
                    all_results.append(r)

        logger.info("FMA: %d unique entities across all types", len(all_results))
        return all_results
