"""North Data API – company intelligence for German / European firms.

North Data aggregates data from official registers (Handelsregister,
Bundesanzeiger, EU registers) and provides structured company profiles
including financials, ownership, officers, and M&A events.

Docs: https://www.northdata.com/doc/api
Free tier: limited; paid plans for bulk access.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from integrations.api_client import APIClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.northdata.com/_api"


class NorthDataClient:
    """Client for the North Data company intelligence API."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["X-Api-Key"] = api_key
        self._api_key = api_key
        self._http = APIClient(
            base_url=BASE_URL,
            headers=headers,
            rate_limit=1.0,
            cache_ttl=43200,  # 12 hours
            name="NorthData",
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def search_company(
        self,
        name: str,
        country: str = "DE",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fuzzy company name search."""
        params: dict[str, Any] = {
            "query": name,
            "country": country,
            "limit": limit,
        }
        data = self._http.get_safe("search/v1/suggest", params=params, default=[])
        if isinstance(data, list):
            return data
        return data.get("results", []) if isinstance(data, dict) else []

    def get_company(
        self,
        name: str,
        city: Optional[str] = None,
        register_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Retrieve full company profile including financials and officers."""
        params: dict[str, Any] = {"name": name}
        if city:
            params["city"] = city
        if register_id:
            params["registerId"] = register_id

        return self._http.get_safe("company/v1/company", params=params, default=None)

    def get_financials(
        self,
        name: str,
        city: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Retrieve published financial statements (Bundesanzeiger filings)."""
        params: dict[str, Any] = {"name": name}
        if city:
            params["city"] = city
        return self._http.get_safe("company/v1/financials", params=params, default=None)

    def get_events(
        self,
        name: str,
        city: Optional[str] = None,
        event_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Retrieve company events (M&A, management changes, insolvency, etc.).

        Useful for detecting succession signals, ownership changes, and
        carve-out announcements.
        """
        params: dict[str, Any] = {"name": name}
        if city:
            params["city"] = city
        if event_types:
            params["eventTypes"] = ",".join(event_types)

        data = self._http.get_safe("company/v1/events", params=params, default=[])
        return data if isinstance(data, list) else data.get("events", [])

    def find_succession_candidates(
        self,
        keywords: list[str],
        country: str = "DE",
        limit_per_keyword: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for companies showing succession / ownership-change signals."""
        candidates: list[dict] = []
        succession_event_types = [
            "management_change",
            "shareholder_change",
            "liquidation_start",
        ]
        for keyword in keywords:
            companies = self.search_company(keyword, country=country, limit=limit_per_keyword)
            for company in companies:
                name = company.get("name", {})
                company_name = name.get("name", "") if isinstance(name, dict) else str(name)
                if not company_name:
                    continue
                events = self.get_events(
                    company_name,
                    event_types=succession_event_types,
                )
                if events:
                    company["succession_signals"] = events
                    candidates.append(company)
        logger.info(
            "NorthData: found %d succession candidates across %d keywords",
            len(candidates), len(keywords),
        )
        return candidates

    def enrich_company(
        self,
        name: str,
        city: Optional[str] = None,
    ) -> dict[str, Any]:
        """Pull all available data for a company into a single dict."""
        profile = self.get_company(name, city) or {}
        financials = self.get_financials(name, city)
        events = self.get_events(name, city)
        profile["financials"] = financials
        profile["events"] = events
        return profile
