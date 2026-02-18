"""OpenCorporates API – global company registry data.

Free tier: 500 requests/month, no API key required for basic lookups.
Docs: https://api.opencorporates.com/documentation/API-Reference

Used by both agents:
- Deal sourcing: find German SMEs, check status, get filings
- Fundraising: identify investment firms, family offices, PE vehicles
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)

BASE_URL = "https://api.opencorporates.com/v0.4"


class OpenCorporatesClient:
    """Client for the OpenCorporates company search API."""

    def __init__(self, api_token: Optional[str] = None) -> None:
        headers = {}
        self._params: dict[str, str] = {}
        if api_token:
            self._params["api_token"] = api_token
        self._http = APIClient(
            base_url=BASE_URL,
            headers=headers,
            rate_limit=1.0,  # conservative for free tier
            cache_ttl=86400,  # company data changes slowly
            name="OpenCorporates",
        )

    def search_companies(
        self,
        query: str,
        jurisdiction_code: str = "de",
        per_page: int = 30,
        page: int = 1,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search companies by name in a given jurisdiction.

        Args:
            query: Company name or keyword.
            jurisdiction_code: ISO jurisdiction (de, at, ch, etc.).
            per_page: Results per page (max 100 on free tier).
            page: Page number.
            status: Filter by status (e.g. "Active").

        Returns:
            List of company dicts with keys: name, company_number,
            jurisdiction_code, registered_address, current_status, etc.
        """
        params: dict[str, Any] = {
            "q": query,
            "jurisdiction_code": jurisdiction_code,
            "per_page": per_page,
            "page": page,
            **self._params,
        }
        if status:
            params["current_status"] = status

        data = self._http.get_safe("companies/search", params=params, default={})
        if not data:
            return []

        results = data.get("results", {})
        companies = results.get("companies", [])
        return [c.get("company", c) for c in companies]

    def get_company(
        self, jurisdiction_code: str, company_number: str
    ) -> Optional[dict[str, Any]]:
        """Fetch full details for a single company."""
        path = f"companies/{jurisdiction_code}/{company_number}"
        params = dict(self._params)
        data = self._http.get_safe(path, params=params, default=None)
        if not data:
            return None
        return data.get("results", {}).get("company", data)

    def search_officers(
        self,
        query: str,
        jurisdiction_code: str = "de",
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """Search company officers/directors — useful for identifying
        founder-led businesses or key decision-makers."""
        params: dict[str, Any] = {
            "q": query,
            "jurisdiction_code": jurisdiction_code,
            "per_page": per_page,
            **self._params,
        }
        data = self._http.get_safe("officers/search", params=params, default={})
        if not data:
            return []
        results = data.get("results", {})
        officers = results.get("officers", [])
        return [o.get("officer", o) for o in officers]

    def search_german_smes(
        self,
        sector_keywords: list[str],
        regions: Optional[list[str]] = None,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """Convenience: search for German SMEs matching sector keywords."""
        all_results: list[dict] = []
        for keyword in sector_keywords:
            companies = self.search_companies(
                query=keyword,
                jurisdiction_code="de",
                per_page=per_page,
                status="Active",
            )
            for company in companies:
                addr = company.get("registered_address_in_full", "") or ""
                if regions:
                    if not any(r.lower() in addr.lower() for r in regions):
                        continue
                all_results.append(company)
        logger.info(
            "OpenCorporates: found %d German SME candidates across %d keywords",
            len(all_results), len(sector_keywords),
        )
        return all_results

    def search_investment_firms(
        self,
        jurisdiction_code: str = "de",
        keywords: Optional[list[str]] = None,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """Search for investment/PE/family-office vehicles in a jurisdiction."""
        if keywords is None:
            keywords = [
                "beteiligungsgesellschaft",
                "family office",
                "kapitalverwaltung",
                "private equity",
                "vermögensverwaltung",
                "investment",
            ]
        all_results: list[dict] = []
        for kw in keywords:
            companies = self.search_companies(
                query=kw,
                jurisdiction_code=jurisdiction_code,
                per_page=per_page,
                status="Active",
            )
            all_results.extend(companies)
        logger.info(
            "OpenCorporates: found %d investment firms in %s",
            len(all_results), jurisdiction_code,
        )
        return all_results
