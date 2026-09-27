from __future__ import annotations

import os
import sqlite3
from collections.abc import MutableMapping

import pandas as pd
import streamlit as st

import dashboard as dash
from mortgage_calc import (
    ANNUITY,
    DIFFERENTIATED,
    PAYMENT_TYPES,
    MortgageInput,
    MortgageInputError,
    calculate_mortgage,
)
from scenario_models import MortgageScenario
from scenario_repository import InMemoryScenarioRepository, ScenarioRepository
from scenario_service import ScenarioService, ScenarioServiceError


_DEMO_REPOSITORY_SESSION_KEY = "_demo_scenario_repository"
_DEMO_NOTICE = (
    "Демонстрационный режим. Сценарии хранятся только в текущей сессии "
    "и могут исчезнуть после ее завершения. Не вводите персональные данные."
)

_CSS_LIGHT = """
<style>
[data-testid="stAppViewContainer"] {
    background-color: #ffffff;
    color: #20232a;
}
[data-testid="stSidebar"] {
    background-color: #f0f4f8;
    color: #20232a;
}
[data-testid="stMetric"] {
    background-color: #f0f4f8;
    border: 1px solid #d9e2ec;
    border-radius: 8px;
    padding: 12px;
}
[data-testid="stButton"] button[kind="primary"] {
    background-color: #2563eb;
    border: 1px solid #1d4ed8;
    color: #ffffff;
    font-weight: 600;
}
[data-testid="stButton"] button[kind="primary"]:hover {
    background-color: #1d4ed8;
    border-color: #1e40af;
    color: #ffffff;
}
[data-testid="stButton"] button[kind="primary"]:active {
    background-color: #1e40af;
    border-color: #1e3a8a;
    color: #ffffff;
}
[data-testid="stButton"] button[kind="primary"]:focus-visible {
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.35);
}
[data-testid="stDownloadButton"] button[kind="secondary"] {
    background-color: #ffffff;
    border: 1px solid #94a3b8;
    color: #334155;
}
[data-testid="stDownloadButton"] button[kind="secondary"]:hover {
    background-color: #f1f5f9;
    border-color: #64748b;
    color: #1e293b;
}
[data-testid="stDownloadButton"] button[kind="secondary"]:active {
    background-color: #e2e8f0;
    border-color: #475569;
    color: #0f172a;
}
[data-testid="stDownloadButton"] button[kind="secondary"]:focus-visible {
    box-shadow: 0 0 0 3px rgba(100, 116, 139, 0.3);
}
</style>
"""

_CSS_DARK = """
<style>
[data-testid="stAppViewContainer"] {
    background-color: #0e1117;
}
[data-testid="stSidebar"] {
    background-color: #161b24;
    color: #fafafa;
}
[data-testid="stHeader"] {
    background: transparent;
}
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label {
    color: #fafafa;
}
[data-testid="stMetric"] {
    background-color: #161b24;
    border: 1px solid #2a3441;
    border-radius: 8px;
    padding: 12px;
}
[data-testid="stButton"] button[kind="primary"] {
    background-color: #2563eb;
    border: 1px solid #60a5fa;
    color: #ffffff;
    font-weight: 600;
}
[data-testid="stButton"] button[kind="primary"]:hover {
    background-color: #1d4ed8;
    border-color: #93c5fd;
    color: #ffffff;
}
[data-testid="stButton"] button[kind="primary"]:active {
    background-color: #1e40af;
    border-color: #bfdbfe;
    color: #ffffff;
}
[data-testid="stButton"] button[kind="primary"]:focus-visible {
    box-shadow: 0 0 0 3px rgba(147, 197, 253, 0.4);
}
[data-testid="stDownloadButton"] button[kind="secondary"] {
    background-color: #1f2937;
    border: 1px solid #64748b;
    color: #f8fafc;
}
[data-testid="stDownloadButton"] button[kind="secondary"]:hover {
    background-color: #334155;
    border-color: #94a3b8;
    color: #ffffff;
}
[data-testid="stDownloadButton"] button[kind="secondary"]:active {
    background-color: #475569;
    border-color: #cbd5e1;
    color: #ffffff;
}
[data-testid="stDownloadButton"] button[kind="secondary"]:focus-visible {
    box-shadow: 0 0 0 3px rgba(203, 213, 225, 0.35);
}
[data-testid="stDataFrame"] {
    background-color: #161b24;
    color: #fafafa;
}
</style>
"""


def apply_theme(is_dark: bool) -> None:
    st.markdown(_CSS_DARK if is_dark else _CSS_LIGHT, unsafe_allow_html=True)


