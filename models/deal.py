from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class DealStage(str, enum.Enum):
    IDENTIFIED = "identified"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    IN_REVIEW = "in_review"
    DUE_DILIGENCE = "due_diligence"
    NEGOTIATION = "negotiation"
    CLOSED = "closed"
    PASSED = "passed"


@dataclass
class DealCriteria:
    """Filter criteria for sourcing SME deals in Germany."""

    min_revenue_eur: float = 5_000_000
    max_revenue_eur: float = 250_000_000
    min_ebitda_eur: Optional[float] = None
    max_ebitda_eur: Optional[float] = None
    min_ebitda_margin: Optional[float] = None
    target_sectors: list[str] = field(default_factory=lambda: [
        "Industrials",
        "Healthcare",
        "Technology",
        "Business Services",
        "Consumer Goods",
        "Automotive Suppliers",
    ])
    target_regions: list[str] = field(default_factory=lambda: [
        "Baden-Württemberg",
        "Bayern",
        "Nordrhein-Westfalen",
        "Hessen",
        "Niedersachsen",
    ])
    succession_only: bool = False
    exclude_turnaround: bool = True
    min_employees: int = 20
    max_employees: int = 2000


@dataclass
class Deal:
    """A potential PE deal in the German SME / Mittelstand sector."""

    company_name: str
    sector: str
    region: str
    city: str

    revenue_eur: Optional[float] = None
    ebitda_eur: Optional[float] = None
    ebitda_margin: Optional[float] = None
    employee_count: Optional[int] = None

    stage: DealStage = DealStage.IDENTIFIED
    score: float = 0.0

    is_succession: bool = False
    is_carve_out: bool = False
    has_advisor: bool = False
    advisor_name: Optional[str] = None

    source: str = ""
    source_url: Optional[str] = None
    description: str = ""
    notes: str = ""

    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self) -> None:
        if isinstance(self.stage, str):
            self.stage = DealStage(self.stage)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_name": self.company_name,
            "sector": self.sector,
            "region": self.region,
            "city": self.city,
            "revenue_eur": self.revenue_eur,
            "ebitda_eur": self.ebitda_eur,
            "ebitda_margin": self.ebitda_margin,
            "employee_count": self.employee_count,
            "stage": self.stage.value,
            "score": self.score,
            "is_succession": self.is_succession,
            "is_carve_out": self.is_carve_out,
            "has_advisor": self.has_advisor,
            "advisor_name": self.advisor_name,
            "source": self.source,
            "source_url": self.source_url,
            "description": self.description,
            "notes": self.notes,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Deal:
        data = dict(data)
        data["stage"] = DealStage(data["stage"])
        return cls(**data)

    def matches_criteria(self, criteria: DealCriteria) -> bool:
        if self.revenue_eur is not None:
            if self.revenue_eur < criteria.min_revenue_eur:
                return False
            if self.revenue_eur > criteria.max_revenue_eur:
                return False

        if self.ebitda_eur is not None and criteria.min_ebitda_eur is not None:
            if self.ebitda_eur < criteria.min_ebitda_eur:
                return False

        if self.ebitda_eur is not None and criteria.max_ebitda_eur is not None:
            if self.ebitda_eur > criteria.max_ebitda_eur:
                return False

        if self.ebitda_margin is not None and criteria.min_ebitda_margin is not None:
            if self.ebitda_margin < criteria.min_ebitda_margin:
                return False

        if self.employee_count is not None:
            if self.employee_count < criteria.min_employees:
                return False
            if self.employee_count > criteria.max_employees:
                return False

        if criteria.succession_only and not self.is_succession:
            return False

        if criteria.target_sectors:
            if self.sector not in criteria.target_sectors:
                return False

        if criteria.target_regions:
            if self.region not in criteria.target_regions:
                return False

        return True
