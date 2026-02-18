"""Central configuration for the sourcing agents.

API keys can be set via environment variables or directly in this file.
Environment variables take precedence.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
MCP_CONFIG_PATH = PROJECT_ROOT / "mcp_servers.json"

# ---------------------------------------------------------------------------
# Deal Sourcing Agent – defaults
# ---------------------------------------------------------------------------
DEAL_MIN_REVENUE_EUR = 5_000_000
DEAL_MAX_REVENUE_EUR = 250_000_000
DEAL_TARGET_SECTORS = [
    "Industrials",
    "Healthcare",
    "Technology",
    "Business Services",
    "Consumer Goods",
    "Automotive Suppliers",
]
DEAL_TARGET_REGIONS = [
    "Baden-Württemberg",
    "Bayern",
    "Nordrhein-Westfalen",
    "Hessen",
    "Niedersachsen",
    "Hamburg",
    "Sachsen",
    "Rheinland-Pfalz",
    "Thüringen",
    "Berlin",
]

# ---------------------------------------------------------------------------
# Fundraising Agent – defaults
# ---------------------------------------------------------------------------
FUNDRAISING_TARGET_COUNTRIES = ["DE", "AT", "CH"]
FUNDRAISING_MIN_TICKET_EUR = 500_000
FUNDRAISING_MAX_TICKET_EUR = 50_000_000

# ---------------------------------------------------------------------------
# API Keys (set via env vars or override here)
# ---------------------------------------------------------------------------
OPENCORPORATES_TOKEN = os.environ.get("OPENCORPORATES_TOKEN", "")
NORTH_DATA_API_KEY = os.environ.get("NORTH_DATA_API_KEY", "")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
GNEWS_KEY = os.environ.get("GNEWS_KEY", "")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(name)-28s | %(levelname)-7s | %(message)s"
