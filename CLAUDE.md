# CLAUDE.md

This file provides guidance to AI assistants (including Claude) working in this repository.

## Repository Overview

- **Repository:** folahnstein-source/Test
- **Language:** Python 3.10+
- **Domain:** Private equity deal sourcing and fundraising in the DACH region
- **Dependencies:** Python standard library only (no external packages required)

The project contains two AI agents designed for independent sponsors and small PE firms:

1. **Deal Sourcing Agent** — identifies, qualifies, scores, and tracks acquisition targets in the German Mittelstand (SME) sector
2. **Fundraising Agent** — builds and maintains a database of co-investment partners (family offices, PE funds, institutional investors, HNWIs) across Germany, Austria, and Switzerland

## Project Structure

```
.
├── CLAUDE.md              # This file
├── config.py              # Central configuration (paths, defaults, logging)
├── main.py                # Entry point — runs demo with sample data
├── requirements.txt       # Python dependencies (stdlib-only today)
├── .gitignore
├── agents/
│   ├── __init__.py
│   ├── base.py            # BaseAgent ABC — persistence, CRUD, run-loop
│   ├── deal_sourcing.py   # DealSourcingAgent
│   └── fundraising.py     # FundraisingAgent
├── models/
│   ├── __init__.py
│   ├── deal.py            # Deal, DealStage, DealCriteria dataclasses
│   └── investor.py        # Investor, InvestorType, InvestorStatus dataclasses
└── data/                  # Runtime JSON persistence (git-ignored)
```

## How to Run

```bash
python3 main.py
```

This runs both agents with built-in sample data and prints pipeline summaries, top-ranked deals, investor scores, and a deal-specific outreach list.

## Architecture

### Models (`models/`)

- **Deal** — represents a potential acquisition target with financial metrics, sector, region, succession/carve-out flags, pipeline stage, and a composite score
- **DealCriteria** — configurable filters (revenue range, EBITDA, sectors, regions, employee count)
- **Investor** — represents a co-investment partner with ticket size, sector preferences, relationship status, and a relationship score
- Enums: `DealStage`, `InvestorType`, `InvestorStatus`
- All models use `@dataclass` with `to_dict()` / `from_dict()` for JSON serialization
- Models accept both enum instances and raw strings (coerced in `__post_init__`)

### Agents (`agents/`)

- **BaseAgent** — abstract base providing JSON file persistence, CRUD helpers, and a `run_cycle()` skeleton (source → score → report)
- **DealSourcingAgent** — manages the deal pipeline:
  - `source()` / `ingest_deals()` — ingest from external feeds or raw dicts
  - `score()` — weighted multi-factor scoring (financial fit, sector, succession premium, margin quality, size sweet-spot, region)
  - `top_deals()`, `deals_by_stage()`, `search_deals()` — querying
  - `advance_stage()` — move deals through the funnel
  - `report()` — pipeline summary by stage, sector, region
- **FundraisingAgent** — manages the investor database:
  - `source()` / `ingest_investors()` — ingest investor records
  - `score()` — weighted scoring (co-invest friendliness, ticket fit, sector alignment, relationship warmth, track record, speed, geography)
  - `match_to_deal()` — rank investors by fit for a specific deal
  - `outreach_list()` — generate a prioritised contact list for a deal
  - `log_interaction()` — record relationship touchpoints
  - `report()` — database summary by status, type, country

### Data Persistence

- Agents persist to `data/deals.json` and `data/investors.json`
- The `data/` directory is git-ignored; JSON files are created at runtime
- Data is loaded on agent init and saved after every mutation

### Scoring

Both agents use weighted multi-factor scoring (0–100 scale). Weights are defined at module level (`_SCORE_WEIGHTS` / `_INVESTOR_WEIGHTS`) and can be tuned without changing logic.

## Key Conventions

- **Dataclasses** for all domain models — no Pydantic or attrs
- **Enums** (`str, enum.Enum`) for all finite-state fields
- **Type hints** throughout; `from __future__ import annotations` for forward refs
- **Logging** via stdlib `logging` — agents log at INFO for lifecycle events, DEBUG for filtering decisions
- **No external dependencies** — the project runs on a bare Python 3.10+ install
- **Deduplication** by name (case-insensitive) on insert
- Snake_case for variables/functions, PascalCase for classes

## Development Workflow

### Branching

- Feature branches should be created off the default branch
- Use descriptive branch names that reflect the work being done

### Commits

- Write clear, descriptive commit messages
- Keep commits focused on a single logical change

### Code Review

- All changes should go through pull requests before merging to the main branch

## Guidelines for AI Assistants

- Read existing files before proposing modifications
- Do not over-engineer — keep changes minimal and focused on the task at hand
- Do not add files, features, or abstractions beyond what is requested
- Follow the existing patterns: dataclasses for models, weighted scoring in agents, JSON persistence in `data/`
- Run `python3 main.py` to verify changes work end-to-end before committing
- When adding new data sources, implement them behind the `source()` method of the relevant agent
- When adding new scoring factors, add them to the `_SCORE_WEIGHTS` / `_INVESTOR_WEIGHTS` dicts and the corresponding `_score_*` method
- Ask clarifying questions when requirements are ambiguous

## Future Integration Points

The agents are designed with pluggable `source()` methods. Production integrations would connect to:

**Deal Sourcing:**
- Bundesanzeiger (financial filings)
- Handelsregister (German company registry)
- M&A platforms (CARL, DUB.de, Nachfolge.de)
- Industry news feeds and press releases

**Fundraising:**
- BaFin / FMA / FINMA registers
- Family-office directories (Listenchampion, Finleap)
- PE databases (Preqin, PitchBook)
- LinkedIn / XING for HNWI identification
- Conference attendee lists
