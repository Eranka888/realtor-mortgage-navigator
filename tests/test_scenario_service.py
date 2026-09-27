import sqlite3
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

from mortgage_calc import ANNUITY, DIFFERENTIATED, MortgageInput
from scenario_repository import ScenarioRepository
from scenario_service import (
    ScenarioComparison,
    ScenarioNotFoundError,
    ScenarioService,
    ScenarioStorageError,
    ScenarioValidationError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_mortgage_input(**overrides: object) -> MortgageInput:
    values = {
        "property_price": 1_200_000,
        "down_payment": 20,
        "down_payment_in_percent": True,
        "annual_rate_percent": 12,
        "term_years": 1,
        "payment_type": ANNUITY,
    }
    values.update(overrides)
    return MortgageInput(**values)


class FailingRepository:
    def list_all(self) -> list[object]:
        raise sqlite3.OperationalError("database is locked")


class ScenarioServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = self.create_temporary_database_path()
        self.repository = ScenarioRepository(self.database_path)
        self.service = ScenarioService(self.repository)

    def create_temporary_database_path(self) -> Path:
        with NamedTemporaryFile(
            dir=PROJECT_ROOT,
            suffix=".db",
            delete=False,
        ) as temporary_file:
            database_path = Path(temporary_file.name)
        database_path.unlink()
        self.addCleanup(self.remove_database_files, database_path)
        return database_path

    def remove_database_files(self, database_path: Path) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = Path(f"{database_path}{suffix}")
            if path.exists():
                path.unlink()

    def test_saves_annuity_scenario_with_percent_down_payment(self) -> None:
        saved = self.service.save_scenario(
            "Аннуитет, взнос 20%",
            make_mortgage_input(),
        )

        self.assertEqual(saved.name, "Аннуитет, взнос 20%")
        self.assertEqual(saved.down_payment_value, 20)
        self.assertEqual(saved.down_payment_unit, "percent")
        self.assertEqual(saved.down_payment_amount, 240_000)
        self.assertEqual(saved.loan_amount, 960_000)
        self.assertEqual(saved.payment_type, ANNUITY)
        self.assertEqual(saved.monthly_payment_first, 85_294.84)
        self.assertEqual(saved.monthly_payment_last, 85_294.84)
        self.assertEqual(saved.total_payment, 1_023_538.05)
        self.assertEqual(saved.total_interest, 63_538.05)

    def test_saves_differentiated_scenario_with_ruble_down_payment(self) -> None:
        saved = self.service.save_scenario(
            "Дифференцированный",
            make_mortgage_input(
                down_payment=200_000,
                down_payment_in_percent=False,
                payment_type=DIFFERENTIATED,
            ),
        )

        self.assertEqual(saved.down_payment_value, 200_000)
        self.assertEqual(saved.down_payment_unit, "rubles")
        self.assertEqual(saved.down_payment_amount, 200_000)
        self.assertEqual(saved.loan_amount, 1_000_000)
        self.assertEqual(saved.payment_type, DIFFERENTIATED)
        self.assertEqual(saved.monthly_payment_first, 93_333.33)
        self.assertEqual(saved.monthly_payment_last, 84_166.70)
        self.assertEqual(saved.total_payment, 1_065_000)
        self.assertEqual(saved.total_interest, 65_000)

    def test_saves_second_scenario_and_lists_both(self) -> None:
        first = self.service.save_scenario("Первый", make_mortgage_input())
        second = self.service.save_scenario(
            "Второй",
            make_mortgage_input(annual_rate_percent=10),
        )

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(self.service.list_scenarios(), [first, second])

    def test_gets_saved_scenario_by_id(self) -> None:
        saved = self.service.save_scenario("Первый", make_mortgage_input())

        self.assertEqual(self.service.get_scenario(saved.id), saved)

    def test_unknown_scenario_id_is_an_application_error(self) -> None:
        with self.assertRaisesRegex(
            ScenarioNotFoundError,
            "Сценарий не найден",
        ):
            self.service.get_scenario(999)

    def test_update_recalculates_same_id_without_duplicate(self) -> None:
        original = self.service.save_scenario("Первый", make_mortgage_input())

        updated = self.service.save_scenario(
            "Первый — обновлен",
            make_mortgage_input(annual_rate_percent=10),
            scenario_id=original.id,
        )

        self.assertEqual(updated.id, original.id)
        self.assertEqual(updated.created_at, original.created_at)
        self.assertGreater(updated.updated_at, original.updated_at)
        self.assertEqual(updated.annual_rate_percent, 10)
        self.assertEqual(len(self.service.list_scenarios()), 1)

    def test_update_unknown_id_is_an_application_error(self) -> None:
        with self.assertRaisesRegex(
            ScenarioNotFoundError,
            "Сценарий не найден",
        ):
            self.service.save_scenario(
                "Неизвестный",
                make_mortgage_input(),
                scenario_id=999,
            )

    def test_compares_two_saved_scenarios_in_selected_order(self) -> None:
        first = self.service.save_scenario("Первый", make_mortgage_input())
        second = self.service.save_scenario(
            "Второй",
            make_mortgage_input(payment_type=DIFFERENTIATED),
        )

        comparison = self.service.compare_scenarios([second.id, first.id])

        self.assertIsInstance(comparison, ScenarioComparison)
        self.assertEqual(comparison.scenarios, (second, first))

    def test_compares_three_saved_scenarios(self) -> None:
        saved = [
            self.service.save_scenario(
                f"Сценарий {number}",
                make_mortgage_input(annual_rate_percent=10 + number),
            )
            for number in range(1, 4)
        ]

        comparison = self.service.compare_scenarios(
            [scenario.id for scenario in saved]
        )

        self.assertEqual(comparison.scenarios, tuple(saved))

    def test_comparison_rejects_one_scenario(self) -> None:
        saved = self.service.save_scenario("Один", make_mortgage_input())

        with self.assertRaisesRegex(
            ScenarioValidationError,
            "2–3 разных сценария",
        ):
            self.service.compare_scenarios([saved.id])

    def test_comparison_rejects_more_than_three_scenarios(self) -> None:
        saved = [
            self.service.save_scenario(
                f"Сценарий {number}",
                make_mortgage_input(annual_rate_percent=10 + number),
            )
            for number in range(1, 5)
        ]

        with self.assertRaisesRegex(
            ScenarioValidationError,
            "2–3 разных сценария",
        ):
            self.service.compare_scenarios(
                [scenario.id for scenario in saved]
            )

    def test_comparison_rejects_repeated_id(self) -> None:
        saved = self.service.save_scenario("Один", make_mortgage_input())

        with self.assertRaisesRegex(
            ScenarioValidationError,
            "2–3 разных сценария",
        ):
            self.service.compare_scenarios([saved.id, saved.id])

    def test_empty_or_whitespace_only_name_is_rejected(self) -> None:
        for name in ("", "   ", "\t\n"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ScenarioValidationError,
                    "Введите название сценария",
                ):
                    self.service.save_scenario(name, make_mortgage_input())

        self.assertEqual(self.service.list_scenarios(), [])

    def test_invalid_mortgage_input_is_an_application_error(self) -> None:
        with self.assertRaisesRegex(
            ScenarioValidationError,
            "Стоимость недвижимости должна быть больше нуля",
        ):
            self.service.save_scenario(
                "Некорректный",
                make_mortgage_input(property_price=0),
            )

    def test_repository_error_is_translated_to_storage_error(self) -> None:
        service = ScenarioService(FailingRepository())

        with self.assertRaisesRegex(
            ScenarioStorageError,
            "Не удалось получить сохраненные сценарии",
        ):
            service.list_scenarios()


if __name__ == "__main__":
    unittest.main()
