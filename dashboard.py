from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def remaining_debt_chart(schedule: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        go.Scatter(
            x=schedule["Месяц"],
            y=schedule["Остаток долга"],
            mode="lines",
            name="Остаток долга",
            line={"width": 2.5},
        )
    )
    fig.update_layout(
        title="Остаток долга по месяцам",
        xaxis_title="Месяц",
        yaxis_title="Рубли (₽)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        margin={"l": 40, "r": 20, "t": 60, "b": 40},
    )
    return fig


def payment_structure_chart(schedule: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=schedule["Месяц"],
            y=schedule["Основной долг"],
            name="Основной долг",
            marker_color="#4C9F70",
        )
    )
    fig.add_bar(
        x=schedule["Месяц"],
        y=schedule["Проценты"],
        name="Проценты",
        marker_color="#E4572E",
    )
    fig.update_layout(
        title="Структура ежемесячного платежа",
        xaxis_title="Месяц",
        yaxis_title="Рубли (₽)",
        barmode="stack",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        margin={"l": 40, "r": 20, "t": 60, "b": 40},
    )
    return fig


def share_chart(principal_total: float, interest_total: float) -> go.Figure:
    fig = go.Figure(
        go.Pie(
            labels=["Основной долг", "Проценты"],
            values=[principal_total, interest_total],
            hole=0.45,
            textinfo="percent",
            marker={"colors": ["#4C9F70", "#E4572E"]},
        )
    )
    fig.update_layout(
        title="Доля основного долга и процентов в общей сумме выплат",
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
    )
    return fig


def cumulative_payment_chart(schedule: pd.DataFrame, loan_amount: float) -> go.Figure:
    cumulative_principal = schedule["Основной долг"].cumsum()
    cumulative_interest = schedule["Проценты"].cumsum()
    months = schedule["Месяц"]

    fig = go.Figure(
        go.Scatter(
            x=months,
            y=cumulative_principal,
            mode="lines",
            name="Выплаченный основной долг",
            line={"width": 2.5},
        )
    )
    fig.add_scatter(
        x=months,
        y=cumulative_interest,
        mode="lines",
        name="Выплаченные проценты",
        line={"width": 2.5},
    )
    fig.add_hline(
        y=loan_amount,
        line_dash="dash",
        line_color="#888888",
        annotation_text="Сумма кредита",
        annotation_position="right",
    )
    fig.update_layout(
        title="Накопленные выплаты",
        xaxis_title="Месяц",
        yaxis_title="Рубли (₽)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        margin={"l": 40, "r": 20, "t": 60, "b": 40},
    )
    return fig


def build_dashboard(
    schedule: pd.DataFrame,
    loan_amount: float,
    principal_total: float,
    interest_total: float,
) -> list[go.Figure]:
    return [
        remaining_debt_chart(schedule),
        payment_structure_chart(schedule),
        cumulative_payment_chart(schedule, loan_amount),
        share_chart(principal_total, interest_total),
    ]