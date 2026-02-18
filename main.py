#!/usr/bin/env python3
"""Entry point – demonstrates both sourcing agents with sample data."""

import json
import logging
import sys

import config
from agents.deal_sourcing import DealSourcingAgent
from agents.fundraising import FundraisingAgent
from models.deal import Deal, DealCriteria, DealStage
from models.investor import Investor, InvestorStatus, InvestorType

logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sample data – replace with real integrations in production
# ---------------------------------------------------------------------------

SAMPLE_DEALS = [
    {
        "company_name": "Müller Maschinenbau GmbH",
        "sector": "Industrials",
        "region": "Baden-Württemberg",
        "city": "Stuttgart",
        "revenue_eur": 35_000_000,
        "ebitda_eur": 5_250_000,
        "ebitda_margin": 0.15,
        "employee_count": 180,
        "is_succession": True,
        "source": "M&A Advisor",
        "description": "Precision machinery manufacturer, founder retiring",
    },
    {
        "company_name": "Schmidt MedTech AG",
        "sector": "Healthcare",
        "region": "Bayern",
        "city": "München",
        "revenue_eur": 22_000_000,
        "ebitda_eur": 4_400_000,
        "ebitda_margin": 0.20,
        "employee_count": 95,
        "is_succession": False,
        "source": "Industry conference",
        "description": "Medical device manufacturer seeking growth capital",
    },
    {
        "company_name": "Weber IT-Solutions GmbH",
        "sector": "Technology",
        "region": "Hessen",
        "city": "Frankfurt",
        "revenue_eur": 12_000_000,
        "ebitda_eur": 2_400_000,
        "ebitda_margin": 0.20,
        "employee_count": 60,
        "is_succession": True,
        "source": "Nachfolge.de",
        "description": "IT services company, owner looking for succession",
    },
    {
        "company_name": "Bauer Automotive Zulieferer GmbH",
        "sector": "Automotive Suppliers",
        "region": "Nordrhein-Westfalen",
        "city": "Düsseldorf",
        "revenue_eur": 85_000_000,
        "ebitda_eur": 6_800_000,
        "ebitda_margin": 0.08,
        "employee_count": 420,
        "is_succession": False,
        "is_carve_out": True,
        "source": "Corporate advisor",
        "description": "Carve-out from large OEM, strong niche position",
    },
    {
        "company_name": "Fischer Verpackung GmbH",
        "sector": "Consumer Goods",
        "region": "Bayern",
        "city": "Nürnberg",
        "revenue_eur": 18_000_000,
        "ebitda_eur": 3_600_000,
        "ebitda_margin": 0.20,
        "employee_count": 110,
        "is_succession": True,
        "source": "DUB.de",
        "description": "Sustainable packaging, strong regional brand",
    },
]

SAMPLE_INVESTORS = [
    {
        "name": "Huber Family Office",
        "investor_type": "family_office",
        "country": "DE",
        "city": "München",
        "min_ticket_eur": 2_000_000,
        "max_ticket_eur": 10_000_000,
        "typical_ticket_eur": 5_000_000,
        "sector_preferences": ["Industrials", "Healthcare", "Technology"],
        "co_invest_appetite": True,
        "independent_sponsor_friendly": True,
    },
    {
        "name": "Alpine Capital Partners",
        "investor_type": "pe_fund",
        "country": "AT",
        "city": "Wien",
        "min_ticket_eur": 5_000_000,
        "max_ticket_eur": 25_000_000,
        "typical_ticket_eur": 12_000_000,
        "sector_preferences": ["Industrials", "Business Services"],
        "co_invest_appetite": True,
        "independent_sponsor_friendly": True,
    },
    {
        "name": "Zürich Private Equity AG",
        "investor_type": "pe_fund",
        "country": "CH",
        "city": "Zürich",
        "min_ticket_eur": 3_000_000,
        "max_ticket_eur": 15_000_000,
        "typical_ticket_eur": 8_000_000,
        "sector_preferences": ["Healthcare", "Technology"],
        "co_invest_appetite": True,
        "independent_sponsor_friendly": False,
        "requires_board_seat": True,
    },
    {
        "name": "Rhein-Main Family Office",
        "investor_type": "family_office",
        "country": "DE",
        "city": "Frankfurt",
        "min_ticket_eur": 1_000_000,
        "max_ticket_eur": 7_000_000,
        "typical_ticket_eur": 3_000_000,
        "sector_preferences": ["Technology", "Consumer Goods"],
        "co_invest_appetite": True,
        "independent_sponsor_friendly": True,
    },
    {
        "name": "Norddeutsche Beteiligungsgesellschaft",
        "investor_type": "institutional",
        "country": "DE",
        "city": "Hamburg",
        "min_ticket_eur": 10_000_000,
        "max_ticket_eur": 50_000_000,
        "typical_ticket_eur": 20_000_000,
        "sector_preferences": [],
        "co_invest_appetite": True,
        "independent_sponsor_friendly": True,
    },
    {
        "name": "Dr. Becker HNWI",
        "investor_type": "hnwi",
        "country": "DE",
        "city": "Düsseldorf",
        "min_ticket_eur": 500_000,
        "max_ticket_eur": 3_000_000,
        "typical_ticket_eur": 1_500_000,
        "sector_preferences": ["Healthcare", "Industrials"],
        "co_invest_appetite": True,
        "independent_sponsor_friendly": True,
    },
    {
        "name": "Wiener Stadtwerke Pension",
        "investor_type": "pension_fund",
        "country": "AT",
        "city": "Wien",
        "min_ticket_eur": 5_000_000,
        "max_ticket_eur": 30_000_000,
        "typical_ticket_eur": 15_000_000,
        "sector_preferences": ["Industrials", "Healthcare"],
        "co_invest_appetite": True,
        "independent_sponsor_friendly": False,
        "requires_lead": True,
    },
]


