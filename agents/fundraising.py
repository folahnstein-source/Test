"""Fundraising Agent for sourcing co-investors for independent sponsors in DACH.

This agent builds and maintains a database of potential co-investment partners
across Germany, Austria, and Switzerland.  It is tailored for independent
sponsors (fundless sponsors) who need to assemble equity for each deal from
a pool of recurring capital partners.

Target investor universe:

* Family offices (single & multi)
* Small / mid-cap PE funds open to co-investments
* Institutional investors (pension funds, insurers)
* HNWIs with direct-investment mandates
* Development banks (KfW, AWS, etc.) and state-backed vehicles
* Fund-of-funds with co-invest sleeves

The agent tracks relationship status, matches investors to specific deals,
and produces outreach lists ranked by fit.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from models.deal import Deal
from models.investor import Investor, InvestorStatus, InvestorType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights for investor attractiveness
# ---------------------------------------------------------------------------
_INVESTOR_WEIGHTS = {
    "co_invest_friendliness": 0.25,
    "ticket_fit": 0.20,
    "sector_alignment": 0.15,
    "relationship_warmth": 0.15,
    "track_record": 0.10,
    "speed_reputation": 0.10,
    "geography_match": 0.05,
}

# Investor types most aligned with independent-sponsor model
_PREFERRED_TYPES = {
    InvestorType.FAMILY_OFFICE,
    InvestorType.HNWI,
    InvestorType.PE_FUND,
}

DACH_COUNTRIES = {"DE", "AT", "CH"}


class FundraisingAgent:
    """Sources and manages co-investor relationships for independent sponsors.

    Typical usage::

        agent = FundraisingAgent()

        # Add investors manually or in bulk
        agent.add_investor(Investor(
            name="Müller Family Office",
            investor_type=InvestorType.FAMILY_OFFICE,
            country="DE",
            city="München",
            min_ticket_eur=1e6,
            max_ticket_eur=10e6,
            sector_preferences=["Industrials", "Healthcare"],
        ))

        agent.ingest_investors([...])

        # Score and rank
        agent.score()

        # Match investors to a specific deal
        matches = agent.match_to_deal(deal, equity_required=15e6)

        # Generate outreach list
        outreach = agent.outreach_list(deal, top_n=20)
    """

    def __init__(self) -> None:
        from agents.base import DATA_DIR

        self._data_dir = DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._investors: list[Investor] = self._load_investors()
        logger.info(
            "FundraisingAgent ready – %d investors in database",
            len(self._investors),
        )

    # -- persistence ----------------------------------------------------------

    def _investor_path(self):
        return self._data_dir / "investors.json"

    def _load_investors(self) -> list[Investor]:
        import json
        path = self._investor_path()
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                return [Investor.from_dict(d) for d in json.load(fh)]
        return []

    def _save_investors(self) -> None:
        import json
        with open(self._investor_path(), "w", encoding="utf-8") as fh:
            json.dump(
                [i.to_dict() for i in self._investors],
                fh, indent=2, ensure_ascii=False,
            )

    # -- investor management --------------------------------------------------

    def add_investor(self, investor: Investor) -> Investor:
        """Add a single investor, skipping duplicates by name."""
        for existing in self._investors:
            if existing.name.lower() == investor.name.lower():
                logger.info("Duplicate skipped: %s", investor.name)
                return existing
        self._investors.append(investor)
        self._save_investors()
        logger.info("Investor added: %s (id=%s)", investor.name, investor.id)
        return investor

    def ingest_investors(self, raw_investors: list[dict]) -> list[Investor]:
        """Bulk-ingest investor records from an external source."""
        added: list[Investor] = []
        for raw in raw_investors:
            try:
                inv = Investor(**raw)
            except TypeError as exc:
                logger.warning("Skipping malformed investor record: %s – %s", raw, exc)
                continue

            if inv.country not in DACH_COUNTRIES:
                logger.debug("Filtered out (non-DACH): %s", inv.name)
                continue

            result = self.add_investor(inv)
            if result.id == inv.id:
                added.append(inv)
        logger.info("Ingested %d / %d investors", len(added), len(raw_investors))
        return added

    def update_investor(self, investor_id: str, **kwargs: Any) -> Optional[Investor]:
        for inv in self._investors:
            if inv.id == investor_id:
                for k, v in kwargs.items():
                    if hasattr(inv, k):
                        setattr(inv, k, v)
                inv.updated_at = datetime.utcnow().isoformat()
                self._save_investors()
                return inv
        return None

    def update_status(self, investor_id: str, status: InvestorStatus) -> Optional[Investor]:
        return self.update_investor(investor_id, status=status)

    def log_interaction(self, investor_id: str, note: str) -> Optional[Investor]:
        """Record a touchpoint with an investor."""
        now = datetime.utcnow().isoformat()
        for inv in self._investors:
            if inv.id == investor_id:
                inv.last_interaction = now
                inv.notes = (inv.notes + f"\n[{now}] {note}").strip()
                inv.updated_at = now
                self._save_investors()
                return inv
        return None

    def remove_investor(self, investor_id: str) -> bool:
        before = len(self._investors)
        self._investors = [i for i in self._investors if i.id != investor_id]
        if len(self._investors) < before:
            self._save_investors()
            return True
        return False

    def get_investor(self, investor_id: str) -> Optional[Investor]:
        for inv in self._investors:
            if inv.id == investor_id:
                return inv
        return None

    # -- sourcing (pluggable) -------------------------------------------------

    def source(self, raw_investors: Optional[list[dict]] = None, **kwargs: Any) -> list[Investor]:
        """Run a sourcing cycle.

        If ``raw_investors`` is provided, they are ingested directly.  In
        production this method would call external APIs and databases:

        * BaFin / FMA / FINMA registers for regulated entities
        * Family-office directories (e.g. Listenchampion, Finleap)
        * PE databases (Preqin, PitchBook, Majunke)
        * XING / LinkedIn for HNWI identification
        * Conference and event attendee lists
        * Placement-agent networks
        """
        if raw_investors:
            return self.ingest_investors(raw_investors)

        logger.info(
            "source() called without raw_investors – connect external feeds "
            "for automated sourcing"
        )
        return []

    # -- scoring --------------------------------------------------------------

    def _score_investor(self, investor: Investor) -> float:
        """Compute a 0-100 attractiveness score for a single investor."""
        scores: dict[str, float] = {}

        # 1. Co-invest friendliness
        if investor.independent_sponsor_friendly and investor.co_invest_appetite:
            scores["co_invest_friendliness"] = 100.0
        elif investor.co_invest_appetite:
            scores["co_invest_friendliness"] = 60.0
        else:
            scores["co_invest_friendliness"] = 10.0

        # 2. Ticket fit (prefer investors who can write meaningful cheques)
        if investor.typical_ticket_eur is not None:
            if 1_000_000 <= investor.typical_ticket_eur <= 20_000_000:
                scores["ticket_fit"] = 100.0
            elif investor.typical_ticket_eur < 1_000_000:
                scores["ticket_fit"] = 40.0
            else:
                scores["ticket_fit"] = 70.0  # large tickets still useful
        else:
            scores["ticket_fit"] = 50.0

        # 3. Sector alignment (breadth of mandate is a plus)
        if not investor.sector_preferences:
            scores["sector_alignment"] = 80.0  # generalist = flexible
        elif len(investor.sector_preferences) >= 3:
            scores["sector_alignment"] = 90.0
        else:
            scores["sector_alignment"] = 60.0

        # 4. Relationship warmth (based on status)
        warmth_map = {
            InvestorStatus.COMMITTED: 100.0,
            InvestorStatus.INTERESTED: 85.0,
            InvestorStatus.IN_DIALOGUE: 70.0,
            InvestorStatus.CONTACTED: 50.0,
            InvestorStatus.RESEARCHED: 30.0,
            InvestorStatus.IDENTIFIED: 15.0,
            InvestorStatus.DECLINED: 5.0,
            InvestorStatus.DORMANT: 10.0,
        }
        scores["relationship_warmth"] = warmth_map.get(investor.status, 15.0)

        # 5. Track record (preferred investor types for independent sponsors)
        if investor.investor_type in _PREFERRED_TYPES:
            scores["track_record"] = 100.0
        else:
            scores["track_record"] = 50.0

        # 6. Speed reputation (family offices / HNWIs tend to decide faster)
        fast_types = {InvestorType.FAMILY_OFFICE, InvestorType.HNWI}
        scores["speed_reputation"] = 100.0 if investor.investor_type in fast_types else 50.0

        # 7. Geography match
        scores["geography_match"] = 100.0 if investor.country in DACH_COUNTRIES else 30.0

        total = sum(
            scores.get(k, 50.0) * w for k, w in _INVESTOR_WEIGHTS.items()
        )
        return round(total, 1)

    def score(self) -> None:
        """Re-score all investors."""
        for inv in self._investors:
            inv.relationship_score = self._score_investor(inv)
        self._investors.sort(key=lambda i: i.relationship_score, reverse=True)
        self._save_investors()
        logger.info("Scored %d investors", len(self._investors))

    # -- deal matching --------------------------------------------------------

    def match_to_deal(
        self,
        deal: Deal,
        equity_required_eur: Optional[float] = None,
        max_investors: int = 50,
    ) -> list[Investor]:
        """Rank investors by their fit for a specific deal.

        Considers sector alignment, ticket size vs. equity need, geographic
        overlap, and current relationship status.
        """
        candidates: list[tuple[float, Investor]] = []

        for inv in self._investors:
            if inv.status == InvestorStatus.DECLINED:
                continue
            if not inv.co_invest_appetite:
                continue

            fit = 0.0

            # Sector match
            if inv.matches_sector(deal.sector):
                fit += 35.0

            # Ticket vs. equity need
            if equity_required_eur and inv.typical_ticket_eur:
                ratio = inv.typical_ticket_eur / equity_required_eur
                if 0.05 <= ratio <= 0.50:
                    fit += 25.0  # ideal: can take 5-50% of the equity
                elif ratio < 0.05:
                    fit += 5.0
                else:
                    fit += 15.0
            elif equity_required_eur:
                if inv.ticket_in_range(equity_required_eur * 0.2):
                    fit += 20.0

            # Geography (investor covers deal region)
            if inv.matches_geography(deal.region):
                fit += 15.0

            # Relationship quality
            fit += inv.relationship_score * 0.25

            # Independent-sponsor friendliness bonus
            if inv.independent_sponsor_friendly:
                fit += 10.0

            candidates.append((round(fit, 1), inv))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [inv for _, inv in candidates[:max_investors]]

    def outreach_list(
        self,
        deal: Deal,
        equity_required_eur: Optional[float] = None,
        top_n: int = 20,
    ) -> list[dict]:
        """Generate a prioritised outreach list for a deal.

        Returns dicts with investor details and a match-fit score, ready
        for CRM export or email campaigns.
        """
        matched = self.match_to_deal(deal, equity_required_eur, max_investors=top_n)
        outreach: list[dict] = []
        for rank, inv in enumerate(matched, 1):
            outreach.append({
                "rank": rank,
                "investor_name": inv.name,
                "type": inv.investor_type.value,
                "country": inv.country,
                "city": inv.city,
                "typical_ticket_eur": inv.typical_ticket_eur,
                "contact_name": inv.contact_name,
                "contact_email": inv.contact_email,
                "status": inv.status.value,
                "relationship_score": inv.relationship_score,
                "notes": inv.notes,
            })
        return outreach

    # -- querying -------------------------------------------------------------

    def top_investors(self, n: int = 10) -> list[Investor]:
        return sorted(
            self._investors, key=lambda i: i.relationship_score, reverse=True
        )[:n]

    def investors_by_type(self, investor_type: InvestorType) -> list[Investor]:
        return [i for i in self._investors if i.investor_type == investor_type]

    def investors_by_country(self, country: str) -> list[Investor]:
        return [i for i in self._investors if i.country == country]

    def investors_by_status(self, status: InvestorStatus) -> list[Investor]:
        return [i for i in self._investors if i.status == status]

    def search_investors(self, query: str) -> list[Investor]:
        q = query.lower()
        return [
            i for i in self._investors
            if q in i.name.lower()
            or (i.city and q in i.city.lower())
            or q in i.notes.lower()
        ]

    @property
    def database(self) -> list[Investor]:
        return sorted(
            self._investors, key=lambda i: i.relationship_score, reverse=True
        )

    # -- reporting ------------------------------------------------------------

    def report(self) -> dict:
        status_counts = Counter(i.status.value for i in self._investors)
        type_counts = Counter(i.investor_type.value for i in self._investors)
        country_counts = Counter(i.country for i in self._investors)

        avg_score = (
            sum(i.relationship_score for i in self._investors) / len(self._investors)
            if self._investors
            else 0.0
        )

        is_friendly = sum(1 for i in self._investors if i.independent_sponsor_friendly)

        return {
            "total_investors": len(self._investors),
            "avg_relationship_score": round(avg_score, 1),
            "independent_sponsor_friendly": is_friendly,
            "by_status": dict(status_counts),
            "by_type": dict(type_counts),
            "by_country": dict(country_counts),
            "top_5": [
                {
                    "name": i.name,
                    "type": i.investor_type.value,
                    "score": i.relationship_score,
                    "status": i.status.value,
                }
                for i in self.top_investors(5)
            ],
        }

    # -- full cycle -----------------------------------------------------------

    def run_cycle(
        self, raw_investors: Optional[list[dict]] = None, **kwargs: Any
    ) -> dict:
        """Execute a complete source -> score -> report cycle."""
        logger.info("FundraisingAgent: starting cycle")
        self.source(raw_investors=raw_investors, **kwargs)
        self.score()
        summary = self.report()
        logger.info(
            "FundraisingAgent: cycle complete – %d investors",
            summary["total_investors"],
        )
        return summary
