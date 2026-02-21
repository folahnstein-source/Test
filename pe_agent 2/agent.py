#!/usr/bin/env python3
"""Daily PE portfolio agent CLI.

Local-only SQLite tool for portfolio monitoring, risk ranking, and report drafting.
No external dependencies required.
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib import request

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "portfolio.db"
REPORTS_DIR = ROOT / "reports"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
  company_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  country TEXT NOT NULL,
  sector TEXT NOT NULL,
  ownership_pct REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financials (
  financial_id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  period_end TEXT NOT NULL,
  revenue_actual REAL NOT NULL,
  revenue_budget REAL NOT NULL,
  ebitda_actual REAL NOT NULL,
  ebitda_budget REAL NOT NULL,
  cash_balance REAL NOT NULL,
  net_debt REAL NOT NULL,
  interest_expense REAL NOT NULL,
  capex REAL NOT NULL,
  dso REAL,
  dpo REAL,
  dio REAL,
  notes TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(company_id, period_end),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);

CREATE TABLE IF NOT EXISTS covenants (
  covenant_id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  covenant_name TEXT NOT NULL,
  metric TEXT NOT NULL,
  formula_expr TEXT,
  threshold REAL NOT NULL,
  direction TEXT NOT NULL CHECK(direction in ('<=', '>=')),
  warning_buffer REAL NOT NULL DEFAULT 0.10,
  UNIQUE(company_id, covenant_name),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);

CREATE TABLE IF NOT EXISTS kpi_taxonomy (
  taxonomy_id INTEGER PRIMARY KEY AUTOINCREMENT,
  kpi_name TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  description TEXT,
  aggregation TEXT NOT NULL DEFAULT 'avg',
  default_unit TEXT
);

CREATE TABLE IF NOT EXISTS operational_kpis (
  operational_kpi_id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  period_end TEXT NOT NULL,
  kpi_name TEXT NOT NULL,
  kpi_actual REAL NOT NULL,
  kpi_budget REAL,
  unit TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(company_id, period_end, kpi_name),
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);

CREATE TABLE IF NOT EXISTS initiatives (
  initiative_id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  owner TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status in ('not_started', 'in_progress', 'at_risk', 'completed')),
  target_value_eur REAL,
  due_date TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  period_end TEXT,
  severity TEXT NOT NULL CHECK(severity in ('green', 'amber', 'red')),
  alert_type TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(company_id) REFERENCES companies(company_id)
);
"""


@dataclass
class RiskRow:
  company: str
  risk_score: float
  ebitda_var_pct: float
  leverage: float
  interest_cover: float
  cash_runway_months: float
  active_red_alerts: int
  active_amber_alerts: int


def connect_db(db_path: Path) -> sqlite3.Connection:
  db_path.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(db_path)
  conn.row_factory = sqlite3.Row
  return conn


def init_db(conn: sqlite3.Connection) -> None:
  conn.executescript(SCHEMA_SQL)
  # Lightweight in-place migration for DBs created before formula_expr existed.
  cov_cols = {row["name"] for row in conn.execute("PRAGMA table_info(covenants)").fetchall()}
  if "formula_expr" not in cov_cols:
    conn.execute("ALTER TABLE covenants ADD COLUMN formula_expr TEXT")
  conn.commit()


def get_company_id(conn: sqlite3.Connection, company_name: str) -> int:
  row = conn.execute(
    "SELECT company_id FROM companies WHERE lower(name)=lower(?)",
    (company_name.strip(),),
  ).fetchone()
  if not row:
    raise ValueError(f"Unknown company: {company_name}")
  return int(row["company_id"])


def latest_period(conn: sqlite3.Connection, company_id: Optional[int] = None) -> Optional[str]:
  if company_id:
    row = conn.execute(
      "SELECT MAX(period_end) AS p FROM financials WHERE company_id=?",
      (company_id,),
    ).fetchone()
  else:
    row = conn.execute("SELECT MAX(period_end) AS p FROM financials").fetchone()
  return row["p"] if row and row["p"] else None


