# CLAUDE.md

This file provides guidance to AI assistants (including Claude) working in this repository.

## Repository Overview

- **Repository:** folahnstein-source/Test
- **Language:** Python 3.10+
- **Domain:** Private equity deal sourcing and fundraising in the DACH region
- **Dependencies:** Python standard library only (no external packages required)

The project contains two AI agents designed for independent sponsors and small PE firms:

1. **Deal Sourcing Agent** — identifies, qualifies, scores, and tracks acquisition targets in the German Mittelstand (SME) sector by querying multiple public APIs, RSS feeds, and MCP servers
2. **Fundraising Agent** — builds and maintains a database of co-investment partners (family offices, PE funds, institutional investors, HNWIs) across Germany, Austria, and Switzerland using financial regulator databases, company registries, and MCP servers

## Project Structure

```
.
├── CLAUDE.md                    # This file
├── config.py                    # Central config (paths, defaults, API keys, logging)
├── main.py                      # Entry point — runs demo with sample data + live APIs
├── requirements.txt             # Python dependencies (stdlib-only today)
├── .env.example                 # Template for API key environment variables
├── mcp_servers.example.json     # Template for MCP server configuration
├── .gitignore
├── agents/
│   ├── __init__.py
│   ├── base.py                  # BaseAgent ABC — persistence, CRUD, run-loop
│   ├── deal_sourcing.py         # DealSourcingAgent (7 data sources + MCP)
│   └── fundraising.py           # FundraisingAgent (7 data sources + MCP)
├── integrations/
│   ├── __init__.py
│   ├── api_client.py            # Base HTTP client — retries, rate-limiting, caching
│   ├── opencorporates.py        # OpenCorporates API — company registry (DE/AT/CH)
│   ├── handelsregister.py       # German commercial register
│   ├── north_data.py            # North Data — company intelligence + succession signals
│   ├── news_api.py              # NewsAPI.org + GNews — M&A / investor signals
│   ├── rss_feeds.py             # RSS aggregator — financial press feeds
│   ├── dub.py                   # DUB.de + nexxt-change.org — business-for-sale
│   ├── bafin.py                 # BaFin — German financial regulator
│   ├── fma.py                   # FMA — Austrian financial regulator
│   ├── finma.py                 # FINMA — Swiss financial regulator
│   └── mcp/
│       ├── __init__.py
│       ├── client.py            # MCP client (JSON-RPC over stdio + SSE)
│       └── registry.py          # MCP server registry and tool routing
├── models/
│   ├── __init__.py
│   ├── deal.py                  # Deal, DealStage, DealCriteria dataclasses
│   └── investor.py              # Investor, InvestorType, InvestorStatus dataclasses
└── data/                        # Runtime JSON persistence (git-ignored)
```

## How to Run

```bash
# Basic run (sample data + free-tier APIs)
python3 main.py

# With API keys for full coverage
OPENCORPORATES_TOKEN=xxx NEWSAPI_KEY=xxx python3 main.py

# With MCP servers (copy and edit the template first)
cp mcp_servers.example.json mcp_servers.json
# Edit mcp_servers.json to enable servers, then:
python3 main.py
```

## Data Sources

### Deal Sourcing Agent

Each `source()` cycle queries these in order:

| # | Source | Type | Auth Required |
|---|--------|------|---------------|
| 1 | Manual / direct ingest | Raw dicts | No |
| 2 | OpenCorporates | REST API | Optional token |
| 3 | Handelsregister | Web scrape | No |
| 4 | North Data | REST API | API key |
| 5 | DUB.de + nexxt-change.org | Web scrape | No |
| 6 | NewsAPI / GNews | REST API | API key |
| 7 | RSS feeds (7 financial press) | RSS/Atom | No |
| 8 | MCP servers (any with deal tools) | JSON-RPC | Varies |

### Fundraising Agent

Each `source()` cycle queries these in order:

| # | Source | Type | Auth Required |
|---|--------|------|---------------|
| 1 | Manual / direct ingest | Raw dicts | No |
| 2 | BaFin (German regulator) | Web scrape | No |
| 3 | FMA (Austrian regulator) | Web scrape | No |
| 4 | FINMA (Swiss regulator) | Web scrape | No |
| 5 | OpenCorporates (DE/AT/CH) | REST API | Optional token |
| 6 | NewsAPI / GNews | REST API | API key |
| 7 | RSS feeds (investor press) | RSS/Atom | No |
| 8 | MCP servers (any with investor tools) | JSON-RPC | Varies |

## Architecture

### Models (`models/`)

