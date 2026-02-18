from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class InvestorType(str, enum.Enum):
    FAMILY_OFFICE = "family_office"
    PE_FUND = "pe_fund"
    INSTITUTIONAL = "institutional"
    HNWI = "hnwi"
    CORPORATE_VC = "corporate_vc"
    FUND_OF_FUNDS = "fund_of_funds"
    PENSION_FUND = "pension_fund"
    INSURANCE = "insurance"
    BANK = "bank"
    DEVELOPMENT_BANK = "development_bank"


class InvestorStatus(str, enum.Enum):
    IDENTIFIED = "identified"
    RESEARCHED = "researched"
    CONTACTED = "contacted"
    IN_DIALOGUE = "in_dialogue"
    INTERESTED = "interested"
    COMMITTED = "committed"
    DECLINED = "declined"
    DORMANT = "dormant"


@dataclass
class Investor:
    """A potential co-investor for independent sponsor deals in the DACH region."""

    name: str
    investor_type: InvestorType | str
    country: str  # DE, AT, CH

    city: Optional[str] = None
    website: Optional[str] = None

    min_ticket_eur: Optional[float] = None
    max_ticket_eur: Optional[float] = None
    typical_ticket_eur: Optional[float] = None
    aum_eur: Optional[float] = None

    sector_preferences: list[str] = field(default_factory=list)
    deal_type_preferences: list[str] = field(default_factory=list)
    geographic_focus: list[str] = field(default_factory=lambda: ["DACH"])

    co_invest_appetite: bool = True
    independent_sponsor_friendly: bool = True
    requires_lead: bool = False
    requires_board_seat: bool = False

    status: InvestorStatus = InvestorStatus.IDENTIFIED
    relationship_score: float = 0.0

    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_linkedin: Optional[str] = None

    source: str = ""
    notes: str = ""
    last_interaction: Optional[str] = None

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self) -> None:
        if isinstance(self.investor_type, str):
            self.investor_type = InvestorType(self.investor_type)
        if isinstance(self.status, str):
            self.status = InvestorStatus(self.status)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "investor_type": self.investor_type.value,
            "country": self.country,
            "city": self.city,
            "website": self.website,
            "min_ticket_eur": self.min_ticket_eur,
            "max_ticket_eur": self.max_ticket_eur,
            "typical_ticket_eur": self.typical_ticket_eur,
            "aum_eur": self.aum_eur,
            "sector_preferences": self.sector_preferences,
            "deal_type_preferences": self.deal_type_preferences,
            "geographic_focus": self.geographic_focus,
            "co_invest_appetite": self.co_invest_appetite,
            "independent_sponsor_friendly": self.independent_sponsor_friendly,
            "requires_lead": self.requires_lead,
            "requires_board_seat": self.requires_board_seat,
            "status": self.status.value,
            "relationship_score": self.relationship_score,
            "contact_name": self.contact_name,
            "contact_title": self.contact_title,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "contact_linkedin": self.contact_linkedin,
            "source": self.source,
            "notes": self.notes,
            "last_interaction": self.last_interaction,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Investor:
        data = dict(data)
        data["investor_type"] = InvestorType(data["investor_type"])
        data["status"] = InvestorStatus(data["status"])
        return cls(**data)

    def ticket_in_range(self, amount_eur: float) -> bool:
        if self.min_ticket_eur is not None and amount_eur < self.min_ticket_eur:
            return False
        if self.max_ticket_eur is not None and amount_eur > self.max_ticket_eur:
            return False
        return True

    def matches_sector(self, sector: str) -> bool:
        if not self.sector_preferences:
            return True
        return sector in self.sector_preferences

    def matches_geography(self, region: str) -> bool:
        if not self.geographic_focus:
            return True
        return region in self.geographic_focus or "DACH" in self.geographic_focus