def seed_demo(conn: sqlite3.Connection) -> None:
  companies = [
    ("Alpen Components GmbH", "Germany", "Industrials", 78.0),
    ("Nordic Flow Systems AB", "Sweden", "B2B Services", 64.0),
    ("Rhein Software Solutions GmbH", "Germany", "Software", 81.0),
    ("Iberia MedTech SL", "Spain", "Healthcare Tech", 72.0),
  ]
  conn.executemany(
    """
    INSERT OR IGNORE INTO companies (name, country, sector, ownership_pct)
    VALUES (?, ?, ?, ?)
    """,
    companies,
  )

  periods = ["2025-09-30", "2025-10-31", "2025-11-30", "2025-12-31"]

  # (rev_actual, rev_budget, ebitda_actual, ebitda_budget, cash, net_debt, interest, capex, dso, dpo, dio)
  demo_fin = {
    "Alpen Components GmbH": [
      (17.2, 17.0, 2.6, 2.5, 5.2, 28.0, 0.45, 0.7, 54, 47, 63),
      (16.8, 17.4, 2.1, 2.6, 4.7, 28.8, 0.45, 0.8, 58, 46, 67),
      (18.0, 18.2, 2.4, 2.8, 4.4, 29.4, 0.46, 0.8, 60, 45, 69),
      (18.4, 19.1, 2.2, 3.0, 4.0, 30.1, 0.48, 0.9, 62, 44, 70),
    ],
    "Nordic Flow Systems AB": [
      (9.1, 9.0, 1.4, 1.4, 3.4, 12.3, 0.21, 0.3, 49, 39, 8),
      (9.5, 9.3, 1.6, 1.5, 3.8, 12.0, 0.21, 0.3, 48, 40, 8),
      (9.8, 9.6, 1.7, 1.6, 4.1, 11.8, 0.20, 0.4, 47, 40, 9),
      (10.0, 9.8, 1.8, 1.7, 4.3, 11.5, 0.20, 0.4, 47, 41, 9),
    ],
    "Rhein Software Solutions GmbH": [
      (6.2, 6.0, 1.1, 1.0, 2.2, 9.8, 0.17, 0.2, 38, 28, 1),
      (6.5, 6.4, 1.1, 1.1, 2.1, 10.2, 0.18, 0.2, 40, 27, 1),
      (6.4, 6.7, 0.8, 1.3, 1.6, 10.6, 0.19, 0.3, 43, 26, 1),
      (6.1, 6.9, 0.6, 1.4, 1.2, 11.2, 0.21, 0.3, 45, 25, 1),
    ],
    "Iberia MedTech SL": [
      (11.0, 10.8, 1.7, 1.6, 3.1, 16.4, 0.31, 0.6, 73, 44, 52),
      (11.3, 11.1, 1.8, 1.7, 3.4, 16.2, 0.31, 0.6, 72, 45, 51),
      (11.1, 11.5, 1.6, 1.8, 3.0, 16.6, 0.32, 0.6, 74, 45, 53),
      (10.7, 11.8, 1.2, 1.9, 2.5, 17.4, 0.33, 0.7, 77, 44, 55),
    ],
  }

  for company, rows in demo_fin.items():
    cid = get_company_id(conn, company)
    for period, values in zip(periods, rows):
      conn.execute(
        """
        INSERT OR REPLACE INTO financials (
          company_id, period_end, revenue_actual, revenue_budget,
          ebitda_actual, ebitda_budget, cash_balance, net_debt,
          interest_expense, capex, dso, dpo, dio, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'seed')
        """,
        (cid, period, *values),
      )

  demo_cov = [
    ("Alpen Components GmbH", "Net Debt / EBITDA", "leverage", "net_debt / ebitda_ltm", 4.00, "<=", 0.10),
    ("Alpen Components GmbH", "Interest Cover", "interest_cover", "ebitda_actual / interest_expense", 3.00, ">=", 0.10),
    ("Nordic Flow Systems AB", "Net Debt / EBITDA", "leverage", "net_debt / ebitda_ltm", 3.50, "<=", 0.10),
    ("Nordic Flow Systems AB", "Interest Cover", "interest_cover", "ebitda_actual / interest_expense", 3.20, ">=", 0.10),
    ("Rhein Software Solutions GmbH", "Net Debt / EBITDA", "leverage", "net_debt / ebitda_ltm", 4.20, "<=", 0.10),
    ("Rhein Software Solutions GmbH", "Interest Cover", "interest_cover", "ebitda_actual / interest_expense", 2.80, ">=", 0.10),
    ("Iberia MedTech SL", "Net Debt / EBITDA", "leverage", "net_debt / ebitda_ltm", 4.00, "<=", 0.10),
    ("Iberia MedTech SL", "Interest Cover", "interest_cover", "ebitda_actual / interest_expense", 3.00, ">=", 0.10),
  ]

  for company, cname, metric, formula_expr, threshold, direction, warning in demo_cov:
    cid = get_company_id(conn, company)
    conn.execute(
      """
      INSERT OR REPLACE INTO covenants
      (company_id, covenant_name, metric, formula_expr, threshold, direction, warning_buffer)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      """,
      (cid, cname, metric, formula_expr, threshold, direction, warning),
    )

  initiatives = [
    ("Alpen Components GmbH", "Plant scheduling optimization", "COO", "in_progress", 1_200_000, "2026-06-30"),
    ("Rhein Software Solutions GmbH", "Pricing uplift + packaging", "CRO", "at_risk", 900_000, "2026-04-30"),
    ("Iberia MedTech SL", "Receivables cleanup", "CFO", "in_progress", 750_000, "2026-03-31"),
    ("Nordic Flow Systems AB", "Shared services rollout", "CEO", "completed", 500_000, "2025-12-31"),
  ]

  conn.execute("DELETE FROM initiatives")
  for company, title, owner, status, target, due in initiatives:
    cid = get_company_id(conn, company)
    conn.execute(
      """
      INSERT INTO initiatives (company_id, title, owner, status, target_value_eur, due_date)
      VALUES (?, ?, ?, ?, ?, ?)
      """,
      (cid, title, owner, status, target, due),
    )

  taxonomy_rows = [
    ("pipeline_conversion_pct", "commercial", "Qualified to won conversion rate", "avg", "%"),
    ("gross_churn_pct", "commercial", "Gross churn in period", "avg", "%"),
    ("oee_pct", "operations", "Overall equipment effectiveness", "avg", "%"),
    ("on_time_delivery_pct", "operations", "On-time in full delivery", "avg", "%"),
    ("revenue_per_fte_k", "people", "Revenue per full-time equivalent (EURk)", "avg", "EURk"),
    ("sick_days_per_fte", "people", "Sick days per FTE", "avg", "days"),
  ]
  conn.executemany(
    """
    INSERT OR REPLACE INTO kpi_taxonomy (kpi_name, category, description, aggregation, default_unit)
    VALUES (?, ?, ?, ?, ?)
    """,
    taxonomy_rows,
  )

  period_kpis = {
    "Alpen Components GmbH": [
      ("2025-12-31", "oee_pct", 74.0, 79.0),
      ("2025-12-31", "on_time_delivery_pct", 86.0, 92.0),
      ("2025-12-31", "revenue_per_fte_k", 18.0, 19.0),
    ],
    "Nordic Flow Systems AB": [
      ("2025-12-31", "pipeline_conversion_pct", 28.0, 26.0),
      ("2025-12-31", "revenue_per_fte_k", 23.0, 22.0),
    ],
    "Rhein Software Solutions GmbH": [
      ("2025-12-31", "gross_churn_pct", 8.4, 6.0),
      ("2025-12-31", "pipeline_conversion_pct", 17.0, 24.0),
      ("2025-12-31", "revenue_per_fte_k", 15.0, 18.0),
    ],
    "Iberia MedTech SL": [
      ("2025-12-31", "on_time_delivery_pct", 82.0, 89.0),
      ("2025-12-31", "sick_days_per_fte", 2.7, 2.0),
      ("2025-12-31", "revenue_per_fte_k", 16.0, 18.0),
    ],
  }
  for company, rows in period_kpis.items():
    cid = get_company_id(conn, company)
    for period_end, kpi_name, actual, budget in rows:
      conn.execute(
        """
        INSERT OR REPLACE INTO operational_kpis
        (company_id, period_end, kpi_name, kpi_actual, kpi_budget, unit, source)
        VALUES (?, ?, ?, ?, ?, (SELECT default_unit FROM kpi_taxonomy WHERE kpi_name=?), 'seed')
        """,
        (cid, period_end, kpi_name, actual, budget, kpi_name),
      )

  conn.commit()


