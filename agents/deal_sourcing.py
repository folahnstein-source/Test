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

    def __init__(self, criteria: Optional[DealCriteria] = None) -> None:
        from agents.base import BaseAgent, DATA_DIR

        self._data_dir = DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._criteria = criteria or DealCriteria()
        self._deals: list[Deal] = self._load_deals()
        logger.info(
            "DealSourcingAgent ready – %d deals in pipeline, criteria: rev €%.0fM–€%.0fM",
            len(self._deals),
            self._criteria.min_revenue_eur / 1e6,
            self._criteria.max_revenue_eur / 1e6,
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

    # -- sourcing (pluggable) -------------------------------------------------

    def source(self, raw_deals: Optional[list[dict]] = None, **kwargs: Any) -> list[Deal]:
        """Run a sourcing cycle.

        If ``raw_deals`` is provided, they are ingested directly.  In a
        production setup this method would call external APIs (e.g.
        Handelsregister, Bundesanzeiger, news feeds, broker platforms).
        """
        if raw_deals:
            return self.ingest_deals(raw_deals)

        # Placeholder: in production, this would query external data sources
        # such as:
        #   - Bundesanzeiger (financial filings)
        #   - Handelsregister (company registry)
        #   - M&A broker platforms (CARL, DUB, Nachfolge.de)
        #   - Industry news feeds
        #   - LinkedIn / XING for succession signals
        #   - Conference attendee lists (e.g. Deutsche Mittelstandstage)
        logger.info(
            "source() called without raw_deals – connect external feeds for "
            "automated sourcing"
        )
        return []

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