- **Deal** — acquisition target with financials, sector, region, succession/carve-out flags, pipeline stage, composite score
- **DealCriteria** — configurable filters (revenue, EBITDA, sectors, regions, employees)
- **Investor** — co-investment partner with ticket size, sector preferences, relationship status, score
- Enums: `DealStage`, `InvestorType`, `InvestorStatus`
- All models: `@dataclass` with `to_dict()` / `from_dict()`, `__post_init__` for string-to-enum coercion

### Integrations (`integrations/`)

- **APIClient** — base HTTP client on `urllib` with exponential-backoff retries, per-host rate limiting, and on-disk response cache
- **OpenCorporates** — company search across jurisdictions, officer search, SME/investment-firm convenience methods
- **Handelsregister** — German commercial register with per-court search across federal states
- **NorthData** — company profiles, financial filings, event-based succession detection
- **NewsAPI** — keyword-based news scanning for M&A and investor signals (DE+EN)
- **RSSFeedAggregator** — 10 pre-configured financial press feeds with keyword filtering
- **DUB** — DUB.de and nexxt-change.org business-for-sale listing aggregation
- **BaFin/FMA/FINMA** — regulated-entity search across all three DACH financial regulators

### MCP Framework (`integrations/mcp/`)

- **MCPClient** — full MCP protocol client supporting stdio (subprocess) and SSE (HTTP) transports; handles initialize, tool discovery, tool calls, and shutdown
- **MCPRegistry** — manages multiple MCP servers; loads config from `mcp_servers.json`; auto-routes tool calls to the correct server; supports broadcast calls across all servers

### Agents (`agents/`)

- **DealSourcingAgent** — orchestrates all deal-sourcing APIs and MCP servers in a single `source()` cycle; normalises external data into `Deal` objects via sector/region inference helpers
- **FundraisingAgent** — orchestrates all investor-sourcing APIs and MCP servers; normalises external data into `Investor` objects via investor-type inference helpers; provides `match_to_deal()` and `outreach_list()` for deal-specific investor ranking

### Data Persistence

- Agents persist to `data/deals.json` and `data/investors.json`
- API responses cached in `data/.api_cache/` with configurable TTL
- The `data/` directory is git-ignored; files created at runtime

### Scoring

Both agents use weighted multi-factor scoring (0–100 scale). Weights are defined at module level (`_SCORE_WEIGHTS` / `_INVESTOR_WEIGHTS`) and can be tuned without changing logic.

## Configuration

### Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `OPENCORPORATES_TOKEN` | Both agents | OpenCorporates API token (free tier works without) |
| `NORTH_DATA_API_KEY` | Deal sourcing | North Data API key (paid) |
| `NEWSAPI_KEY` | Both agents | NewsAPI.org key (free: 100 req/day) |
| `GNEWS_KEY` | Both agents | GNews API key (free: 100 req/day) |
| `LOG_LEVEL` | All | DEBUG, INFO, WARNING (default: INFO) |

### MCP Servers

Copy `mcp_servers.example.json` to `mcp_servers.json` and enable servers. Each server entry specifies:
- `transport`: `"stdio"` (subprocess) or `"sse"` (HTTP)
- `command` / `url`: how to connect
- `tags`: `["deals"]`, `["investors"]`, or `["both"]`
- `enabled`: `true` / `false`

## Key Conventions

- **Dataclasses** for all domain models — no Pydantic or attrs
- **Enums** (`str, enum.Enum`) for all finite-state fields
- **Type hints** throughout; `from __future__ import annotations` for forward refs
- **Logging** via stdlib `logging` — INFO for lifecycle, WARNING for API failures, DEBUG for filtering
- **No external dependencies** — runs on bare Python 3.10+ (urllib for HTTP, xml.etree for RSS, subprocess for MCP stdio)
- **Graceful degradation** — every API call uses `get_safe()` / try-except; agents continue if any source fails
- **Deduplication** by name (case-insensitive) on insert
- **Caching** — API responses cached on disk to avoid redundant calls
- snake_case for variables/functions, PascalCase for classes

## Development Workflow

### Branching

- Feature branches off the default branch
- Descriptive branch names

### Commits

- Clear, descriptive messages
- One logical change per commit

### Code Review

- All changes through pull requests

## Guidelines for AI Assistants

- Read existing files before proposing modifications
- Do not over-engineer — keep changes minimal and focused
- Follow existing patterns: dataclasses for models, weighted scoring in agents, JSON persistence in `data/`, `get_safe()` for API calls
- Run `python3 main.py` to verify changes end-to-end before committing
- New data sources: add an integration client in `integrations/`, then add a `_source_*()` method in the relevant agent
- New scoring factors: add to `_SCORE_WEIGHTS` / `_INVESTOR_WEIGHTS` dicts and the `_score_*` method
- New MCP integrations: add server config to `mcp_servers.example.json`
- All API clients must use `get_safe()` so failures never crash the agent