def parse_csv_float(value: str) -> Optional[float]:
  if value is None:
    return None
  text = str(value).strip()
  if not text:
    return None
  return float(text)


def import_companies_csv(conn: sqlite3.Connection, path: Path) -> int:
  with path.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    required = {"name", "country", "sector", "ownership_pct"}
    missing = required - set(reader.fieldnames or [])
    if missing:
      raise ValueError(f"Missing columns in companies CSV: {sorted(missing)}")

    count = 0
    for row in reader:
      conn.execute(
        """
        INSERT INTO companies (name, country, sector, ownership_pct)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
          country=excluded.country,
          sector=excluded.sector,
          ownership_pct=excluded.ownership_pct
        """,
        (
          row["name"].strip(),
          row["country"].strip(),
          row["sector"].strip(),
          float(row["ownership_pct"]),
        ),
      )
      count += 1
  conn.commit()
  return count


def import_financials_csv(conn: sqlite3.Connection, path: Path) -> int:
  with path.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    required = {
      "company",
      "period_end",
      "revenue_actual",
      "revenue_budget",
      "ebitda_actual",
      "ebitda_budget",
      "cash_balance",
      "net_debt",
      "interest_expense",
      "capex",
      "dso",
      "dpo",
      "dio",
    }
    missing = required - set(reader.fieldnames or [])
    if missing:
      raise ValueError(f"Missing columns in financials CSV: {sorted(missing)}")

    count = 0
    for row in reader:
      cid = get_company_id(conn, row["company"])
      dt.date.fromisoformat(row["period_end"])
      conn.execute(
        """
        INSERT INTO financials (
          company_id, period_end, revenue_actual, revenue_budget,
          ebitda_actual, ebitda_budget, cash_balance, net_debt,
          interest_expense, capex, dso, dpo, dio, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'csv')
        ON CONFLICT(company_id, period_end) DO UPDATE SET
          revenue_actual=excluded.revenue_actual,
          revenue_budget=excluded.revenue_budget,
          ebitda_actual=excluded.ebitda_actual,
          ebitda_budget=excluded.ebitda_budget,
          cash_balance=excluded.cash_balance,
          net_debt=excluded.net_debt,
          interest_expense=excluded.interest_expense,
          capex=excluded.capex,
          dso=excluded.dso,
          dpo=excluded.dpo,
          dio=excluded.dio,
          source='csv'
        """,
        (
          cid,
          row["period_end"],
          float(row["revenue_actual"]),
          float(row["revenue_budget"]),
          float(row["ebitda_actual"]),
          float(row["ebitda_budget"]),
          float(row["cash_balance"]),
          float(row["net_debt"]),
          float(row["interest_expense"]),
          float(row["capex"]),
          parse_csv_float(row["dso"]),
          parse_csv_float(row["dpo"]),
          parse_csv_float(row["dio"]),
        ),
      )
      count += 1
  conn.commit()
  return count


def import_covenants_csv(conn: sqlite3.Connection, path: Path) -> int:
  with path.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    required = {"company", "covenant_name", "metric", "formula_expr", "threshold", "direction", "warning_buffer"}
    missing = required - set(reader.fieldnames or [])
    if missing:
      raise ValueError(f"Missing columns in covenants CSV: {sorted(missing)}")

    count = 0
    for row in reader:
      cid = get_company_id(conn, row["company"])
      direction = row["direction"].strip()
      if direction not in ("<=", ">="):
        raise ValueError(f"Invalid direction {direction} for covenant {row['covenant_name']}")
      conn.execute(
        """
        INSERT INTO covenants
        (company_id, covenant_name, metric, formula_expr, threshold, direction, warning_buffer)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_id, covenant_name) DO UPDATE SET
          metric=excluded.metric,
          formula_expr=excluded.formula_expr,
          threshold=excluded.threshold,
          direction=excluded.direction,
          warning_buffer=excluded.warning_buffer
        """,
        (
          cid,
          row["covenant_name"].strip(),
          row["metric"].strip(),
          row["formula_expr"].strip(),
          float(row["threshold"]),
          direction,
          float(row["warning_buffer"]),
        ),
      )
      count += 1
  conn.commit()
  return count


def import_kpi_taxonomy_csv(conn: sqlite3.Connection, path: Path) -> int:
  with path.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    required = {"kpi_name", "category", "description", "aggregation", "default_unit"}
    missing = required - set(reader.fieldnames or [])
    if missing:
      raise ValueError(f"Missing columns in KPI taxonomy CSV: {sorted(missing)}")

    count = 0
    for row in reader:
      conn.execute(
        """
        INSERT INTO kpi_taxonomy (kpi_name, category, description, aggregation, default_unit)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(kpi_name) DO UPDATE SET
          category=excluded.category,
          description=excluded.description,
          aggregation=excluded.aggregation,
          default_unit=excluded.default_unit
        """,
        (
          row["kpi_name"].strip(),
          row["category"].strip(),
          row["description"].strip(),
          row["aggregation"].strip() or "avg",
          row["default_unit"].strip(),
        ),
      )
      count += 1
  conn.commit()
  return count


