# Daily PE Portfolio Agent (Local MVP)

This module gives you a usable daily portfolio agent for PE monitoring on top of a local SQLite database.

## What it does now
- Portfolio/fund dashboard (actual vs budget, leverage, interest cover)
- Company risk ranking with deterministic risk score
- Covenant checks using formula expressions (`formula_expr`)
- KPI taxonomy and operational KPI watchlist
- Variance explanations by company/period
- Draft memo generation (`ic`, `lender`, `board`)
- Daily brief generation to markdown reports
- Slack/Teams webhook notifications from daily brief
- CSV imports for companies, financials, covenants, KPI taxonomy, and KPI values
- Rule-based `ask` command for natural language shortcuts

## File paths
- Agent CLI: `/Users/flvorsprung/Documents/New project 3/pe_agent/agent.py`
- Daily runner: `/Users/flvorsprung/Documents/New project 3/pe_agent/run_daily.sh`
- Database: `/Users/flvorsprung/Documents/New project 3/pe_agent/data/portfolio.db`
- Reports: `/Users/flvorsprung/Documents/New project 3/pe_agent/reports`
- CSV templates: `/Users/flvorsprung/Documents/New project 3/pe_agent/sample_data`

## Quick start

```bash
python3 pe_agent/agent.py init
python3 pe_agent/agent.py seed-demo
python3 pe_agent/agent.py dashboard
python3 pe_agent/agent.py risk-rank
python3 pe_agent/agent.py daily-brief
```

## Daily usage (recommended)

1. Import latest close data:
```bash
python3 pe_agent/agent.py import-financials --csv pe_agent/sample_data/financials.csv
python3 pe_agent/agent.py import-kpi-taxonomy --csv pe_agent/sample_data/kpi-taxonomy-template.csv
python3 pe_agent/agent.py import-kpis --csv pe_agent/sample_data/kpis-template.csv
python3 pe_agent/agent.py import-covenants --csv pe_agent/sample_data/covenants-template.csv
```

Dictionary options you can load:
```bash
python3 pe_agent/agent.py import-kpi-taxonomy --csv pe_agent/sample_data/kpi-dictionary-core-sme.csv
python3 pe_agent/agent.py import-kpi-taxonomy --csv pe_agent/sample_data/kpi-dictionary-industrials.csv
python3 pe_agent/agent.py import-kpi-taxonomy --csv pe_agent/sample_data/kpi-dictionary-software.csv
python3 pe_agent/agent.py import-kpi-taxonomy --csv pe_agent/sample_data/kpi-dictionary-people.csv
```
Reference guide: `/Users/flvorsprung/Documents/New project 3/pe_agent/references/kpi-dictionary-options.md`

2. Refresh and review risk:
```bash
python3 pe_agent/agent.py refresh-alerts
python3 pe_agent/agent.py risk-rank
```

3. Generate morning brief:
```bash
python3 pe_agent/agent.py daily-brief
```

4. Optional Slack/Teams notifications:
```bash
export PE_AGENT_SLACK_WEBHOOK="https://hooks.slack.com/services/..."
export PE_AGENT_TEAMS_WEBHOOK="https://.../webhook/..."
./pe_agent/run_daily.sh
```

5. Ask ad-hoc questions:
```bash
python3 pe_agent/agent.py ask --q "Rank portfolio risk"
python3 pe_agent/agent.py ask --q "Explain EBITDA miss for Rhein Software Solutions GmbH"
python3 pe_agent/agent.py ask --q "Show KPI watchlist"
python3 pe_agent/agent.py ask --q "Draft lender memo for Alpen Components GmbH"
```

## CSV formats

### Companies CSV
- `name,country,sector,ownership_pct`

### Financials CSV
- `company,period_end,revenue_actual,revenue_budget,ebitda_actual,ebitda_budget,cash_balance,net_debt,interest_expense,capex,dso,dpo,dio`
- `period_end` format: `YYYY-MM-DD`

### Covenants CSV
- `company,covenant_name,metric,formula_expr,threshold,direction,warning_buffer`
- `direction` must be `<=` or `>=`
- `formula_expr` supports arithmetic with variables from financials and KPIs, e.g.:
  - `net_debt / ebitda_ltm`
  - `ebitda_actual / interest_expense`
  - `gross_churn_pct`

### KPI taxonomy CSV
- `kpi_name,category,description,aggregation,default_unit`

### KPI values CSV
- `company,period_end,kpi_name,kpi_actual,kpi_budget,unit`

## Formula variable reference
Built-in variables available in covenant formulas:
- `revenue_actual`, `revenue_budget`
- `ebitda_actual`, `ebitda_budget`, `ebitda_ltm`
- `cash_balance`, `net_debt`, `interest_expense`, `capex`
- `dso`, `dpo`, `dio`
- `leverage`, `interest_cover`
- Any KPI in `operational_kpis`, normalized to lowercase with non-alphanumeric chars replaced by `_`

## Notes
- This is local and internal-only by design.
- Numeric outputs are generated from structured data and deterministic formulas.
- Validate all generated commentary before external distribution.
