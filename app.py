#!/usr/bin/env python3
"""Flask web application for PE Sourcing Agents.

Provides a dashboard, deal pipeline, investor database, and investor-deal
matching — all backed by the existing DealSourcingAgent and FundraisingAgent.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, url_for

import config
from agents.deal_sourcing import DealSourcingAgent
from agents.fundraising import FundraisingAgent
from integrations.mcp.registry import MCPRegistry
from models.deal import Deal, DealCriteria, DealStage
from models.investor import Investor, InvestorStatus, InvestorType

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pe-sourcing-dev-key")

# ---------------------------------------------------------------------------
# Sample data (loaded on first run if pipeline is empty)
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

# ---------------------------------------------------------------------------
# Agent initialisation (singletons, thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_mcp: MCPRegistry | None = None
_deal_agent: DealSourcingAgent | None = None
_fund_agent: FundraisingAgent | None = None


def _get_mcp() -> MCPRegistry:
    global _mcp
    if _mcp is None:
        _mcp = MCPRegistry()
        loaded = _mcp.load_config()
        if loaded:
            _mcp.connect_all()
    return _mcp


def get_deal_agent() -> DealSourcingAgent:
    global _deal_agent
    with _lock:
        if _deal_agent is None:
            _deal_agent = DealSourcingAgent(
                criteria=DealCriteria(
                    min_revenue_eur=config.DEAL_MIN_REVENUE_EUR,
                    max_revenue_eur=config.DEAL_MAX_REVENUE_EUR,
                ),
                opencorporates_token=config.OPENCORPORATES_TOKEN or None,
                north_data_key=config.NORTH_DATA_API_KEY or None,
                newsapi_key=config.NEWSAPI_KEY or None,
                gnews_key=config.GNEWS_KEY or None,
                mcp_registry=_get_mcp(),
            )
            # Seed with sample data if pipeline is empty
            if not _deal_agent.pipeline:
                _deal_agent.ingest_deals(SAMPLE_DEALS)
                _deal_agent.score()
    return _deal_agent


def get_fund_agent() -> FundraisingAgent:
    global _fund_agent
    with _lock:
        if _fund_agent is None:
            _fund_agent = FundraisingAgent(
                opencorporates_token=config.OPENCORPORATES_TOKEN or None,
                newsapi_key=config.NEWSAPI_KEY or None,
                gnews_key=config.GNEWS_KEY or None,
                mcp_registry=_get_mcp(),
            )
            if not _fund_agent.database:
                _fund_agent.ingest_investors(SAMPLE_INVESTORS)
                _fund_agent.score()
    return _fund_agent


# ---------------------------------------------------------------------------
# Helper: format EUR amounts
# ---------------------------------------------------------------------------
def _fmt_eur(val: float | None) -> str:
    if val is None:
        return "n/a"
    if val >= 1_000_000:
        return f"\u20ac{val / 1e6:.1f}M"
    if val >= 1_000:
        return f"\u20ac{val / 1e3:.0f}K"
    return f"\u20ac{val:.0f}"


# Expose helpers in templates
app.jinja_env.globals["fmt_eur"] = _fmt_eur


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------
@app.template_filter("pct")
def pct_filter(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{val * 100:.1f}%"


# ===================================================================
# HTML VIEWS
# ===================================================================

@app.route("/")
def index():
    """Dashboard — overview of both pipelines."""
    da = get_deal_agent()
    fa = get_fund_agent()
    deal_report = da.report()
    inv_report = fa.report()

    api_status = {
        "OpenCorporates": bool(config.OPENCORPORATES_TOKEN),
        "North Data": bool(config.NORTH_DATA_API_KEY),
        "NewsAPI": bool(config.NEWSAPI_KEY),
        "GNews": bool(config.GNEWS_KEY),
    }

    return render_template(
        "dashboard.html",
        deal_report=deal_report,
        inv_report=inv_report,
        top_deals=da.top_deals(5),
        top_investors=fa.top_investors(5),
        api_status=api_status,
        fmt_eur=_fmt_eur,
    )


# -- Deals ---------------------------------------------------------------

@app.route("/deals")
def deals_list():
    da = get_deal_agent()
    stage = request.args.get("stage")
    sector = request.args.get("sector")
    region = request.args.get("region")
    q = request.args.get("q", "").strip()

    if q:
        deals = da.search_deals(q)
    elif stage:
        deals = da.deals_by_stage(DealStage(stage))
    elif sector:
        deals = da.deals_by_sector(sector)
    elif region:
        deals = da.deals_by_region(region)
    else:
        deals = da.pipeline

    stages = [s.value for s in DealStage]
    sectors = sorted({d.sector for d in da.pipeline})
    regions = sorted({d.region for d in da.pipeline})

    return render_template(
        "deals.html",
        deals=deals,
        stages=stages,
        sectors=sectors,
        regions=regions,
        current_stage=stage,
        current_sector=sector,
        current_region=region,
        query=q,
        fmt_eur=_fmt_eur,
    )


@app.route("/deals/<deal_id>")
def deal_detail(deal_id: str):
    da = get_deal_agent()
    deal = da.get_deal(deal_id)
    if not deal:
        return "Deal not found", 404
    return render_template("deal_detail.html", deal=deal, fmt_eur=_fmt_eur)


@app.route("/deals/<deal_id>/advance", methods=["POST"])
def deal_advance(deal_id: str):
    da = get_deal_agent()
    new_stage = request.form.get("stage")
    if new_stage:
        da.advance_stage(deal_id, DealStage(new_stage))
    return redirect(url_for("deal_detail", deal_id=deal_id))


@app.route("/deals/<deal_id>/delete", methods=["POST"])
def deal_delete(deal_id: str):
    da = get_deal_agent()
    da.remove_deal(deal_id)
    return redirect(url_for("deals_list"))


@app.route("/deals/add", methods=["GET", "POST"])
def deal_add():
    if request.method == "POST":
        da = get_deal_agent()
        form = request.form
        deal = Deal(
            company_name=form["company_name"],
            sector=form.get("sector", "Industrials"),
            region=form.get("region", "Deutschland"),
            city=form.get("city", ""),
            revenue_eur=float(form["revenue_eur"]) if form.get("revenue_eur") else None,
            ebitda_eur=float(form["ebitda_eur"]) if form.get("ebitda_eur") else None,
            ebitda_margin=float(form["ebitda_margin"]) if form.get("ebitda_margin") else None,
            employee_count=int(form["employee_count"]) if form.get("employee_count") else None,
            is_succession="is_succession" in form,
            is_carve_out="is_carve_out" in form,
            source=form.get("source", "manual"),
            description=form.get("description", ""),
            contact_name=form.get("contact_name"),
            contact_email=form.get("contact_email"),
            contact_phone=form.get("contact_phone"),
        )
        da.add_deal(deal)
        da.score()
        return redirect(url_for("deal_detail", deal_id=deal.id))

    return render_template(
        "deal_form.html",
        sectors=config.DEAL_TARGET_SECTORS,
        regions=config.DEAL_TARGET_REGIONS,
    )


@app.route("/deals/<deal_id>/match")
def deal_match_investors(deal_id: str):
    da = get_deal_agent()
    fa = get_fund_agent()
    deal = da.get_deal(deal_id)
    if not deal:
        return "Deal not found", 404
    equity = (deal.revenue_eur or 30e6) * 0.4
    outreach = fa.outreach_list(deal, equity_required_eur=equity, top_n=20)
    return render_template(
        "deal_match.html",
        deal=deal,
        outreach=outreach,
        equity=equity,
        fmt_eur=_fmt_eur,
    )


# -- Investors ------------------------------------------------------------

@app.route("/investors")
def investors_list():
    fa = get_fund_agent()
    inv_type = request.args.get("type")
    country = request.args.get("country")
    status = request.args.get("status")
    q = request.args.get("q", "").strip()

    if q:
        investors = fa.search_investors(q)
    elif inv_type:
        investors = fa.investors_by_type(InvestorType(inv_type))
    elif country:
        investors = fa.investors_by_country(country)
    elif status:
        investors = fa.investors_by_status(InvestorStatus(status))
    else:
        investors = fa.database

    types = [t.value for t in InvestorType]
    statuses = [s.value for s in InvestorStatus]
    countries = sorted({i.country for i in fa.database})

    return render_template(
        "investors.html",
        investors=investors,
        types=types,
        statuses=statuses,
        countries=countries,
        current_type=inv_type,
        current_country=country,
        current_status=status,
        query=q,
        fmt_eur=_fmt_eur,
    )


@app.route("/investors/<investor_id>")
def investor_detail(investor_id: str):
    fa = get_fund_agent()
    inv = fa.get_investor(investor_id)
    if not inv:
        return "Investor not found", 404
    return render_template("investor_detail.html", inv=inv, fmt_eur=_fmt_eur)


@app.route("/investors/<investor_id>/status", methods=["POST"])
def investor_update_status(investor_id: str):
    fa = get_fund_agent()
    new_status = request.form.get("status")
    if new_status:
        fa.update_status(investor_id, InvestorStatus(new_status))
    return redirect(url_for("investor_detail", investor_id=investor_id))


@app.route("/investors/<investor_id>/interaction", methods=["POST"])
def investor_log_interaction(investor_id: str):
    fa = get_fund_agent()
    note = request.form.get("note", "")
    if note:
        fa.log_interaction(investor_id, note)
    return redirect(url_for("investor_detail", investor_id=investor_id))


@app.route("/investors/<investor_id>/delete", methods=["POST"])
def investor_delete(investor_id: str):
    fa = get_fund_agent()
    fa.remove_investor(investor_id)
    return redirect(url_for("investors_list"))


@app.route("/investors/add", methods=["GET", "POST"])
def investor_add():
    if request.method == "POST":
        fa = get_fund_agent()
        form = request.form
        inv = Investor(
            name=form["name"],
            investor_type=InvestorType(form.get("investor_type", "pe_fund")),
            country=form.get("country", "DE"),
            city=form.get("city", ""),
            website=form.get("website") or None,
            min_ticket_eur=float(form["min_ticket_eur"]) if form.get("min_ticket_eur") else None,
            max_ticket_eur=float(form["max_ticket_eur"]) if form.get("max_ticket_eur") else None,
            typical_ticket_eur=float(form["typical_ticket_eur"]) if form.get("typical_ticket_eur") else None,
            sector_preferences=[s.strip() for s in form.get("sector_preferences", "").split(",") if s.strip()],
            co_invest_appetite="co_invest_appetite" in form,
            independent_sponsor_friendly="independent_sponsor_friendly" in form,
            contact_name=form.get("contact_name") or None,
            contact_email=form.get("contact_email") or None,
            contact_phone=form.get("contact_phone") or None,
            notes=form.get("notes", ""),
        )
        fa.add_investor(inv)
        fa.score()
        return redirect(url_for("investor_detail", investor_id=inv.id))

    return render_template(
        "investor_form.html",
        types=[t.value for t in InvestorType],
        sectors=config.DEAL_TARGET_SECTORS,
    )


# -- Sourcing actions -----------------------------------------------------

@app.route("/source/deals", methods=["POST"])
def source_deals():
    """Trigger a full deal-sourcing cycle across all APIs."""
    da = get_deal_agent()
    summary = da.run_cycle()
    return redirect(url_for("deals_list"))


@app.route("/source/investors", methods=["POST"])
def source_investors():
    """Trigger a full investor-sourcing cycle across all APIs."""
    fa = get_fund_agent()
    summary = fa.run_cycle()
    return redirect(url_for("investors_list"))


# -- Settings -------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        # Update API keys in environment (runtime only)
        for key in ("OPENCORPORATES_TOKEN", "NORTH_DATA_API_KEY", "NEWSAPI_KEY", "GNEWS_KEY"):
            val = request.form.get(key, "").strip()
            if val:
                os.environ[key] = val
                setattr(config, key, val)

        # Force re-init of agents with new keys
        global _deal_agent, _fund_agent
        _deal_agent = None
        _fund_agent = None
        return redirect(url_for("settings"))

    api_keys = {
        "OPENCORPORATES_TOKEN": config.OPENCORPORATES_TOKEN,
        "NORTH_DATA_API_KEY": config.NORTH_DATA_API_KEY,
        "NEWSAPI_KEY": config.NEWSAPI_KEY,
        "GNEWS_KEY": config.GNEWS_KEY,
    }
    return render_template("settings.html", api_keys=api_keys)


# ===================================================================
# REST API
# ===================================================================

@app.route("/api/deals")
def api_deals():
    da = get_deal_agent()
    return jsonify([d.to_dict() for d in da.pipeline])


@app.route("/api/deals/<deal_id>")
def api_deal(deal_id: str):
    da = get_deal_agent()
    deal = da.get_deal(deal_id)
    if not deal:
        return jsonify({"error": "not found"}), 404
    return jsonify(deal.to_dict())


@app.route("/api/deals/report")
def api_deal_report():
    return jsonify(get_deal_agent().report())


@app.route("/api/deals/source", methods=["POST"])
def api_source_deals():
    da = get_deal_agent()
    summary = da.run_cycle()
    return jsonify(summary)


@app.route("/api/investors")
def api_investors():
    fa = get_fund_agent()
    return jsonify([i.to_dict() for i in fa.database])


@app.route("/api/investors/<investor_id>")
def api_investor(investor_id: str):
    fa = get_fund_agent()
    inv = fa.get_investor(investor_id)
    if not inv:
        return jsonify({"error": "not found"}), 404
    return jsonify(inv.to_dict())


@app.route("/api/investors/report")
def api_investor_report():
    return jsonify(get_fund_agent().report())


@app.route("/api/investors/source", methods=["POST"])
def api_source_investors():
    fa = get_fund_agent()
    summary = fa.run_cycle()
    return jsonify(summary)


@app.route("/api/deals/<deal_id>/match")
def api_match(deal_id: str):
    da = get_deal_agent()
    fa = get_fund_agent()
    deal = da.get_deal(deal_id)
    if not deal:
        return jsonify({"error": "not found"}), 404
    equity = (deal.revenue_eur or 30e6) * 0.4
    outreach = fa.outreach_list(deal, equity_required_eur=equity, top_n=20)
    return jsonify({"deal": deal.to_dict(), "equity_required": equity, "outreach": outreach})


# ===================================================================
# Main
# ===================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n  PE Sourcing Agents — Web App")
    print(f"  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