def import_operational_kpis_csv(conn: sqlite3.Connection, path: Path) -> int:
  with path.open(newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    required = {"company", "period_end", "kpi_name", "kpi_actual", "kpi_budget", "unit"}
    missing = required - set(reader.fieldnames or [])
    if missing:
      raise ValueError(f"Missing columns in operational KPIs CSV: {sorted(missing)}")

    count = 0
    for row in reader:
      cid = get_company_id(conn, row["company"])
      dt.date.fromisoformat(row["period_end"])
      unit = row["unit"].strip()
      if not unit:
        taxonomy_unit = conn.execute(
          "SELECT default_unit FROM kpi_taxonomy WHERE kpi_name=?",
          (row["kpi_name"].strip(),),
        ).fetchone()
        unit = taxonomy_unit["default_unit"] if taxonomy_unit else ""
      conn.execute(
        """
        INSERT INTO operational_kpis
        (company_id, period_end, kpi_name, kpi_actual, kpi_budget, unit, source)
        VALUES (?, ?, ?, ?, ?, ?, 'csv')
        ON CONFLICT(company_id, period_end, kpi_name) DO UPDATE SET
          kpi_actual=excluded.kpi_actual,
          kpi_budget=excluded.kpi_budget,
          unit=excluded.unit,
          source='csv'
        """,
        (
          cid,
          row["period_end"],
          row["kpi_name"].strip(),
          float(row["kpi_actual"]),
          parse_csv_float(row["kpi_budget"]),
          unit,
        ),
      )
      count += 1
  conn.commit()
  return count


def _safe_div(n: float, d: float) -> float:
  if d == 0:
    return 0.0
  return n / d


def _get_ltm_ebitda(conn: sqlite3.Connection, company_id: int, period_end: str) -> float:
  rows = conn.execute(
    """
    SELECT ebitda_actual
    FROM financials
    WHERE company_id=? AND period_end <= ?
    ORDER BY period_end DESC
    LIMIT 4
    """,
    (company_id, period_end),
  ).fetchall()
  return float(sum(float(r["ebitda_actual"]) for r in rows))


def _get_company_kpi_map(conn: sqlite3.Connection, company_id: int, period_end: str) -> dict[str, float]:
  rows = conn.execute(
    """
    SELECT kpi_name, kpi_actual
    FROM operational_kpis
    WHERE company_id=? AND period_end=?
    """,
    (company_id, period_end),
  ).fetchall()
  return {re.sub(r"\\W+", "_", str(r["kpi_name"]).strip().lower()): float(r["kpi_actual"]) for r in rows}


def _safe_eval_formula(formula: str, variables: dict[str, float]) -> float:
  expr = ast.parse(formula, mode="eval")
  allowed = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Num,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Mod,
    ast.FloorDiv,
  )

  for node in ast.walk(expr):
    if not isinstance(node, allowed):
      raise ValueError(f"Unsupported formula token: {type(node).__name__}")
    if isinstance(node, ast.Name) and node.id not in variables:
      raise ValueError(f"Unknown variable in formula: {node.id}")

  return float(eval(compile(expr, "<formula>", "eval"), {"__builtins__": {}}, variables))


def compute_risk_rows(conn: sqlite3.Connection, period_end: Optional[str] = None) -> list[RiskRow]:
  if period_end is None:
    period_end = latest_period(conn)
  if period_end is None:
    return []

  rows = conn.execute(
    """
    SELECT
      c.company_id,
      c.name,
      f.ebitda_actual,
      f.ebitda_budget,
      f.cash_balance,
      f.net_debt,
      f.interest_expense,
      f.capex,
      f.dso,
      f.dpo,
      f.dio,
      f.revenue_actual,
      f.revenue_budget,
      f.period_end
    FROM companies c
    JOIN financials f ON f.company_id = c.company_id
    WHERE f.period_end = ?
    ORDER BY c.name
    """,
    (period_end,),
  ).fetchall()

  results: list[RiskRow] = []
  for row in rows:
    ebitda_actual = float(row["ebitda_actual"])
    ebitda_budget = float(row["ebitda_budget"])
    ebitda_var_pct = _safe_div(ebitda_actual - ebitda_budget, abs(ebitda_budget)) * 100.0

    annualized_ebitda = ebitda_actual * 12.0
    leverage = _safe_div(float(row["net_debt"]), annualized_ebitda)
    interest_cover = _safe_div(ebitda_actual, float(row["interest_expense"]))

    monthly_burn_proxy = max(0.15, float(row["interest_expense"]) + float(row["capex"]) - max(0.0, ebitda_actual))
    cash_runway = float(row["cash_balance"]) / monthly_burn_proxy

    red_alerts = 0
    amber_alerts = 0

    company_id = int(row["company_id"])
    covs = conn.execute(
      """
      SELECT covenant_name, metric, formula_expr, threshold, direction, warning_buffer
      FROM covenants
      WHERE company_id = ?
      """,
      (company_id,),
    ).fetchall()

    formula_vars = {
      "revenue_actual": float(row["revenue_actual"]),
      "revenue_budget": float(row["revenue_budget"]),
      "ebitda_actual": ebitda_actual,
      "ebitda_budget": ebitda_budget,
      "cash_balance": float(row["cash_balance"]),
      "net_debt": float(row["net_debt"]),
      "interest_expense": float(row["interest_expense"]),
      "capex": float(row["capex"]),
      "dso": float(row["dso"] or 0.0),
      "dpo": float(row["dpo"] or 0.0),
      "dio": float(row["dio"] or 0.0),
      "leverage": leverage,
      "interest_cover": interest_cover,
      "ebitda_ltm": _get_ltm_ebitda(conn, company_id, str(row["period_end"])),
    }
    formula_vars.update(_get_company_kpi_map(conn, company_id, str(row["period_end"])))

    for cov in covs:
      metric = cov["metric"]
      formula_expr = (cov["formula_expr"] or "").strip()
      threshold = float(cov["threshold"])
      direction = cov["direction"]
      warning = float(cov["warning_buffer"])

      if formula_expr:
        try:
          value = _safe_eval_formula(formula_expr, formula_vars)
        except Exception:
          continue
      elif metric == "leverage":
        value = leverage
      elif metric == "interest_cover":
        value = interest_cover
      else:
        continue

      if direction == "<=":
        if value > threshold:
          red_alerts += 1
        elif value > threshold * (1 - warning):
          amber_alerts += 1
      elif direction == ">=":
        if value < threshold:
          red_alerts += 1
        elif value < threshold * (1 + warning):
          amber_alerts += 1

    variance_component = min(30.0, max(0.0, -ebitda_var_pct) * 1.2)
    leverage_component = min(25.0, max(0.0, leverage - 2.0) * 10.0)
    cover_component = min(20.0, max(0.0, 3.0 - interest_cover) * 8.0)
    runway_component = min(15.0, max(0.0, 6.0 - cash_runway) * 2.5)
    covenant_component = red_alerts * 15.0 + amber_alerts * 7.0

    risk_score = min(
      100.0,
      variance_component + leverage_component + cover_component + runway_component + covenant_component,
    )

    results.append(
      RiskRow(
        company=row["name"],
        risk_score=round(risk_score, 1),
        ebitda_var_pct=round(ebitda_var_pct, 1),
        leverage=round(leverage, 2),
        interest_cover=round(interest_cover, 2),
        cash_runway_months=round(cash_runway, 1),
        active_red_alerts=red_alerts,
        active_amber_alerts=amber_alerts,
      )
    )

  results.sort(key=lambda x: x.risk_score, reverse=True)
  return results


