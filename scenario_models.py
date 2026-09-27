from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScenarioDraft:
    name: str
    property_price: float
    down_payment_value: float
    down_payment_unit: str
    down_payment_amount: float
    loan_amount: float
    annual_rate_percent: float
    term_years: int
    payment_type: str
    monthly_payment_first: float
    monthly_payment_last: float
    total_payment: float
    total_interest: float


@dataclass(frozen=True)
class MortgageScenario(ScenarioDraft):
    id: int
    created_at: datetime
    updated_at: datetime
