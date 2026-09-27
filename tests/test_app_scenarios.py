import sqlite3
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app import (
    build_comparison_table,
    format_money,
    format_percent,
    format_schedule_for_display,
    initialize_form_state,
    initialize_scenario_service,
    load_scenario_into_form,
    render_scenarios_section,
    scenario_card_data,
    set_down_payment_default_for_unit,
    start_new_scenario,
    to_csv,
)
from mortgage_calc import ANNUITY, DIFFERENTIATED, MortgageInput
from scenario_models import MortgageScenario
from scenario_service import ScenarioComparison, ScenarioStorageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class NumberFormattingTests(unittest.TestCase):
    def test_money_uses_russian_grouping_and_decimal_separator(self) -> None:
        self.assertEqual(format_money(17_000_000), "17.000.000,00 ₽")
        self.assertEqual(format_money(1_234.5), "1.234,50 ₽")

    def test_percent_uses_russian_decimal_separator(self) -> None:
        self.assertEqual(format_percent(15), "15,00 %")
        self.assertEqual(format_percent(15.25), "15,25 %")

    def test_csv_keeps_machine_readable_number_format(self) -> None:
        csv_data = to_csv(
            pd.DataFrame(
                {
                    "Месяц": [1],
                    "Платёж": [17_000_000.5],
                    "Проценты": [1_234.5],
                }
            )
        )
        csv_text = csv_data.decode("utf-8-sig")

        self.assertTrue(csv_data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Месяц;Платёж;Проценты", csv_text)
        self.assertIn("1;17000000,50;1234,50", csv_text)

    def test_schedule_display_is_formatted_without_changing_source_data(self) -> None:
        schedule = pd.DataFrame(
            {
                "Месяц": [1],
                "Платёж": [17_000_000.5],
                "Основной долг": [12_000_000.25],
            }
        )

        display_schedule = format_schedule_for_display(schedule)

        self.assertEqual(display_schedule.loc[0, "Платёж"], "17.000.000,50 ₽")
        self.assertEqual(
            display_schedule.loc[0, "Основной долг"], "12.000.000,25 ₽"
        )
        self.assertEqual(schedule.loc[0, "Платёж"], 17_000_000.5)


def make_mortgage_input() -> MortgageInput:
    return MortgageInput(
        property_price=7_000_000,
        down_payment=20,
        down_payment_in_percent=True,
        annual_rate_percent=15,
        term_years=20,
        payment_type=ANNUITY,
    )


def make_scenario(**overrides: object) -> MortgageScenario:
    timestamp = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    values = {
        "id": 1,
        "name": "Квартира у парка",
        "property_price": 7_000_000.25,
        "down_payment_value": 20.0,
        "down_payment_unit": "percent",
        "down_payment_amount": 1_400_000.05,
        "loan_amount": 5_600_000.20,
        "annual_rate_percent": 15.25,
        "term_years": 20,
        "payment_type": ANNUITY,
        "monthly_payment_first": 74_123.45,
        "monthly_payment_last": 74_123.45,
        "total_payment": 17_789_628.12,
        "total_interest": 12_189_627.92,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    values.update(overrides)
    return MortgageScenario(**values)


class StreamlitRecorder:
    def __init__(
        self,
        scenario_name: str = "",
        save_clicked: bool = False,
        editing_id: int | None = None,
        selected_ids: list[int] | None = None,
    ) -> None:
        self.scenario_name = scenario_name
        self.save_clicked = save_clicked
        self.session_state = {"editing_id": editing_id, "scenario_name": scenario_name}
        self.selected_ids = selected_ids or []
        self.subheaders: list[str] = []
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []
        self.text_input_calls = 0
        self.button_calls = 0
        self.buttons: list[tuple[str, dict]] = []
        self.tables: list[pd.DataFrame] = []
        self.max_selections: int | None = None

    def subheader(self, text: str) -> None:
        self.subheaders.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)

    def info(self, text: str) -> None:
        self.infos.append(text)

    def success(self, text: str) -> None:
        self.successes.append(text)

    def text_input(self, *args: object, **kwargs: object) -> str:
        self.text_input_calls += 1
        return self.scenario_name

    def button(self, *args: object, **kwargs: object) -> bool:
        self.button_calls += 1
        label = str(args[0])
        self.buttons.append((label, kwargs))
        return self.save_clicked and label in ("Сохранить сценарий", "Сохранить изменения")

    def multiselect(self, *args: object, **kwargs: object) -> list[int]:
        self.max_selections = kwargs.get("max_selections")
        return self.selected_ids

    def dataframe(self, table: pd.DataFrame, **kwargs: object) -> None:
        self.tables.append(table)

    def container(self, *args: object, **kwargs: object) -> "StreamlitRecorder":
        return self

    def __enter__(self) -> "StreamlitRecorder":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def markdown(self, text: str) -> None:
        pass

    def write(self, text: str) -> None:
        pass


class RecordingService:
    def __init__(
        self,
        scenarios: list[MortgageScenario] | None = None,
        save_error: Exception | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self.scenarios = scenarios or []
        self.save_error = save_error
        self.list_error = list_error
        self.saved_name: str | None = None
        self.saved_input: MortgageInput | None = None
        self.saved_id: int | None = None
        self.list_calls = 0
        self.compared_ids: tuple[int, ...] | None = None

    def save_scenario(
        self,
        name: str,
        mortgage_input: MortgageInput,
        scenario_id: int | None = None,
    ) -> MortgageScenario:
        if self.save_error is not None:
            raise self.save_error
        self.saved_name = name
        self.saved_input = mortgage_input
        self.saved_id = scenario_id
        return self.scenarios[0]

    def list_scenarios(self) -> list[MortgageScenario]:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return self.scenarios

    def get_scenario(self, scenario_id: int) -> MortgageScenario:
        return next(s for s in self.scenarios if s.id == scenario_id)

    def compare_scenarios(self, ids: list[int]) -> ScenarioComparison:
        self.compared_ids = tuple(ids)
        return ScenarioComparison(tuple(self.get_scenario(i) for i in ids))


class ScenarioCardFormattingTests(unittest.TestCase):
    def test_percent_down_payment_uses_saved_original_and_ruble_amount(self) -> None:
        data = scenario_card_data(make_scenario())

        self.assertEqual(data["down_payment_value"], "20,00 %")
        self.assertEqual(data["down_payment_amount"], "1.400.000,05 ₽")

    def test_ruble_down_payment_uses_saved_original_and_ruble_amount(self) -> None:
        data = scenario_card_data(
            make_scenario(
                down_payment_value=1_234_567.89,
                down_payment_unit="rubles",
                down_payment_amount=1_234_567.89,
            )
        )

        self.assertEqual(data["down_payment_value"], "1.234.567,89 ₽")
        self.assertEqual(data["down_payment_amount"], "1.234.567,89 ₽")

    def test_annuity_scenario_displays_one_saved_payment(self) -> None:
        data = scenario_card_data(make_scenario())

        self.assertEqual(data["payment_type"], "Аннуитетный")
        self.assertEqual(data["payment"], "74.123,45 ₽")

    def test_differentiated_scenario_displays_saved_payment_range(self) -> None:
        data = scenario_card_data(
            make_scenario(
                payment_type=DIFFERENTIATED,
                monthly_payment_first=120_001.23,
                monthly_payment_last=45_006.78,
            )
        )

        self.assertEqual(data["payment_type"], "Дифференцированный")
        self.assertEqual(data["payment"], "120.001,23 ₽ → 45.006,78 ₽")

    def test_card_contains_required_saved_indicators(self) -> None:
        data = scenario_card_data(make_scenario())

        self.assertEqual(data["property_price"], "7.000.000,25 ₽")
        self.assertEqual(data["annual_rate"], "15,25 %")
        self.assertEqual(data["term"], "20 лет")
        self.assertEqual(data["total_interest"], "12.189.627,92 ₽")


class ScenarioInitializationTests(unittest.TestCase):
    def test_sqlite_initialization_error_disables_scenario_service(self) -> None:
        with patch(
            "app.ScenarioRepository",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            service, error_message = initialize_scenario_service(public_demo=False)

        self.assertIsNone(service)
        self.assertEqual(
            error_message,
            "Не удалось открыть хранилище сохраненных сценариев.",
        )

    def test_importing_app_does_not_create_default_database(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "from unittest.mock import patch; "
                    "guard = patch('sqlite3.connect', "
                    "side_effect=AssertionError('SQLite opened during import')); "
                    "guard.start(); import app; guard.stop()"
                ),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


class ScenarioSectionTests(unittest.TestCase):
    def test_initialization_error_stops_only_scenario_operations(self) -> None:
        recorder = StreamlitRecorder()

        with patch("app.st", recorder):
            render_scenarios_section(
                make_mortgage_input(),
                service=None,
                initialization_error="Хранилище недоступно.",
            )

        self.assertEqual(recorder.errors, ["Хранилище недоступно."])
        self.assertEqual(recorder.text_input_calls, 0)
        self.assertEqual(recorder.button_calls, 0)

    def test_empty_scenario_list_shows_exact_empty_state(self) -> None:
        recorder = StreamlitRecorder()
        service = RecordingService()

        with patch("app.st", recorder):
            render_scenarios_section(
                make_mortgage_input(),
                service,
                initialization_error=None,
            )

        self.assertEqual(service.list_calls, 1)
        self.assertEqual(
            recorder.infos,
            [
                "Сохраненных сценариев пока нет. "
                "Рассчитайте первый вариант и сохраните его."
            ],
        )

    def test_save_passes_current_input_and_shows_success(self) -> None:
        mortgage_input = make_mortgage_input()
        saved = make_scenario(name="Вариант у парка")
        service = RecordingService([saved])
        recorder = StreamlitRecorder(
            scenario_name="Вариант у парка",
            save_clicked=True,
        )

        with patch("app.st", recorder):
            render_scenarios_section(
                mortgage_input,
                service,
                initialization_error=None,
            )

        self.assertEqual(service.saved_name, "Вариант у парка")
        self.assertIs(service.saved_input, mortgage_input)
        self.assertEqual(
            recorder.successes,
            ["Сценарий «Вариант у парка» успешно сохранен."],
        )

    def test_save_error_is_shown_without_escaping_the_ui_boundary(self) -> None:
        service = RecordingService(
            save_error=ScenarioStorageError("Не удалось сохранить сценарий.")
        )
        recorder = StreamlitRecorder(
            scenario_name="Вариант",
            save_clicked=True,
        )

        with patch("app.st", recorder):
            render_scenarios_section(
                make_mortgage_input(),
                service,
                initialization_error=None,
            )

        self.assertEqual(recorder.errors, ["Не удалось сохранить сценарий."])

    def test_list_error_is_shown_without_escaping_the_ui_boundary(self) -> None:
        service = RecordingService(
            list_error=ScenarioStorageError(
                "Не удалось получить сохраненные сценарии."
            )
        )
        recorder = StreamlitRecorder()

        with patch("app.st", recorder):
            render_scenarios_section(
                make_mortgage_input(),
                service,
                initialization_error=None,
            )

        self.assertEqual(
            recorder.errors,
            ["Не удалось получить сохраненные сценарии."],
        )


class ScenarioEditingTests(unittest.TestCase):
    def test_manual_unit_change_keeps_previous_default_behavior(self) -> None:
        state = {"down_payment_unit": "В рублях", "down_payment": 20.0}

        with patch("app.st.session_state", state):
            set_down_payment_default_for_unit()

        self.assertEqual(state["down_payment"], 1_400_000.0)

    def test_form_defaults_do_not_replace_existing_inputs(self) -> None:
        state = {"property_price": 8_500_000.0, "down_payment": 25.0}

        with patch("app.st.session_state", state):
            initialize_form_state()

        self.assertEqual(state["property_price"], 8_500_000.0)
        self.assertEqual(state["down_payment"], 25.0)
        self.assertIsNone(state["editing_id"])
        self.assertEqual(state["scenario_name"], "")

    def test_open_restores_original_form_inputs_and_editing_id(self) -> None:
        saved = make_scenario(
            id=7,
            name="Вариант в рублях",
            property_price=8_000_000.25,
            down_payment_value=1_500_000.75,
            down_payment_unit="rubles",
            annual_rate_percent=12.5,
            term_years=15,
            payment_type=DIFFERENTIATED,
        )
        state = {"property_price": 2_000_000.0, "down_payment": 10.0}
        service = RecordingService([saved])

        with patch("app.st.session_state", state):
            load_scenario_into_form(service, saved.id)

        self.assertEqual(state["editing_id"], 7)
        self.assertEqual(state["scenario_name"], "Вариант в рублях")
        self.assertEqual(state["property_price"], 8_000_000.25)
        self.assertEqual(state["down_payment_unit"], "В рублях")
        self.assertEqual(state["down_payment"], 1_500_000.75)
        self.assertEqual(state["annual_rate"], 12.5)
        self.assertEqual(state["term_years"], 15)
        self.assertEqual(state["payment_type_label"], "Дифференцированный")

    def test_new_scenario_keeps_current_inputs_and_clears_identity(self) -> None:
        state = {
            "editing_id": 7,
            "scenario_name": "Старый вариант",
            "property_price": 8_000_000.25,
            "down_payment": 1_500_000.75,
            "down_payment_unit": "В рублях",
            "annual_rate": 12.5,
            "term_years": 15,
            "payment_type_label": "Дифференцированный",
        }

        with patch("app.st.session_state", state):
            start_new_scenario()

        self.assertIsNone(state["editing_id"])
        self.assertEqual(state["scenario_name"], "")
        self.assertEqual(state["property_price"], 8_000_000.25)
        self.assertEqual(state["down_payment"], 1_500_000.75)
        self.assertEqual(state["down_payment_unit"], "В рублях")
        self.assertEqual(state["annual_rate"], 12.5)
        self.assertEqual(state["term_years"], 15)
        self.assertEqual(state["payment_type_label"], "Дифференцированный")

    def test_editing_saves_under_same_id_and_keeps_mode(self) -> None:
        saved = make_scenario(id=7, name="Измененный вариант")
        service = RecordingService([saved])
        recorder = StreamlitRecorder(
            scenario_name="Измененный вариант", save_clicked=True, editing_id=7
        )

        with patch("app.st", recorder):
            render_scenarios_section(make_mortgage_input(), service, None)

        self.assertEqual(service.saved_id, 7)
        self.assertEqual(recorder.session_state["editing_id"], 7)
        self.assertIn("Сохранить изменения", [label for label, _ in recorder.buttons])
        self.assertEqual(
            recorder.successes, ["Сценарий «Измененный вариант» успешно обновлен."]
        )

    def test_new_mode_saves_without_existing_id(self) -> None:
        saved = make_scenario()
        service = RecordingService([saved])
        recorder = StreamlitRecorder(scenario_name="Новый", save_clicked=True)

        with patch("app.st", recorder):
            render_scenarios_section(make_mortgage_input(), service, None)

        self.assertIsNone(service.saved_id)

    def test_open_buttons_use_callbacks_for_safe_form_state_update(self) -> None:
        saved = make_scenario(id=7)
        service = RecordingService([saved])
        recorder = StreamlitRecorder()

        with patch("app.st", recorder):
            render_scenarios_section(make_mortgage_input(), service, None)

        open_buttons = [kwargs for label, kwargs in recorder.buttons if label == "Открыть"]
        self.assertEqual(len(open_buttons), 1)
        self.assertTrue(callable(open_buttons[0]["on_click"]))

    def test_open_error_is_reported_without_changing_current_form(self) -> None:
        state = {"editing_id": 7, "property_price": 8_000_000.0}
        service = RecordingService()

        with patch("app.st.session_state", state):
            with patch.object(
                service, "get_scenario", side_effect=ScenarioStorageError("Не удалось открыть сценарий.")
            ):
                load_scenario_into_form(service, 9)

        self.assertEqual(state["editing_id"], 7)
        self.assertEqual(state["property_price"], 8_000_000.0)
        self.assertEqual(state["scenario_action_error"], "Не удалось открыть сценарий.")


class ComparisonDisplayTests(unittest.TestCase):
    def test_two_saved_scenarios_show_annuity_and_differentiated_values(self) -> None:
        annuity = make_scenario(id=1, name="Аннуитет")
        differentiated = make_scenario(
            id=2,
            name="Дифференцированный",
            down_payment_unit="rubles",
            down_payment_value=1_500_000.75,
            down_payment_amount=1_500_000.75,
            payment_type=DIFFERENTIATED,
            monthly_payment_first=120_001.23,
            monthly_payment_last=45_006.78,
        )

        table = build_comparison_table((annuity, differentiated))

        self.assertEqual(len(table.columns), 2)
        self.assertEqual(table.loc["Платёж", "Аннуитет (ID 1)"], "74.123,45 ₽")
        self.assertEqual(
            table.loc["Платёж", "Дифференцированный (ID 2)"],
            "120.001,23 ₽ → 45.006,78 ₽",
        )
        self.assertEqual(
            table.loc["Первоначальный взнос", "Дифференцированный (ID 2)"],
            "1.500.000,75 ₽ (1.500.000,75 ₽)",
        )
        self.assertEqual(table.loc["Сумма кредита", "Аннуитет (ID 1)"], "5.600.000,20 ₽")
        self.assertEqual(table.loc["Общая сумма выплат", "Аннуитет (ID 1)"], "17.789.628,12 ₽")

    def test_three_saved_scenarios_are_compared_in_selected_order(self) -> None:
        scenarios = (
            make_scenario(id=3, name="Третий"),
            make_scenario(id=1, name="Первый"),
            make_scenario(id=2, name="Второй"),
        )

        table = build_comparison_table(scenarios)

        self.assertEqual(
            list(table.columns),
            ["Третий (ID 3)", "Первый (ID 1)", "Второй (ID 2)"],
        )

    def test_two_selected_scenarios_use_saved_service_results(self) -> None:
        scenarios = [make_scenario(id=1), make_scenario(id=2, payment_type=DIFFERENTIATED)]
        service = RecordingService(scenarios)
        recorder = StreamlitRecorder(selected_ids=[2, 1])

        with patch("app.st", recorder):
            render_scenarios_section(make_mortgage_input(), service, None)

        self.assertEqual(service.compared_ids, (2, 1))
        self.assertEqual(recorder.max_selections, 3)
        self.assertEqual(len(recorder.tables), 1)
        self.assertEqual(list(recorder.tables[0].columns), [
            f"{scenarios[1].name} (ID 2)", f"{scenarios[0].name} (ID 1)"
        ])

    def test_three_selected_scenarios_use_service(self) -> None:
        scenarios = [make_scenario(id=i) for i in (1, 2, 3)]
        service = RecordingService(scenarios)
        recorder = StreamlitRecorder(selected_ids=[3, 1, 2])

        with patch("app.st", recorder):
            render_scenarios_section(make_mortgage_input(), service, None)

        self.assertEqual(service.compared_ids, (3, 1, 2))
        self.assertEqual(len(recorder.tables[0].columns), 3)

    def test_one_selected_scenario_shows_guidance_without_comparing(self) -> None:
        service = RecordingService([make_scenario()])
        recorder = StreamlitRecorder(selected_ids=[1])

        with patch("app.st", recorder):
            render_scenarios_section(make_mortgage_input(), service, None)

        self.assertIsNone(service.compared_ids)
        self.assertIn("Для сравнения выберите еще один сценарий.", recorder.infos)


if __name__ == "__main__":
    unittest.main()