def upsert_alerts_from_risk(conn: sqlite3.Connection, period_end: Optional[str] = None) -> int:
  if period_end is None:
    period_end = latest_period(conn)
  if period_end is None:
    return 0

  risk_rows = compute_risk_rows(conn, period_end)
  count = 0
  for row in risk_rows:
    company_id = get_company_id(conn, row.company)
    conn.execute(
      "DELETE FROM alerts WHERE company_id=? AND period_end=? AND alert_type='risk_score'",
      (company_id, period_end),
    )

    if row.risk_score >= 70:
      severity = "red"
    elif row.risk_score >= 45:
      severity = "amber"
    else:
      severity = "green"

    message = (
      f"Risk score {row.risk_score} | EBITDA var {row.ebitda_var_pct}% | "
      f"Leverage {row.leverage}x | Cover {row.interest_cover}x"
    )
    conn.execute(
      """
      INSERT INTO alerts (company_id, period_end, severity, alert_type, message)
      VALUES (?, ?, ?, 'risk_score', ?)
      """,
      (company_id, period_end, severity, message),
    )
    count += 1

  conn.commit()
  return count


def render_risk_table(rows: Iterable[RiskRow]) -> str:
  headers = [
    "Company",
    "Risk",
    "EBITDA Var%",
    "Leverage",
    "Cover",
    "Runway(m)",
    "Red",
    "Amber",
  ]
  lines = [" | ".join(headers), " | ".join(["---"] * len(headers))]
  for r in rows:
    lines.append(
      " | ".join(
        [
          r.company,
          f"{r.risk_score:.1f}",
          f"{r.ebitda_var_pct:.1f}",
          f"{r.leverage:.2f}x",
          f"{r.interest_cover:.2f}x",
          f"{r.cash_runway_months:.1f}",
          str(r.active_red_alerts),
          str(r.active_amber_alerts),
        ]
      )
    )
  return "\n".join(lines)


def fund_dashboard(conn: sqlite3.Connection, period_end: Optional[str] = None) -> str:
  if period_end is None:
    period_end = latest_period(conn)
  if period_end is None:
    return "No data found. Run init + seed-demo or import CSV files first."

  agg = conn.execute(
    """
    SELECT
      COUNT(*) AS company_count,
      SUM(revenue_actual) AS rev_actual,
      SUM(revenue_budget) AS rev_budget,
      SUM(ebitda_actual) AS ebitda_actual,
      SUM(ebitda_budget) AS ebitda_budget,
      SUM(cash_balance) AS cash,
      SUM(net_debt) AS net_debt,
      SUM(interest_expense) AS interest
    FROM financials
    WHERE period_end = ?
    """,
    (period_end,),
  ).fetchone()

  rev_var = _safe_div(float(agg["rev_actual"] - agg["rev_budget"]), abs(float(agg["rev_budget"]))) * 100
  ebitda_var = _safe_div(float(agg["ebitda_actual"] - agg["ebitda_budget"]), abs(float(agg["ebitda_budget"]))) * 100
  leverage = _safe_div(float(agg["net_debt"]), float(agg["ebitda_actual"]) * 12.0)
  interest_cover = _safe_div(float(agg["ebitda_actual"]), float(agg["interest"]))

  risk_rows = compute_risk_rows(conn, period_end)
  top_risk = risk_rows[0].company if risk_rows else "n/a"

  return textwrap.dedent(
    f"""
    Fund Dashboard ({period_end})
    Companies reporting: {int(agg['company_count'])}
    Revenue: EUR {agg['rev_actual']:.2f}m vs budget {agg['rev_budget']:.2f}m ({rev_var:+.1f}%)
    EBITDA: EUR {agg['ebitda_actual']:.2f}m vs budget {agg['ebitda_budget']:.2f}m ({ebitda_var:+.1f}%)
    Cash: EUR {agg['cash']:.2f}m
    Net debt: EUR {agg['net_debt']:.2f}m
    Net leverage: {leverage:.2f}x
    Interest cover: {interest_cover:.2f}x
    Highest risk company: {top_risk}
    """
  ).strip()


