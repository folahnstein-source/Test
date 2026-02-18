"""Deal Sourcing Agent for direct private-equity investments in German SMEs.

This agent continuously identifies, qualifies, scores, and tracks acquisition
targets in the German Mittelstand (SME) segment.  It is designed for
independent sponsors and small-to-mid-cap PE firms looking for:

* Succession / Nachfolge situations
* Carve-outs from larger corporates
* Growth-equity opportunities
* Founder-led businesses seeking a partner

The agent manages the full sourcing funnel from initial identification through
due-diligence handoff.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from integrations.opencorporates import OpenCorporatesClient
from integrations.handelsregister import HandelsregisterClient
from integrations.north_data import NorthDataClient
from integrations.news_api import NewsAPIClient
from integrations.rss_feeds import RSSFeedAggregator
from integrations.dub import DUBClient
from integrations.mcp.registry import MCPRegistry
from models.deal import Deal, DealCriteria, DealStage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights – tweak these to change how deals are ranked
# ---------------------------------------------------------------------------
_SCORE_WEIGHTS = {
    "financial_fit": 0.30,
    "sector_fit": 0.15,
    "succession_premium": 0.15,
    "margin_quality": 0.15,
    "size_sweet_spot": 0.15,
    "region_preference": 0.10,
}

# Sectors most attractive for PE buy-and-build in Germany
_PREFERRED_SECTORS = [
    "Industrials",
    "Healthcare",
    "Technology",
    "Business Services",
]

# Revenue sweet-spot centre (EUR) for scoring bell-curve
_REVENUE_SWEET_SPOT = 30_000_000


class DealSourcingAgent:
    """Sources and manages PE deal opportunities in the German Mittelstand.

    Typical usage::

        agent = DealSourcingAgent()
        agent.set_criteria(min_revenue_eur=10e6, max_revenue_eur=100e6)

        # Ingest from an external data source
        agent.ingest_deals([...])

        # Or add a single lead manually
        agent.add_deal(Deal(company_name="Müller GmbH", sector="Industrials",
                            region="Bayern", city="München", revenue_eur=25e6))

        # Score and rank the pipeline
        agent.score()

        # View top prospects
        for deal in agent.top_deals(10):
            print(deal.company_name, deal.score)
    """

    def __init__(
        self,
        criteria: Optional[DealCriteria] = None,
        opencorporates_token: Optional[str] = None,
        north_data_key: Optional[str] = None,
        newsapi_key: Optional[str] = None,
        gnews_key: Optional[str] = None,
        mcp_registry: Optional[MCPRegistry] = None,
    ) -> None:
        from agents.base import BaseAgent, DATA_DIR

        self._data_dir = DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._criteria = criteria or DealCriteria()
        self._deals: list[Deal] = self._load_deals()

        # API clients
        self._opencorporates = OpenCorporatesClient(api_token=opencorporates_token)
        self._handelsregister = HandelsregisterClient()
        self._north_data = NorthDataClient(api_key=north_data_key)
        self._news = NewsAPIClient(newsapi_key=newsapi_key, gnews_key=gnews_key)
        self._rss = RSSFeedAggregator()
        self._dub = DUBClient()

        # MCP server registry
        self._mcp = mcp_registry or MCPRegistry()

        logger.info(
            "DealSourcingAgent ready – %d deals in pipeline, criteria: rev €%.0fM–€%.0fM, "
            "APIs: OpenCorporates=%s NorthData=%s News=%s MCP=%d servers",
            len(self._deals),
            self._criteria.min_revenue_eur / 1e6,
            self._criteria.max_revenue_eur / 1e6,
            bool(opencorporates_token),
            self._north_data.is_configured,
            self._news.is_configured,
            len(self._mcp.connected_servers),
        )

    # -- persistence ----------------------------------------------------------

    def _deal_path(self):
        return self._data_dir / "deals.json"

    def _load_deals(self) -> list[Deal]:
        import json
        path = self._deal_path()
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                return [Deal.from_dict(d) for d in json.load(fh)]
        return []

    def _save_deals(self) -> None:
        import json
        with open(self._deal_path(), "w", encoding="utf-8") as fh:
            json.dump([d.to_dict() for d in self._deals], fh, indent=2, ensure_ascii=False)

    # -- criteria -------------------------------------------------------------

    @property
    def criteria(self) -> DealCriteria:
        return self._criteria

    def set_criteria(self, **kwargs: Any) -> DealCriteria:
        """Update search criteria.  Accepts any ``DealCriteria`` field."""
        for key, val in kwargs.items():
            if hasattr(self._criteria, key):
                setattr(self._criteria, key, val)
            else:
                raise ValueError(f"Unknown criterion: {key}")
        logger.info("Criteria updated: %s", kwargs)
        return self._criteria

    # -- deal management ------------------------------------------------------

    def add_deal(self, deal: Deal) -> Deal:
        """Add a single deal to the pipeline."""
        for existing in self._deals:
            if existing.company_name.lower() == deal.company_name.lower():
                logger.info("Duplicate skipped: %s", deal.company_name)
                return existing
        self._deals.append(deal)
        self._save_deals()
        logger.info("Deal added: %s (id=%s)", deal.company_name, deal.id)
        return deal

    def ingest_deals(self, raw_deals: list[dict]) -> list[Deal]:
        """Bulk-ingest deals from an external data source.

        Each dict must contain at least ``company_name``, ``sector``,
        ``region``, and ``city``.  Extra fields are passed through to the
        ``Deal`` constructor.
        """
        added: list[Deal] = []
        for raw in raw_deals:
            try:
                deal = Deal(**raw)
            except TypeError as exc:
                logger.warning("Skipping malformed deal record: %s – %s", raw, exc)
                continue

            if not deal.matches_criteria(self._criteria):
                logger.debug("Filtered out (criteria): %s", deal.company_name)
                continue

            result = self.add_deal(deal)
            if result.id == deal.id:
                added.append(deal)
        logger.info("Ingested %d / %d deals", len(added), len(raw_deals))
        return added

    def update_deal(self, deal_id: str, **kwargs: Any) -> Optional[Deal]:
        """Update fields on an existing deal."""
        for deal in self._deals:
            if deal.id == deal_id:
                for k, v in kwargs.items():
                    if hasattr(deal, k):
                        setattr(deal, k, v)
                deal.updated_at = datetime.utcnow().isoformat()
                self._save_deals()
                return deal
        return None

    def advance_stage(self, deal_id: str, new_stage: DealStage) -> Optional[Deal]:
        """Move a deal to the next pipeline stage."""
        return self.update_deal(deal_id, stage=new_stage)

    def remove_deal(self, deal_id: str) -> bool:
        before = len(self._deals)
        self._deals = [d for d in self._deals if d.id != deal_id]
        if len(self._deals) < before:
            self._save_deals()
            return True
        return False

    def get_deal(self, deal_id: str) -> Optional[Deal]:
        for deal in self._deals:
            if deal.id == deal_id:
                return deal
        return None

    # -- sourcing (multi-API + MCP) -------------------------------------------

    def source(self, raw_deals: Optional[list[dict]] = None, **kwargs: Any) -> list[Deal]:
        """Run a full sourcing cycle across all connected APIs and MCP servers.

        Data flow:
        1. Ingest any manually provided ``raw_deals``
        2. Query OpenCorporates for German SMEs matching sector keywords
        3. Query Handelsregister for registered companies
        4. Query North Data for succession / ownership-change signals
        5. Query DUB.de + nexxt-change.org for business-for-sale listings
        6. Scan news APIs for M&A / succession deal signals
        7. Scan RSS feeds for Mittelstand deal-flow intelligence
        8. Call any connected MCP servers that provide deal-sourcing tools
        """
        all_new: list[Deal] = []

        # 0. Manual / direct ingest
        if raw_deals:
            all_new.extend(self.ingest_deals(raw_deals))

        # 1. OpenCorporates – German company registry
        all_new.extend(self._source_opencorporates())

        # 2. Handelsregister – official German commercial register
        all_new.extend(self._source_handelsregister())

        # 3. North Data – company intelligence + succession signals
        all_new.extend(self._source_north_data())

        # 4. DUB.de + nexxt-change.org – business-for-sale platforms
        all_new.extend(self._source_dub())

        # 5. News APIs – M&A / succession news signals
        all_new.extend(self._source_news())

        # 6. RSS feeds – industry press
        all_new.extend(self._source_rss())

        # 7. MCP servers – any additional deal-sourcing tools
        all_new.extend(self._source_mcp())

        logger.info(
            "DealSourcingAgent: sourcing cycle complete – %d new deals from all sources",
            len(all_new),
        )
        return all_new

    def _source_opencorporates(self) -> list[Deal]:
        """Query OpenCorporates for German SMEs matching target sectors."""
        sector_keywords = [s.lower() for s in self._criteria.target_sectors[:6]]
        try:
            companies = self._opencorporates.search_german_smes(
                sector_keywords=sector_keywords,
                regions=self._criteria.target_regions,
                per_page=30,
            )
        except Exception as exc:
            logger.warning("OpenCorporates sourcing failed: %s", exc)
            return []

        raw_deals: list[dict] = []
        for company in companies:
            name = company.get("name", "")
            if not name:
                continue
            addr = company.get("registered_address_in_full", "") or ""
            region = self._infer_region(addr)
            city = self._infer_city(addr)
            raw_deals.append({
                "company_name": name,
                "sector": self._infer_sector(name),
                "region": region,
                "city": city,
                "source": "opencorporates",
                "source_url": company.get("opencorporates_url", ""),
                "description": f"Status: {company.get('current_status', 'unknown')}",
            })

        return self.ingest_deals(raw_deals) if raw_deals else []

    def _source_handelsregister(self) -> list[Deal]:
        """Query Handelsregister for companies matching target sectors."""
        keywords = self._criteria.target_sectors[:4]
        try:
            results = self._handelsregister.lookup_gmbh_candidates(
                keywords=keywords,
                regions=self._criteria.target_regions[:3],
            )
        except Exception as exc:
            logger.warning("Handelsregister sourcing failed: %s", exc)
            return []

        raw_deals: list[dict] = []
        for r in results:
            name = r.get("name", "")
            if not name:
                continue
            raw_deals.append({
                "company_name": name,
                "sector": self._infer_sector(name),
                "region": r.get("register_court", "Deutschland"),
                "city": r.get("register_court", ""),
                "source": "handelsregister",
                "description": f"Register: {r.get('register_number', '')}",
            })

        return self.ingest_deals(raw_deals) if raw_deals else []

    def _source_north_data(self) -> list[Deal]:
        """Query North Data for companies with succession signals."""
        if not self._north_data.is_configured:
            logger.debug("NorthData: skipped (no API key)")
            return []

        keywords = self._criteria.target_sectors[:4]
        try:
            candidates = self._north_data.find_succession_candidates(
                keywords=keywords,
                country="DE",
            )
        except Exception as exc:
            logger.warning("NorthData sourcing failed: %s", exc)
            return []

        raw_deals: list[dict] = []
        for c in candidates:
            name_data = c.get("name", {})
            company_name = name_data.get("name", "") if isinstance(name_data, dict) else str(name_data)
            if not company_name:
                continue

            city = ""
            if isinstance(name_data, dict):
                city = name_data.get("city", "")

            signals = c.get("succession_signals", [])
            desc = "; ".join(
                e.get("type", "") for e in signals[:3]
            ) if signals else "succession candidate"

            raw_deals.append({
                "company_name": company_name,
                "sector": self._infer_sector(company_name),
                "region": self._infer_region(city),
                "city": city,
                "is_succession": True,
                "source": "north_data",
                "description": f"Signals: {desc}",
            })

        return self.ingest_deals(raw_deals) if raw_deals else []

    def _source_dub(self) -> list[Deal]:
        """Scan DUB.de and nexxt-change.org for business-for-sale listings."""
        try:
            listings = self._dub.scan_all(
                min_revenue=self._criteria.min_revenue_eur,
                max_revenue=self._criteria.max_revenue_eur,
            )
        except Exception as exc:
            logger.warning("DUB/nexxt-change sourcing failed: %s", exc)
            return []

        raw_deals: list[dict] = []
        for listing in listings:
            title = listing.get("title", "")
            if not title:
                continue
            location = listing.get("location", "")
            raw_deals.append({
                "company_name": title,
                "sector": self._infer_sector(title),
                "region": self._infer_region(location),
                "city": location,
                "revenue_eur": listing.get("revenue_eur"),
                "is_succession": listing.get("is_succession", True),
                "source": listing.get("source", "dub.de"),
                "source_url": listing.get("url", ""),
                "description": "Business-for-sale listing",
            })

        return self.ingest_deals(raw_deals) if raw_deals else []

    def _source_news(self) -> list[Deal]:
        """Scan news APIs for M&A / succession signals in Germany."""
        if not self._news.is_configured:
            logger.debug("NewsAPI: skipped (no API key configured)")
            return []

        try:
            articles = self._news.scan_deal_signals(max_per_keyword=5)
        except Exception as exc:
            logger.warning("News API sourcing failed: %s", exc)
            return []

        raw_deals: list[dict] = []
        for article in articles:
            title = article.get("title", "")
            if not title:
                continue
            raw_deals.append({
                "company_name": title[:80],
                "sector": self._infer_sector(title),
                "region": "Deutschland",
                "city": "",
                "source": "news_api",
                "source_url": article.get("url", ""),
                "description": article.get("description", "")[:200],
            })

        return self.ingest_deals(raw_deals) if raw_deals else []

    def _source_rss(self) -> list[Deal]:
        """Scan RSS feeds for deal-flow signals."""
        try:
            items = self._rss.scan_deal_feeds()
        except Exception as exc:
            logger.warning("RSS sourcing failed: %s", exc)
            return []

        raw_deals: list[dict] = []
        for item in items:
            title = item.get("title", "")
            if not title:
                continue
            raw_deals.append({
                "company_name": title[:80],
                "sector": self._infer_sector(title),
                "region": "Deutschland",
                "city": "",
                "source": f"rss:{item.get('feed_source', '')}",
                "source_url": item.get("link", ""),
                "description": item.get("description", "")[:200],
            })

        return self.ingest_deals(raw_deals) if raw_deals else []

    def _source_mcp(self) -> list[Deal]:
        """Call deal-sourcing tools on any connected MCP servers."""
        if not self._mcp.connected_servers:
            return []

        all_raw: list[dict] = []
        all_tools = self._mcp.all_tools()

        for server_name, tools in all_tools.items():
            for tool in tools:
                # Look for tools whose names suggest deal/company sourcing
                if any(kw in tool.name.lower() for kw in (
                    "deal", "company", "search", "source", "find", "list",
                    "mittelstand", "sme", "nachfolge",
                )):
                    logger.info("MCP: calling %s.%s", server_name, tool.name)
                    result = self._mcp.call_tool_safe(
                        tool.name,
                        arguments={
                            "sectors": self._criteria.target_sectors,
                            "regions": self._criteria.target_regions,
                            "min_revenue": self._criteria.min_revenue_eur,
                            "max_revenue": self._criteria.max_revenue_eur,
                        },
                        server=server_name,
                    )
                    if isinstance(result, list):
                        all_raw.extend(result)
                    elif isinstance(result, str):
                        # Try to parse as JSON
                        import json
                        try:
                            parsed = json.loads(result)
                            if isinstance(parsed, list):
                                all_raw.extend(parsed)
                        except json.JSONDecodeError:
                            logger.debug("MCP tool %s returned non-JSON: %s", tool.name, result[:100])

        return self.ingest_deals(all_raw) if all_raw else []

    # -- helpers for normalising external data --------------------------------

    _SECTOR_KEYWORDS = {
        "Industrials": ["maschin", "industri", "fertigung", "manufactur", "produktion", "werkzeug"],
        "Healthcare": ["medizin", "medical", "health", "pharma", "klinik", "pflege", "med"],
        "Technology": ["software", "it-", "tech", "digital", "daten", "cyber", "cloud", "saas"],
        "Business Services": ["dienstleist", "service", "beratung", "consult", "logistik", "personal"],
        "Consumer Goods": ["konsum", "consumer", "verpackung", "nahrung", "food", "einzelhandel"],
        "Automotive Suppliers": ["automobil", "automotive", "fahrzeug", "kfz", "zulieferer"],
    }

    def _infer_sector(self, text: str) -> str:
        """Best-effort sector classification from company name / text."""
        lower = text.lower()
        for sector, keywords in self._SECTOR_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return sector
        return "Industrials"  # default for Mittelstand

    _REGION_MAP = {
        "stuttgart": "Baden-Württemberg", "mannheim": "Baden-Württemberg",
        "freiburg": "Baden-Württemberg", "karlsruhe": "Baden-Württemberg",
        "heidelberg": "Baden-Württemberg", "ulm": "Baden-Württemberg",
        "münchen": "Bayern", "munich": "Bayern", "nürnberg": "Bayern",
        "augsburg": "Bayern", "regensburg": "Bayern", "würzburg": "Bayern",
        "berlin": "Berlin",
        "hamburg": "Hamburg",
        "frankfurt": "Hessen", "darmstadt": "Hessen", "wiesbaden": "Hessen",
        "kassel": "Hessen",
        "hannover": "Niedersachsen", "braunschweig": "Niedersachsen",
        "oldenburg": "Niedersachsen", "osnabrück": "Niedersachsen",
        "düsseldorf": "Nordrhein-Westfalen", "köln": "Nordrhein-Westfalen",
        "cologne": "Nordrhein-Westfalen", "dortmund": "Nordrhein-Westfalen",
        "essen": "Nordrhein-Westfalen", "bielefeld": "Nordrhein-Westfalen",
        "bonn": "Nordrhein-Westfalen", "aachen": "Nordrhein-Westfalen",
        "dresden": "Sachsen", "leipzig": "Sachsen", "chemnitz": "Sachsen",
        "kiel": "Schleswig-Holstein", "lübeck": "Schleswig-Holstein",
        "baden-württemberg": "Baden-Württemberg", "bayern": "Bayern",
        "hessen": "Hessen", "niedersachsen": "Niedersachsen",
        "nordrhein-westfalen": "Nordrhein-Westfalen",
    }

    def _infer_region(self, text: str) -> str:
        lower = text.lower()
        for keyword, region in self._REGION_MAP.items():
            if keyword in lower:
                return region
        return "Deutschland"

    def _infer_city(self, text: str) -> str:
        lower = text.lower()
        cities = [
            "stuttgart", "münchen", "nürnberg", "frankfurt", "düsseldorf",
            "köln", "hamburg", "berlin", "hannover", "dortmund", "essen",
            "dresden", "leipzig", "karlsruhe", "mannheim", "augsburg",
        ]
        for city in cities:
            if city in lower:
                return city.capitalize()
        return ""

    # -- scoring --------------------------------------------------------------

    def _score_deal(self, deal: Deal) -> float:
        """Compute a 0-100 score for a single deal."""
        scores: dict[str, float] = {}

        # 1. Financial fit: does it match revenue / EBITDA criteria?
        if deal.revenue_eur is not None:
            rev = deal.revenue_eur
            if self._criteria.min_revenue_eur <= rev <= self._criteria.max_revenue_eur:
                scores["financial_fit"] = 100.0
            else:
                scores["financial_fit"] = 0.0
        else:
            scores["financial_fit"] = 50.0  # unknown = neutral

        # 2. Sector fit
        if deal.sector in _PREFERRED_SECTORS:
            scores["sector_fit"] = 100.0
        elif deal.sector in self._criteria.target_sectors:
            scores["sector_fit"] = 70.0
        else:
            scores["sector_fit"] = 20.0

        # 3. Succession premium
        scores["succession_premium"] = 100.0 if deal.is_succession else 30.0

        # 4. Margin quality
        if deal.ebitda_margin is not None:
            if deal.ebitda_margin >= 0.20:
                scores["margin_quality"] = 100.0
            elif deal.ebitda_margin >= 0.12:
                scores["margin_quality"] = 70.0
            elif deal.ebitda_margin >= 0.08:
                scores["margin_quality"] = 40.0
            else:
                scores["margin_quality"] = 10.0
        else:
            scores["margin_quality"] = 50.0

        # 5. Size sweet-spot (prefer ~€30M revenue)
        if deal.revenue_eur is not None:
            distance = abs(deal.revenue_eur - _REVENUE_SWEET_SPOT) / _REVENUE_SWEET_SPOT
            scores["size_sweet_spot"] = max(0.0, 100.0 * (1 - distance))
        else:
            scores["size_sweet_spot"] = 50.0

        # 6. Region preference (top Mittelstand regions)
        top_regions = {"Baden-Württemberg", "Bayern", "Nordrhein-Westfalen"}
        if deal.region in top_regions:
            scores["region_preference"] = 100.0
        elif deal.region in self._criteria.target_regions:
            scores["region_preference"] = 60.0
        else:
            scores["region_preference"] = 30.0

        # Weighted total
        total = sum(
            scores.get(k, 50.0) * w for k, w in _SCORE_WEIGHTS.items()
        )
        return round(total, 1)

    def score(self) -> None:
        """Re-score all deals in the pipeline."""
        for deal in self._deals:
            deal.score = self._score_deal(deal)
        self._deals.sort(key=lambda d: d.score, reverse=True)
        self._save_deals()
        logger.info("Scored %d deals", len(self._deals))

    # -- querying -------------------------------------------------------------

    def top_deals(self, n: int = 10) -> list[Deal]:
        """Return the *n* highest-scored deals."""
        return sorted(self._deals, key=lambda d: d.score, reverse=True)[:n]

    def deals_by_stage(self, stage: DealStage) -> list[Deal]:
        return [d for d in self._deals if d.stage == stage]

    def deals_by_sector(self, sector: str) -> list[Deal]:
        return [d for d in self._deals if d.sector == sector]

    def deals_by_region(self, region: str) -> list[Deal]:
        return [d for d in self._deals if d.region == region]

    def search_deals(self, query: str) -> list[Deal]:
        """Simple text search across company name, sector, description."""
        q = query.lower()
        return [
            d for d in self._deals
            if q in d.company_name.lower()
            or q in d.sector.lower()
            or q in d.description.lower()
            or q in d.city.lower()
        ]

    @property
    def pipeline(self) -> list[Deal]:
        """All deals, sorted by score descending."""
        return sorted(self._deals, key=lambda d: d.score, reverse=True)

    # -- reporting ------------------------------------------------------------

    def report(self) -> dict:
        """Generate a pipeline summary."""
        stage_counts = Counter(d.stage.value for d in self._deals)
        sector_counts = Counter(d.sector for d in self._deals)
        region_counts = Counter(d.region for d in self._deals)

        avg_score = (
            sum(d.score for d in self._deals) / len(self._deals)
            if self._deals
            else 0.0
        )

        succession_count = sum(1 for d in self._deals if d.is_succession)

        return {
            "total_deals": len(self._deals),
            "avg_score": round(avg_score, 1),
            "by_stage": dict(stage_counts),
            "by_sector": dict(sector_counts),
            "by_region": dict(region_counts),
            "succession_deals": succession_count,
            "top_5": [
                {"name": d.company_name, "score": d.score, "stage": d.stage.value}
                for d in self.top_deals(5)
            ],
        }

    # -- full cycle -----------------------------------------------------------

    def run_cycle(self, raw_deals: Optional[list[dict]] = None, **kwargs: Any) -> dict:
        """Execute a complete source -> score -> report cycle."""
        logger.info("DealSourcingAgent: starting cycle")
        self.source(raw_deals=raw_deals, **kwargs)
        self.score()
        summary = self.report()
        logger.info("DealSourcingAgent: cycle complete – %d deals", summary["total_deals"])
        return summary
