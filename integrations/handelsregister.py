"""Handelsregister (German Commercial Register) integration.

The official portal at handelsregister.de provides public company filings.
This client queries the publicly accessible search interface and parses
results.  For production use a paid data provider (e.g. North Data,
Bundesanzeiger) is recommended for structured bulk access.

Public endpoint: https://www.handelsregister.de
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.handelsregister.de/rp_web/search.xhtml"

# German federal states and their register courts
REGISTER_COURTS = {
    "Baden-Württemberg": ["Stuttgart", "Mannheim", "Freiburg", "Ulm"],
    "Bayern": ["München", "Nürnberg", "Augsburg", "Regensburg"],
    "Berlin": ["Berlin (Charlottenburg)"],
    "Brandenburg": ["Potsdam", "Cottbus", "Frankfurt (Oder)"],
    "Bremen": ["Bremen"],
    "Hamburg": ["Hamburg"],
    "Hessen": ["Frankfurt am Main", "Darmstadt", "Kassel", "Wiesbaden"],
    "Mecklenburg-Vorpommern": ["Rostock", "Schwerin", "Neubrandenburg"],
    "Niedersachsen": ["Hannover", "Braunschweig", "Oldenburg", "Osnabrück"],
    "Nordrhein-Westfalen": ["Düsseldorf", "Köln", "Essen", "Dortmund", "Bielefeld"],
    "Rheinland-Pfalz": ["Mainz", "Koblenz", "Ludwigshafen"],
    "Saarland": ["Saarbrücken"],
    "Sachsen": ["Dresden", "Leipzig", "Chemnitz"],
    "Sachsen-Anhalt": ["Magdeburg", "Halle (Saale)", "Stendal"],
    "Schleswig-Holstein": ["Kiel", "Lübeck", "Flensburg"],
    "Thüringen": ["Jena", "Erfurt", "Gera"],
}


class HandelsregisterClient:
    """Query the German Handelsregister for company data.

    Note: The public web portal has rate limits and CAPTCHAs for heavy
    use.  This client is intended for targeted lookups, not bulk scraping.
    For high-volume use, integrate a commercial data provider.
    """

    def __init__(self) -> None:
        self._http = APIClient(
            base_url="https://www.handelsregister.de",
            rate_limit=0.5,  # very conservative – public portal
            max_retries=2,
            cache_ttl=86400,
            name="Handelsregister",
        )
        self._http.headers["Accept"] = "text/html,application/xhtml+xml"

    def search_company(
        self,
        company_name: str,
        register_court: Optional[str] = None,
        register_type: str = "HRB",
    ) -> list[dict[str, Any]]:
        """Search for a company by name.

        Args:
            company_name: Full or partial company name.
            register_court: E.g. "München", "Stuttgart". None = all courts.
            register_type: HRA (Einzelkaufleute), HRB (Kapitalgesellschaften),
                          GnR, PR, VR.

        Returns:
            List of dicts with keys: name, register_court, register_number,
            register_type, status, address (when available).
        """
        params: dict[str, Any] = {
            "searchString": company_name,
            "registerType": register_type,
        }
        if register_court:
            params["registerCourt"] = register_court

        raw = self._http.get_safe(
            "rp_web/search.xhtml",
            params=params,
            default="",
        )
        if not raw:
            return []

        return self._parse_search_results(raw, company_name)

    def _parse_search_results(self, html: str, query: str) -> list[dict[str, Any]]:
        """Best-effort extraction from the HTML results page."""
        results: list[dict[str, Any]] = []

        # The Handelsregister returns HTML — extract table rows
        # This is fragile by nature; a commercial API is preferred
        rows = re.findall(
            r"<tr[^>]*class=\"RegPortErworben\"[^>]*>(.*?)</tr>",
            html,
            re.DOTALL,
        )
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if len(cells) >= 3:
                results.append({
                    "name": cells[0],
                    "register_court": cells[1] if len(cells) > 1 else "",
                    "register_number": cells[2] if len(cells) > 2 else "",
                    "status": cells[3] if len(cells) > 3 else "",
                    "address": cells[4] if len(cells) > 4 else "",
                    "source": "handelsregister.de",
                })

        logger.info(
            "Handelsregister: parsed %d results for '%s'",
            len(results), query,
        )
        return results

    def search_by_region(
        self,
        company_name: str,
        region: str,
    ) -> list[dict[str, Any]]:
        """Search across all register courts in a German federal state."""
        courts = REGISTER_COURTS.get(region, [])
        all_results: list[dict] = []
        for court in courts:
            results = self.search_company(company_name, register_court=court)
            all_results.extend(results)
        return all_results

    def lookup_gmbh_candidates(
        self,
        keywords: list[str],
        regions: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Search for GmbH / AG companies matching keywords in target regions."""
        target_regions = regions or list(REGISTER_COURTS.keys())
        all_results: list[dict] = []
        for keyword in keywords:
            for region in target_regions:
                results = self.search_by_region(keyword, region)
                all_results.extend(results)
        logger.info(
            "Handelsregister: found %d GmbH/AG candidates across %d keywords",
            len(all_results), len(keywords),
        )
        return all_results