def portfolio_kpi_watchlist(conn: sqlite3.Connection, period_end: Optional[str] = None, limit: int = 6) -> list[str]:
  if period_end is None:
    period_end = latest_period(conn)
  if period_end is None:
    return []

  rows = conn.execute(
    """
    SELECT
      c.name AS company,
      ok.kpi_name,
      kt.default_unit,
      ok.kpi_actual,
      ok.kpi_budget,
      kt.category
    FROM operational_kpis ok
    JOIN companies c ON c.company_id = ok.company_id
    LEFT JOIN kpi_taxonomy kt ON kt.kpi_name = ok.kpi_name
    WHERE ok.period_end = ?
    ORDER BY
      CASE
        WHEN ok.kpi_budget IS NULL OR ok.kpi_budget = 0 THEN 0
        ELSE ABS((ok.kpi_actual - ok.kpi_budget) / ok.kpi_budget)
      END DESC
    LIMIT ?
    """,
    (period_end, limit),
  ).fetchall()

  lines: list[str] = []
  for r in rows:
    budget = r["kpi_budget"]
    actual = float(r["kpi_actual"])
    raw_unit = r["default_unit"] or ""
    unit = f" {raw_unit}" if raw_unit else ""
    if budget is None or float(budget) == 0:
      var_txt = "n/a"
      budget_txt = "n/a"
    else:
      var = _safe_div(actual - float(budget), abs(float(budget))) * 100
      var_txt = f"{var:+.1f}%"
      budget_txt = f"{float(budget):.2f}{unit}"
    lines.append(
      f"- {r['company']}: {r['kpi_name']} actual {actual:.2f}{unit}, budget {budget_txt}, variance {var_txt} ({r['category'] or 'uncategorized'})"
    )
  return lines


def explain_variance(conn: sqlite3.Connection, company_name: str, period_end: Optional[str] = None) -> str:
  cid = get_company_id(conn, company_name)
  if period_end is None:
    period_end = latest_period(conn, cid)
  if period_end is None:
    return f"No financial data for {company_name}."

  row = conn.execute(
    """
    SELECT c.name, f.*
    FROM financials f
    JOIN companies c ON c.company_id = f.company_id
    WHERE f.company_id=? AND f.period_end=?
    """,
    (cid, period_end),
  ).fetchone()

  if not row:
    return f"No period data for {company_name} on {period_end}."

  ebitda_var_pct = _safe_div(float(row["ebitda_actual"] - row["ebitda_budget"]), abs(float(row["ebitda_budget"]))) * 100
  rev_var_pct = _safe_div(float(row["revenue_actual"] - row["revenue_budget"]), abs(float(row["revenue_budget"]))) * 100
  wc_cycle = float(row["dso"] or 0) + float(row["dio"] or 0) - float(row["dpo"] or 0)

  driver_lines = []
  if rev_var_pct < -2:
    driver_lines.append("Revenue below budget indicates a volume/mix shortfall.")
  elif rev_var_pct > 2:
    driver_lines.append("Revenue outperformance suggests strong top-line execution.")

  if ebitda_var_pct < -5:
    driver_lines.append("EBITDA miss is material; check pricing discipline, gross margin, and overhead drift.")
  elif ebitda_var_pct < 0:
    driver_lines.append("EBITDA is slightly below plan; likely manageable with targeted actions.")

  if wc_cycle > 80:
    driver_lines.append("Working-capital cycle is stretched, likely pressuring liquidity.")

  if float(row["interest_expense"]) > max(0.15, float(row["ebitda_actual"]) * 0.25):
    driver_lines.append("Debt service burden is high relative to EBITDA.")

  if not driver_lines:
    driver_lines.append("Variance is modest; no structural red flags from the core KPI set.")

  driver_block = "\n    - ".join(driver_lines)

  return textwrap.dedent(
    f"""
    Variance explanation for {row['name']} ({period_end})
    Revenue: EUR {row['revenue_actual']:.2f}m vs budget {row['revenue_budget']:.2f}m ({rev_var_pct:+.1f}%)
    EBITDA: EUR {row['ebitda_actual']:.2f}m vs budget {row['ebitda_budget']:.2f}m ({ebitda_var_pct:+.1f}%)
    Cash: EUR {row['cash_balance']:.2f}m | Net debt: EUR {row['net_debt']:.2f}m
    Working capital cycle proxy (DSO + DIO - DPO): {wc_cycle:.1f} days

    Likely drivers:
    - {driver_block}
    """
  ).strip()


def _memo_header(kind: str) -> str:
  if kind == "lender":
    return "Lender Update Draft"
  if kind == "board":
    return "Board Pack Commentary Draft"
  return "Investment Committee Memo Draft"


def draft_memo(conn: sqlite3.Connection, company_name: str, kind: str, period_end: Optional[str] = None) -> str:
  cid = get_company_id(conn, company_name)
  if period_end is None:
    period_end = latest_period(conn, cid)
  if period_end is None:
    return f"No data for {company_name}."

  summary = explain_variance(conn, company_name, period_end)
  risk_rows = compute_risk_rows(conn, period_end)
  risk_map = {r.company: r for r in risk_rows}
  risk = risk_map.get(company_name)

  init_rows = conn.execute(
    """
    SELECT title, owner, status, target_value_eur, due_date
    FROM initiatives
    WHERE company_id=?
    ORDER BY CASE status
      WHEN 'at_risk' THEN 1
      WHEN 'in_progress' THEN 2
      WHEN 'not_started' THEN 3
      WHEN 'completed' THEN 4
      ELSE 5 END,
      due_date
    """,
    (cid,),
  ).fetchall()

  init_lines = []
  for i in init_rows:
    init_lines.append(
      f"- {i['title']} ({i['status']}), owner: {i['owner']}, target EUR {float(i['target_value_eur'] or 0):,.0f}, due {i['due_date'] or 'n/a'}"
    )
  if not init_lines:
    init_lines = ["- No initiatives logged."]

  risk_text = "n/a"
  if risk:
    risk_text = (
      f"score {risk.risk_score:.1f}; leverage {risk.leverage:.2f}x; "
      f"interest cover {risk.interest_cover:.2f}x; red alerts {risk.active_red_alerts}"
    )

  initiatives_block = "\n".join(init_lines)

  return textwrap.dedent(
    f"""
    {_memo_header(kind)}
    Company: {company_name}
    Period: {period_end}

    Executive Summary
    - Current risk status: {risk_text}
    - Key message: Management attention should focus on EBITDA delivery and liquidity discipline.

    Performance Commentary
    {summary}

    Value-Creation Initiative Status
    {initiatives_block}

    Recommended Next Actions (next 30 days)
    - Confirm weekly cash bridge and covenant forecast rolling 13 weeks.
    - Lock top 3 EBITDA recovery actions with owner and dated milestones.
    - Re-forecast downside case and pre-wire lender communication if headroom tightens.

    Data integrity note
    - This draft is generated from local structured data and rule-based analysis; validate figures before external distribution.
    """
  ).strip()


