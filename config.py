"""Central configuration for the sourcing agents."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

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
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(name)-28s | %(levelname)-7s | %(message)s"