def apply_plotly_theme(figures: list, is_dark: bool) -> None:
    if is_dark:
        template = "plotly_dark"
        paper_background = "#0e1117"
        plot_background = "#161b24"
        font_color = "#fafafa"
    else:
        template = "plotly_white"
        paper_background = "#ffffff"
        plot_background = "#f0f4f8"
        font_color = "#20232a"

    for figure in figures:
        figure.update_layout(
            template=template,
            paper_bgcolor=paper_background,
            plot_bgcolor=plot_background,
            font_color=font_color,
        )


def format_money(value: float) -> str:
    return f"{format_number(value)} ₽"


def format_number(value: float) -> str:
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_percent(value: float) -> str:
    return f"{format_number(value)} %"


def format_schedule_for_display(schedule: pd.DataFrame) -> pd.DataFrame:
    display_schedule = schedule.copy()
    for column in ("Платёж", "Основной долг", "Проценты", "Остаток долга"):
        if column in display_schedule:
            display_schedule[column] = display_schedule[column].map(format_money)
    return display_schedule


def to_csv(schedule: pd.DataFrame) -> bytes:
    return schedule.to_csv(
        index=False,
        sep=";",
        decimal=",",
        float_format="%.2f",
    ).encode("utf-8-sig")


def is_public_demo() -> bool:
    return os.getenv("PUBLIC_DEMO", "").strip().lower() == "true"


def render_demo_notice(public_demo: bool) -> None:
    if public_demo:
        st.info(_DEMO_NOTICE)


def initialize_scenario_service(
    public_demo: bool | None = None,
    session_state: MutableMapping[str, object] | None = None,
) -> tuple[ScenarioService | None, str | None]:
    if public_demo is None:
        public_demo = is_public_demo()

    if public_demo:
        state = st.session_state if session_state is None else session_state
        repository = state.get(_DEMO_REPOSITORY_SESSION_KEY)
        if not isinstance(repository, InMemoryScenarioRepository):
            repository = InMemoryScenarioRepository()
            state[_DEMO_REPOSITORY_SESSION_KEY] = repository
        return ScenarioService(repository), None

    try:
        return ScenarioService(ScenarioRepository()), None
    except (sqlite3.Error, OSError):
        return None, "Не удалось открыть хранилище сохраненных сценариев."