def daily_brief(conn: sqlite3.Connection, as_of: Optional[str] = None, write_file: bool = True) -> str:
  period_end = as_of or latest_period(conn)
  if period_end is None:
    return "No data found."

  dashboard = fund_dashboard(conn, period_end)
  risks = compute_risk_rows(conn, period_end)
  top3 = risks[:3]

  initiatives = conn.execute(
    """
    SELECT c.name, i.title, i.status, i.owner, i.due_date
    FROM initiatives i
    JOIN companies c ON c.company_id = i.company_id
    WHERE i.status IN ('at_risk', 'in_progress')
    ORDER BY CASE i.status WHEN 'at_risk' THEN 1 ELSE 2 END, i.due_date
    LIMIT 10
    """
  ).fetchall()

  initiative_lines = [
    f"- {r['name']}: {r['title']} ({r['status']}, owner {r['owner']}, due {r['due_date'] or 'n/a'})"
    for r in initiatives
  ] or ["- No active or at-risk initiatives."]

  risk_lines = [
    f"- {r.company}: risk {r.risk_score:.1f}, EBITDA var {r.ebitda_var_pct:+.1f}%, leverage {r.leverage:.2f}x"
    for r in top3
  ] or ["- No risk rows available."]

  risk_block = "\n".join(risk_lines)
  initiative_block = "\n".join(initiative_lines)
  kpi_watch = portfolio_kpi_watchlist(conn, period_end, limit=5)
  kpi_block = "\n".join(kpi_watch) if kpi_watch else "- No KPI entries for this period."

  report = (
    f"# Daily Portfolio Brief\n"
    f"As of: {period_end}\n\n"
    "## Fund Snapshot\n"
    f"{dashboard}\n\n"
    "## Top Risk Companies\n"
    f"{risk_block}\n\n"
    "## Active Value-Creation Items\n"
    f"{initiative_block}\n\n"
    "## KPI Watchlist\n"
    f"{kpi_block}\n\n"
    "## Actions for Today\n"
    "- Review covenant headroom on top-risk companies.\n"
    "- Confirm owners and deadlines for at-risk initiatives.\n"
    "- Trigger lender/IC draft memos for any company with risk score >= 45."
  ).strip()

  if write_file:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = REPORTS_DIR / f"daily-brief-{period_end}.md"
    out_file.write_text(report + "\n", encoding="utf-8")

  return report


def send_webhook(channel: str, webhook_url: str, message: str) -> tuple[bool, str]:
  channel = channel.lower().strip()
  if channel not in ("slack", "teams"):
    return (False, f"Unsupported channel: {channel}")

  if channel == "slack":
    payload = {"text": message}
  else:
    payload = {"text": message}

  req = request.Request(
    webhook_url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
  )
  try:
    with request.urlopen(req, timeout=10) as resp:
      code = int(resp.status)
      if 200 <= code < 300:
        return (True, f"{channel} webhook delivered (HTTP {code})")
      return (False, f"{channel} webhook failed (HTTP {code})")
  except Exception as exc:
    return (False, f"{channel} webhook failed: {exc}")


