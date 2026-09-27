import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from database import connect_database
from scenario_models import MortgageScenario, ScenarioDraft
from scenario_repository import ScenarioRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class IncrementingClock:
    def __init__(self, start: datetime) -> None:
        self.next_value = start

    def __call__(self) -> datetime:
        value = self.next_value
        self.next_value += timedelta(minutes=1)
        return value


def make_scenario_draft(**overrides: object) -> ScenarioDraft:
    values = {
        "name": "Квартира у парка",
        "property_price": 7_000_000.25,
        "down_payment_value": 20.0,
        "down_payment_unit": "percent",
        "down_payment_amount": 1_400_000.05,
        "loan_amount": 5_600_000.20,
        "annual_rate_percent": 15.25,
        "term_years": 20,
        "payment_type": "annuity",
        "monthly_payment_first": 74_123.45,
        "monthly_payment_last": 74_123.44,
        "total_payment": 17_789_628.12,
        "total_interest": 12_189_627.92,
    }
    values.update(overrides)
    return ScenarioDraft(**values)


class ScenarioRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = self.create_temporary_database_path()
        self.start_time = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        self.clock = IncrementingClock(self.start_time)
        self.repository = ScenarioRepository(self.database_path, clock=self.clock)

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

    def assert_money_equal(self, actual: float, expected: float) -> None:
        self.assertEqual(round(actual, 2), round(expected, 2))

    def test_empty_database_returns_empty_list(self) -> None:
        self.assertEqual(self.repository.list_all(), [])

    def test_create_assigns_id_and_timestamps(self) -> None:
        saved = self.repository.create(make_scenario_draft())

        self.assertEqual(saved.id, 1)
        self.assertEqual(saved.created_at, self.start_time)
        self.assertEqual(saved.updated_at, self.start_time)

    def test_get_by_id_returns_saved_scenario(self) -> None:
        draft = make_scenario_draft()
        saved = self.repository.create(draft)

        loaded = self.repository.get_by_id(saved.id)

        self.assertEqual(loaded, saved)

    def test_unknown_id_returns_none(self) -> None:
        self.assertIsNone(self.repository.get_by_id(999))

    def test_multiple_scenarios_are_listed_in_stable_id_order(self) -> None:
        first = self.repository.create(make_scenario_draft(name="Первый"))
        second = self.repository.create(make_scenario_draft(name="Второй"))
        third = self.repository.create(make_scenario_draft(name="Третий"))

        listed = self.repository.list_all()

        self.assertEqual([scenario.id for scenario in listed], [1, 2, 3])
        self.assertEqual(listed, [first, second, third])

    def test_scenario_survives_reopening_database(self) -> None:
        saved = self.repository.create(make_scenario_draft())

        reopened_repository = ScenarioRepository(self.database_path)

        self.assertEqual(reopened_repository.get_by_id(saved.id), saved)

    def test_all_fields_and_kopecks_survive_round_trip(self) -> None:
        draft = make_scenario_draft(
            down_payment_value=1_234_567.89,
            down_payment_unit="rubles",
            down_payment_amount=1_234_567.89,
            payment_type="differentiated",
            monthly_payment_first=120_001.23,
            monthly_payment_last=45_006.78,
        )

        saved = self.repository.create(draft)
        loaded = self.repository.get_by_id(saved.id)

        self.assertIsInstance(loaded, MortgageScenario)
        assert loaded is not None
        for field_name in (
            "property_price",
            "down_payment_value",
            "down_payment_amount",
            "loan_amount",
            "annual_rate_percent",
            "monthly_payment_first",
            "monthly_payment_last",
            "total_payment",
            "total_interest",
        ):
            with self.subTest(field_name=field_name):
                self.assert_money_equal(
                    getattr(loaded, field_name),
                    getattr(draft, field_name),
                )
        self.assertEqual(loaded.name, draft.name)
        self.assertEqual(loaded.down_payment_unit, "rubles")
        self.assertEqual(loaded.term_years, draft.term_years)
        self.assertEqual(loaded.payment_type, "differentiated")
        self.assertEqual(loaded.created_at, saved.created_at)
        self.assertEqual(loaded.updated_at, saved.updated_at)

    def test_update_preserves_identity_and_creation_time_without_duplicate(self) -> None:
        original = self.repository.create(make_scenario_draft())
        replacement = make_scenario_draft(
            name="Обновлённый вариант",
            annual_rate_percent=13.75,
            monthly_payment_first=110_001.11,
            monthly_payment_last=44_002.22,
        )

        updated = self.repository.update(original.id, replacement)

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.id, original.id)
        self.assertEqual(updated.created_at, original.created_at)
        self.assertGreater(updated.updated_at, original.updated_at)
        self.assertEqual(updated.name, "Обновлённый вариант")
        self.assertEqual(updated.annual_rate_percent, 13.75)
        self.assertEqual(updated.monthly_payment_first, 110_001.11)
        self.assertEqual(updated.monthly_payment_last, 44_002.22)
        self.assertEqual(len(self.repository.list_all()), 1)
        self.assertEqual(self.repository.get_by_id(original.id), updated)

    def test_timestamps_are_stored_as_iso_8601_text(self) -> None:
        saved = self.repository.create(make_scenario_draft())
        updated = self.repository.update(saved.id, make_scenario_draft())

        with closing(connect_database(self.database_path)) as connection:
            row = connection.execute(
                "SELECT created_at, updated_at FROM scenarios WHERE id = ?",
                (saved.id,),
            ).fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIsInstance(row["created_at"], str)
        self.assertIsInstance(row["updated_at"], str)
        self.assertEqual(datetime.fromisoformat(row["created_at"]), self.start_time)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(
            datetime.fromisoformat(row["updated_at"]),
            updated.updated_at,
        )

    def test_update_unknown_id_returns_none_without_creating_record(self) -> None:
        result = self.repository.update(999, make_scenario_draft())

        self.assertIsNone(result)
        self.assertEqual(self.repository.list_all(), [])


if __name__ == "__main__":
    unittest.main()
