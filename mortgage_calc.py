from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ANNUITY = "annuity"
DIFFERENTIATED = "differentiated"

PAYMENT_TYPES = {
    "Аннуитетный": ANNUITY,
    "Дифференцированный": DIFFERENTIATED,
}


class MortgageInputError(ValueError):
    pass


@dataclass(frozen=True)
class MortgageInput:
    property_price: float
    down_payment: float
    down_payment_in_percent: bool
    annual_rate_percent: float
    term_years: int
    payment_type: str


@dataclass(frozen=True)
class MortgageResult:
    loan_amount: float
    down_payment_amount: float
    monthly_payment_first: float
    monthly_payment_last: float
    total_payment: float
    total_interest: float
    interest_share_percent: float
    schedule: pd.DataFrame


def _down_payment_amount(data: MortgageInput) -> float:
    if data.down_payment_in_percent:
        amount = data.property_price * data.down_payment / 100
    else:
        amount = data.down_payment
    return round(amount, 2)


def _validate_input(data: MortgageInput) -> float:
    if data.payment_type not in (ANNUITY, DIFFERENTIATED):
        raise MortgageInputError("Выберите тип платежа: аннуитетный или дифференцированный.")

    if data.property_price <= 0:
        raise MortgageInputError("Стоимость недвижимости должна быть больше нуля.")

    if data.annual_rate_percent <= 0 or data.annual_rate_percent > 100:
        raise MortgageInputError(
            "Годовая процентная ставка должна быть больше нуля и не превышать 100%."
        )

    if data.term_years <= 0:
        raise MortgageInputError("Срок кредита должен быть больше нуля.")

    if data.term_years > 40:
        raise MortgageInputError("Срок кредита не может превышать 40 лет.")

    if data.down_payment < 0:
        raise MortgageInputError("Первоначальный взнос не может быть отрицательным.")

    if data.down_payment_in_percent:
        if data.down_payment >= 100:
            raise MortgageInputError(
                "Первоначальный взнос в процентах должен быть меньше 100%."
            )
    down_payment_amount = _down_payment_amount(data)

    loan_amount = round(data.property_price - down_payment_amount, 2)
    if loan_amount <= 0:
        raise MortgageInputError(
            "Первоначальный взнос должен быть меньше стоимости недвижимости, "
            "чтобы осталась сумма кредита."
        )

    return loan_amount


def _annuity_payment(loan_amount: float, monthly_rate: float, months: int) -> float:
    if monthly_rate == 0:
        return loan_amount / months
    growth = (1 + monthly_rate) ** months
    return loan_amount * monthly_rate * growth / (growth - 1)


def _build_schedule(
    loan_amount: float,
    monthly_rate: float,
    months: int,
    payment_type: str,
) -> pd.DataFrame:
    if payment_type == ANNUITY:
        monthly_payment = _annuity_payment(loan_amount, monthly_rate, months)
    else:
        monthly_payment = None

    rows = []
    remaining = loan_amount
    fixed_principal = loan_amount / months

    for month in range(1, months + 1):
        interest_part = remaining * monthly_rate
        if payment_type == ANNUITY:
            principal_part = monthly_payment - interest_part
            if month == months:
                principal_part = remaining
            payment = principal_part + interest_part
        else:
            principal_part = fixed_principal
            if month == months:
                principal_part = remaining
            payment = principal_part + interest_part

        remaining = remaining - principal_part
        rows.append(
            {
                "Месяц": month,
                "Платёж": payment,
                "Основной долг": principal_part,
                "Проценты": interest_part,
                "Остаток долга": max(remaining, 0.0),
            }
        )

    return pd.DataFrame(rows)


def _round_schedule(schedule: pd.DataFrame, loan_amount: float) -> pd.DataFrame:
    payment_column = "Платёж"
    principal_column = "Основной долг"
    interest_column = "Проценты"
    balance_column = "Остаток долга"

    schedule[principal_column] = schedule[principal_column].round(2)
    schedule[interest_column] = schedule[interest_column].round(2)

    last_index = schedule.index[-1]
    principal_before_last = schedule.loc[schedule.index[:-1], principal_column].sum()
    schedule.loc[last_index, principal_column] = round(
        loan_amount - principal_before_last,
        2,
    )

    schedule[payment_column] = (
        schedule[principal_column] + schedule[interest_column]
    ).round(2)
    schedule[balance_column] = (
        loan_amount - schedule[principal_column].cumsum()
    ).round(2).clip(lower=0)
    schedule.loc[last_index, balance_column] = 0.0

    return schedule


def calculate_mortgage(data: MortgageInput) -> MortgageResult:
    loan_amount = _validate_input(data)
    down_payment_amount = _down_payment_amount(data)

    monthly_rate = data.annual_rate_percent / 100 / 12
    months = data.term_years * 12

    schedule = _round_schedule(
        _build_schedule(loan_amount, monthly_rate, months, data.payment_type),
        loan_amount,
    )

    total_payment = round(float(schedule["Платёж"].sum()), 2)
    total_interest = round(float(schedule["Проценты"].sum()), 2)
    interest_share_percent = (total_interest / total_payment * 100) if total_payment else 0.0

    return MortgageResult(
        loan_amount=loan_amount,
        down_payment_amount=down_payment_amount,
        monthly_payment_first=float(schedule["Платёж"].iloc[0]),
        monthly_payment_last=float(schedule["Платёж"].iloc[-1]),
        total_payment=total_payment,
        total_interest=total_interest,
        interest_share_percent=interest_share_percent,
        schedule=schedule,
    )