def _pp(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def demo_deal_sourcing() -> None:
    """Run the deal sourcing agent with sample data."""
    print("\n" + "=" * 72)
    print("  DEAL SOURCING AGENT – German Mittelstand PE Opportunities")
    print("=" * 72)

    agent = DealSourcingAgent(
        criteria=DealCriteria(
            min_revenue_eur=10_000_000,
            max_revenue_eur=100_000_000,
        )
    )

    summary = agent.run_cycle(raw_deals=SAMPLE_DEALS)

    print(f"\nPipeline summary:\n{_pp(summary)}")

    print("\nTop deals:")
    for i, deal in enumerate(agent.top_deals(5), 1):
        print(
            f"  {i}. {deal.company_name:40s} | Score: {deal.score:5.1f} "
            f"| Rev: €{deal.revenue_eur/1e6:.0f}M | {deal.sector} | {deal.region}"
        )

    print("\nSuccession opportunities:")
    for deal in agent.pipeline:
        if deal.is_succession:
            print(f"  - {deal.company_name} ({deal.city}) – {deal.description}")

    return agent


def demo_fundraising(deal_agent: DealSourcingAgent | None = None) -> None:
    """Run the fundraising agent with sample data and optional deal matching."""
    print("\n" + "=" * 72)
    print("  FUNDRAISING AGENT – Co-Investor Sourcing for Independent Sponsors")
    print("=" * 72)

    agent = FundraisingAgent()

    summary = agent.run_cycle(raw_investors=SAMPLE_INVESTORS)

    print(f"\nInvestor database summary:\n{_pp(summary)}")

    print("\nTop investors:")
    for i, inv in enumerate(agent.top_investors(5), 1):
        ticket = f"€{inv.typical_ticket_eur/1e6:.0f}M" if inv.typical_ticket_eur else "n/a"
        print(
            f"  {i}. {inv.name:40s} | Score: {inv.relationship_score:5.1f} "
            f"| Ticket: {ticket:>5s} | {inv.investor_type.value} | {inv.country}"
        )

    # Match investors to the top deal from the deal-sourcing agent
    if deal_agent and deal_agent.pipeline:
        top_deal = deal_agent.top_deals(1)[0]
        equity_needed = (top_deal.revenue_eur or 30e6) * 0.4  # rough 40% equity assumption

        print(f"\nOutreach list for: {top_deal.company_name} (equity ~€{equity_needed/1e6:.0f}M)")
        outreach = agent.outreach_list(top_deal, equity_required_eur=equity_needed, top_n=10)
        for entry in outreach:
            ticket = (
                f"€{entry['typical_ticket_eur']/1e6:.0f}M"
                if entry["typical_ticket_eur"]
                else "n/a"
            )
            print(
                f"  #{entry['rank']:2d}  {entry['investor_name']:40s} | "
                f"Ticket: {ticket:>5s} | {entry['type']:15s} | {entry['country']}"
            )


def main() -> None:
    deal_agent = demo_deal_sourcing()
    demo_fundraising(deal_agent)

    print("\n" + "=" * 72)
    print("  Demo complete. See data/ for persisted JSON files.")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