def initialize_form_state() -> None:
    defaults = {
        "property_price": 7_000_000.0,
        "down_payment_unit": "В процентах",
        "down_payment": 20.0,
        "annual_rate": 15.0,
        "term_years": 20,
        "payment_type_label": "Аннуитетный",
        "scenario_name": "",
        "editing_id": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def set_down_payment_default_for_unit() -> None:
    st.session_state["down_payment"] = (
        20.0 if st.session_state["down_payment_unit"] == "В процентах" else 1_400_000.0
    )


def load_scenario_into_form(service: ScenarioService, scenario_id: int) -> None:
    try:
        scenario = service.get_scenario(scenario_id)
    except ScenarioServiceError as error:
        st.session_state["scenario_action_error"] = str(error)
        return
    st.session_state["editing_id"] = scenario.id
    st.session_state["scenario_name"] = scenario.name
    st.session_state["property_price"] = scenario.property_price
    st.session_state["down_payment_unit"] = (
        "В процентах" if scenario.down_payment_unit == "percent" else "В рублях"
    )
    st.session_state["down_payment"] = scenario.down_payment_value
    st.session_state["annual_rate"] = scenario.annual_rate_percent
    st.session_state["term_years"] = scenario.term_years
    st.session_state["payment_type_label"] = next(
        label for label, value in PAYMENT_TYPES.items() if value == scenario.payment_type
    )


def start_new_scenario() -> None:
    st.session_state["editing_id"] = None
    st.session_state["scenario_name"] = ""


def scenario_card_data(scenario: MortgageScenario) -> dict[str, str]:
    if scenario.down_payment_unit == "percent":
        down_payment_value = format_percent(scenario.down_payment_value)
    else:
        down_payment_value = format_money(scenario.down_payment_value)

    if scenario.payment_type == ANNUITY:
        payment_type = "Аннуитетный"
        payment = format_money(scenario.monthly_payment_first)
    elif scenario.payment_type == DIFFERENTIATED:
        payment_type = "Дифференцированный"
        payment = (
            f"{format_money(scenario.monthly_payment_first)} → "
            f"{format_money(scenario.monthly_payment_last)}"
        )
    else:
        payment_type = scenario.payment_type
        payment = format_money(scenario.monthly_payment_first)

    return {
        "property_price": format_money(scenario.property_price),
        "down_payment_value": down_payment_value,
        "down_payment_amount": format_money(scenario.down_payment_amount),
        "annual_rate": format_percent(scenario.annual_rate_percent),
        "term": f"{scenario.term_years} лет",
        "payment_type": payment_type,
        "payment": payment,
        "total_interest": format_money(scenario.total_interest),
    }


def build_comparison_table(scenarios: tuple[MortgageScenario, ...]) -> pd.DataFrame:
    columns = {}
    for scenario in scenarios:
        data = scenario_card_data(scenario)
        columns[f"{scenario.name} (ID {scenario.id})"] = {
            "Стоимость недвижимости": data["property_price"],
            "Первоначальный взнос": (
                f"{data['down_payment_value']} ({data['down_payment_amount']})"
            ),
            "Сумма кредита": format_money(scenario.loan_amount),
            "Ставка": data["annual_rate"],
            "Срок": data["term"],
            "Тип платежа": data["payment_type"],
            "Платёж": data["payment"],
            "Общая сумма выплат": format_money(scenario.total_payment),
            "Переплата": data["total_interest"],
        }
    return pd.DataFrame(columns)


def render_scenario_card(scenario: MortgageScenario, service: ScenarioService) -> None:
    data = scenario_card_data(scenario)
    with st.container(border=True):
        st.markdown(f"#### {scenario.name}")
        st.write(f"**Стоимость недвижимости:** {data['property_price']}")
        st.write(f"**Исходный первоначальный взнос:** {data['down_payment_value']}")
        st.write(f"**Рассчитанный взнос:** {data['down_payment_amount']}")
        st.write(f"**Ставка:** {data['annual_rate']}")
        st.write(f"**Срок:** {data['term']}")
        st.write(f"**Тип платежа:** {data['payment_type']}")
        st.write(f"**Платеж:** {data['payment']}")
        st.write(f"**Переплата:** {data['total_interest']}")
        st.button(
            "Открыть",
            key=f"open_scenario_{scenario.id}",
            on_click=load_scenario_into_form,
            args=(service, scenario.id),
        )


def render_comparison_section(
    service: ScenarioService, scenarios: list[MortgageScenario]
) -> None:
    st.subheader("Сравнение сценариев")
    selected_ids = st.multiselect(
        "Выберите 2–3 сценария",
        options=[scenario.id for scenario in scenarios],
        format_func=lambda scenario_id: next(
            f"{scenario.name} (ID {scenario.id})"
            for scenario in scenarios
            if scenario.id == scenario_id
        ),
        max_selections=3,
        key="comparison_ids",
    )
    if len(selected_ids) == 1:
        st.info("Для сравнения выберите еще один сценарий.")
    elif len(selected_ids) >= 2:
        try:
            comparison = service.compare_scenarios(selected_ids)
        except ScenarioServiceError as error:
            st.error(str(error))
        else:
            st.dataframe(build_comparison_table(comparison.scenarios), width="stretch")


def render_scenarios_section(
    mortgage_input: MortgageInput,
    service: ScenarioService | None,
    initialization_error: str | None,
) -> None:
    if service is None:
        st.subheader("Сохраненные сценарии")
        st.error(
            initialization_error
            or "Не удалось открыть хранилище сохраненных сценариев."
        )
        return

    action_error = st.session_state.pop("scenario_action_error", None)
    if action_error:
        st.error(action_error)

    editing_id = st.session_state.get("editing_id")
    st.subheader("Редактировать сценарий" if editing_id is not None else "Сохранить текущий расчет")
    if editing_id is not None:
        st.info(f"Вы редактируете сценарий ID {editing_id}.")
        st.button("Новый сценарий", on_click=start_new_scenario, width="content")
    scenario_name = st.text_input(
        "Название сценария",
        placeholder="Например, квартира у парка",
        key="scenario_name",
    )
    if st.button(
        "Сохранить изменения" if editing_id is not None else "Сохранить сценарий",
        type="primary",
        width="content",
    ):
        try:
            saved = service.save_scenario(
                scenario_name, mortgage_input, scenario_id=editing_id
            )
        except ScenarioServiceError as error:
            st.error(str(error))
        else:
            action = "обновлен" if editing_id is not None else "сохранен"
            st.success(f"Сценарий «{saved.name}» успешно {action}.")

    st.subheader("Сохраненные сценарии")
    try:
        scenarios = service.list_scenarios()
    except ScenarioServiceError as error:
        st.error(str(error))
        return

    if not scenarios:
        st.info(
            "Сохраненных сценариев пока нет. "
            "Рассчитайте первый вариант и сохраните его."
        )
        return

    for scenario in scenarios:
        render_scenario_card(scenario, service)

    render_comparison_section(service, scenarios)


def main() -> None:
    st.set_page_config(
        page_title="Ипотечный калькулятор",
        page_icon="🏠",
        layout="wide",
    )

    st.title("Ипотечный калькулятор с дашбордом")
    public_demo = is_public_demo()
    render_demo_notice(public_demo)
    st.caption(
        "Рассчитайте ежемесячный платёж, переплату и график погашения. "
        "Поддерживаются аннуитетный и дифференцированный типы платежа."
    )

    initialize_form_state()

    with st.sidebar:
        st.header("Параметры кредита")

        property_price = st.number_input(
            "Стоимость недвижимости (₽)",
            min_value=0.0,
            step=100_000.0,
            format="%.2f",
            key="property_price",
        )

        down_payment_unit = st.radio(
            "Единица первоначального взноса",
            options=["В процентах", "В рублях"],
            horizontal=True,
            key="down_payment_unit",
            on_change=set_down_payment_default_for_unit,
        )
        down_payment_in_percent = down_payment_unit == "В процентах"

        down_payment = st.number_input(
            "Первоначальный взнос",
            min_value=0.0,
            step=1.0 if down_payment_in_percent else 50_000.0,
            format="%.2f",
            key="down_payment",
        )

        annual_rate = st.number_input(
            "Годовая процентная ставка (%)",
            min_value=0.01,
            step=0.1,
            format="%.2f",
            key="annual_rate",
        )

        term_years = st.number_input(
            "Срок кредита (лет)",
            min_value=1,
            max_value=40,
            step=1,
            key="term_years",
        )

        payment_type_label = st.selectbox(
            "Тип платежа",
            options=list(PAYMENT_TYPES.keys()),
            key="payment_type_label",
        )
        payment_type = PAYMENT_TYPES[payment_type_label]

        is_dark = st.toggle("Тёмная тема", value=False)
        apply_theme(is_dark)

    mortgage_input = MortgageInput(
        property_price=property_price,
        down_payment=down_payment,
        down_payment_in_percent=down_payment_in_percent,
        annual_rate_percent=annual_rate,
        term_years=int(term_years),
        payment_type=payment_type,
    )

    try:
        result = calculate_mortgage(mortgage_input)
    except MortgageInputError as exc:
        st.error(str(exc))
        st.stop()

    st.subheader("Итоговые показатели")

    metrics = st.columns(5)
    metrics[0].metric("Ежемесячный платёж", format_money(result.monthly_payment_first))
    if result.monthly_payment_last != result.monthly_payment_first:
        metrics[0].caption(
            f"от {format_money(result.monthly_payment_first)} до "
            f"{format_money(result.monthly_payment_last)}"
        )
    metrics[1].metric("Сумма кредита", format_money(result.loan_amount))
    metrics[2].metric("Общая сумма выплат", format_money(result.total_payment))
    metrics[3].metric("Переплата по процентам", format_money(result.total_interest))
    metrics[4].metric(
        "Доля процентов в выплатах", format_percent(result.interest_share_percent)
    )

    scenario_service, scenario_initialization_error = initialize_scenario_service(
        public_demo=public_demo,
    )
    render_scenarios_section(
        mortgage_input,
        scenario_service,
        scenario_initialization_error,
    )

    st.subheader("График платежей")

    schedule = result.schedule
    st.dataframe(
        format_schedule_for_display(schedule),
        width="stretch",
        hide_index=True,
    )

    st.download_button(
        label="Скачать график платежей (CSV)",
        data=to_csv(schedule),
        file_name="grafik_platezhey.csv",
        mime="text/csv",
        type="secondary",
        width="content",
    )

    st.subheader("Визуализация")

    figures = dash.build_dashboard(
        schedule=schedule,
        loan_amount=result.loan_amount,
        principal_total=result.loan_amount,
        interest_total=result.total_interest,
    )
    apply_plotly_theme(figures, is_dark)

    row1 = st.columns(2)
    with row1[0]:
        st.plotly_chart(figures[0])
    with row1[1]:
        st.plotly_chart(figures[1])

    row2 = st.columns(2)
    with row2[0]:
        st.plotly_chart(figures[2])
    with row2[1]:
        st.plotly_chart(figures[3])


if __name__ == "__main__":
    main()
