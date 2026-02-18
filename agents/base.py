from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class BaseAgent(ABC):
    """Shared foundation for all sourcing agents.

    Provides JSON-based persistence, logging, and a run-loop skeleton.
    Subclasses implement the domain-specific sourcing, scoring, and
    reporting logic.
    """

    def __init__(self, name: str, data_file: str) -> None:
        self.name = name
        self._data_path = DATA_DIR / data_file
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._records: list[dict] = self._load()
        logger.info("%s initialised with %d records", self.name, len(self._records))

    # -- persistence ----------------------------------------------------------

    def _load(self) -> list[dict]:
        if self._data_path.exists():
            with open(self._data_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return []

    def _save(self) -> None:
        with open(self._data_path, "w", encoding="utf-8") as fh:
            json.dump(self._records, fh, indent=2, ensure_ascii=False)
        logger.debug("%s saved %d records to %s", self.name, len(self._records), self._data_path)

    # -- CRUD helpers ---------------------------------------------------------

    def _add_record(self, record: dict) -> dict:
        record["updated_at"] = datetime.utcnow().isoformat()
        self._records.append(record)
        self._save()
        return record

    def _update_record(self, record_id: str, updates: dict) -> dict | None:
        for rec in self._records:
            if rec["id"] == record_id:
                rec.update(updates)
                rec["updated_at"] = datetime.utcnow().isoformat()
                self._save()
                return rec
        return None

    def _find_record(self, record_id: str) -> dict | None:
        for rec in self._records:
            if rec["id"] == record_id:
                return rec
        return None

    def _remove_record(self, record_id: str) -> bool:
        before = len(self._records)
        self._records = [r for r in self._records if r["id"] != record_id]
        if len(self._records) < before:
            self._save()
            return True
        return False

    def _filter_records(self, predicate) -> list[dict]:
        return [r for r in self._records if predicate(r)]

    # -- abstract interface ---------------------------------------------------

    @abstractmethod
    def source(self, **kwargs: Any) -> list[dict]:
        """Run one sourcing cycle and return newly found records."""

    @abstractmethod
    def score(self) -> None:
        """Re-score every record in the pipeline."""

    @abstractmethod
    def report(self) -> dict:
        """Return a summary dict of the current pipeline."""

    # -- run loop -------------------------------------------------------------

    def run_cycle(self, **kwargs: Any) -> dict:
        """Execute a single source -> score -> report cycle."""
        logger.info("%s: starting cycle", self.name)
        new = self.source(**kwargs)
        logger.info("%s: sourced %d new records", self.name, len(new))
        self.score()
        summary = self.report()
        logger.info("%s: cycle complete – %s", self.name, summary)
        return summary