def ask_agent(conn: sqlite3.Connection, question: str) -> str:
  q = question.strip().lower()

  company_row = None
  for row in conn.execute("SELECT name FROM companies ORDER BY length(name) DESC").fetchall():
    if row["name"].lower() in q:
      company_row = row["name"]
      break

  if "risk" in q and any(k in q for k in ["rank", "portfolio", "top"]):
    rows = compute_risk_rows(conn)
    if not rows:
      return "No data available."
    return "Portfolio risk ranking\n\n" + render_risk_table(rows)

  if "dashboard" in q or "fund snapshot" in q:
    return fund_dashboard(conn)

  if any(k in q for k in ["explain", "variance", "miss"]):
    if company_row is None:
      return "Please include a company name in your question for variance analysis."
    return explain_variance(conn, company_row)

  if "memo" in q or "lender update" in q or "ic" in q:
    if company_row is None:
      return "Please include a company name in your question for memo drafting."
    kind = "ic"
    if "lender" in q:
      kind = "lender"
    elif "board" in q:
      kind = "board"
    return draft_memo(conn, company_row, kind)

  if "daily" in q and "brief" in q:
    return daily_brief(conn)

  if "kpi" in q and ("watchlist" in q or "variance" in q):
    lines = portfolio_kpi_watchlist(conn)
    if not lines:
      return "No KPI records found for the latest period."
    return "KPI watchlist\n\n" + "\n".join(lines)

  return textwrap.dedent(
    """
    I can help with these queries:
    - "Show fund dashboard"
    - "Rank portfolio risk"
    - "Explain EBITDA miss for Rhein Software Solutions GmbH"
    - "Draft lender memo for Alpen Components GmbH"
    - "Generate daily brief"
    """
  ).strip()


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Daily PE portfolio agent")
  parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to sqlite db")

  sub = parser.add_subparsers(dest="cmd", required=True)

  sub.add_parser("init", help="Initialize database schema")
  sub.add_parser("seed-demo", help="Load demo portfolio data")

  p_comp = sub.add_parser("import-companies", help="Import companies CSV")
  p_comp.add_argument("--csv", type=Path, required=True)

  p_fin = sub.add_parser("import-financials", help="Import financials CSV")
  p_fin.add_argument("--csv", type=Path, required=True)

  p_cov = sub.add_parser("import-covenants", help="Import covenant definitions CSV")
  p_cov.add_argument("--csv", type=Path, required=True)

  p_tax = sub.add_parser("import-kpi-taxonomy", help="Import KPI taxonomy CSV")
  p_tax.add_argument("--csv", type=Path, required=True)

  p_kpis = sub.add_parser("import-kpis", help="Import operational KPI values CSV")
  p_kpis.add_argument("--csv", type=Path, required=True)

  p_dash = sub.add_parser("dashboard", help="Print fund dashboard")
  p_dash.add_argument("--period", help="Period end YYYY-MM-DD")

  p_risk = sub.add_parser("risk-rank", help="Print risk ranking table")
  p_risk.add_argument("--period", help="Period end YYYY-MM-DD")

  p_alert = sub.add_parser("refresh-alerts", help="Recompute risk alerts")
  p_alert.add_argument("--period", help="Period end YYYY-MM-DD")

  p_var = sub.add_parser("explain-variance", help="Explain company variance")
  p_var.add_argument("--company", required=True)
  p_var.add_argument("--period", help="Period end YYYY-MM-DD")

  p_memo = sub.add_parser("draft-memo", help="Draft lender/ic/board memo")
  p_memo.add_argument("--company", required=True)
  p_memo.add_argument("--kind", choices=["ic", "lender", "board"], default="ic")
  p_memo.add_argument("--period", help="Period end YYYY-MM-DD")

  p_daily = sub.add_parser("daily-brief", help="Generate daily brief markdown")
  p_daily.add_argument("--period", help="Period end YYYY-MM-DD")
  p_daily.add_argument("--stdout-only", action="store_true")
  p_daily.add_argument("--notify-slack-env", help="Env var name containing Slack webhook URL")
  p_daily.add_argument("--notify-teams-env", help="Env var name containing Teams webhook URL")

  p_ask = sub.add_parser("ask", help="Ask the rule-based agent")
  p_ask.add_argument("--q", required=True, help="Question")

  p_notify = sub.add_parser("notify", help="Send text to Slack/Teams webhook")
  p_notify.add_argument("--channel", choices=["slack", "teams"], required=True)
  p_notify.add_argument("--webhook-env", required=True, help="Environment variable with webhook URL")
  p_notify.add_argument("--message", required=True, help="Message text")

  return parser


def main() -> int:
  parser = build_parser()
  args = parser.parse_args()

  conn = connect_db(args.db)
  try:
    if args.cmd == "init":
      init_db(conn)
      print(f"Initialized DB at {args.db}")
      return 0

    init_db(conn)

    if args.cmd == "seed-demo":
      seed_demo(conn)
      print("Seeded demo data.")
      return 0

    if args.cmd == "import-companies":
      count = import_companies_csv(conn, args.csv)
      print(f"Imported companies rows: {count}")
      return 0

    if args.cmd == "import-financials":
      count = import_financials_csv(conn, args.csv)
      print(f"Imported financial rows: {count}")
      return 0

    if args.cmd == "import-covenants":
      count = import_covenants_csv(conn, args.csv)
      print(f"Imported covenant rows: {count}")
      return 0

    if args.cmd == "import-kpi-taxonomy":
      count = import_kpi_taxonomy_csv(conn, args.csv)
      print(f"Imported KPI taxonomy rows: {count}")
      return 0

    if args.cmd == "import-kpis":
      count = import_operational_kpis_csv(conn, args.csv)
      print(f"Imported operational KPI rows: {count}")
      return 0

    if args.cmd == "dashboard":
      print(fund_dashboard(conn, args.period))
      return 0

    if args.cmd == "risk-rank":
      rows = compute_risk_rows(conn, args.period)
      if not rows:
        print("No data.")
        return 0
      print(render_risk_table(rows))
      return 0

    if args.cmd == "refresh-alerts":
      count = upsert_alerts_from_risk(conn, args.period)
      print(f"Refreshed alerts for {count} companies")
      return 0

    if args.cmd == "explain-variance":
      print(explain_variance(conn, args.company, args.period))
      return 0

    if args.cmd == "draft-memo":
      print(draft_memo(conn, args.company, args.kind, args.period))
      return 0

    if args.cmd == "daily-brief":
      report = daily_brief(conn, args.period, write_file=not args.stdout_only)
      print(report)
      if not args.stdout_only:
        period = args.period or latest_period(conn)
        print(f"\nSaved to: {REPORTS_DIR / f'daily-brief-{period}.md'}")
      webhook_results = []
      if args.notify_slack_env:
        slack_url = os.getenv(args.notify_slack_env, "").strip()
        if slack_url:
          webhook_results.append(send_webhook("slack", slack_url, report))
        else:
          webhook_results.append((False, f"Env var {args.notify_slack_env} is empty"))
      if args.notify_teams_env:
        teams_url = os.getenv(args.notify_teams_env, "").strip()
        if teams_url:
          webhook_results.append(send_webhook("teams", teams_url, report))
        else:
          webhook_results.append((False, f"Env var {args.notify_teams_env} is empty"))
      for ok, msg in webhook_results:
        prefix = "OK" if ok else "WARN"
        print(f"{prefix}: {msg}")
      return 0

    if args.cmd == "ask":
      print(ask_agent(conn, args.q))
      return 0

    if args.cmd == "notify":
      url = os.getenv(args.webhook_env, "").strip()
      if not url:
        print(f"Webhook env var {args.webhook_env} is empty")
        return 1
      ok, msg = send_webhook(args.channel, url, args.message)
      print(msg)
      return 0 if ok else 1

    parser.print_help()
    return 1
  finally:
    conn.close()


if __name__ == "__main__":
  raise SystemExit(main())
