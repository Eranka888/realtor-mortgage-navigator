import subprocess
import sys
import unittest
from contextlib import closing
from dataclasses import fields
from pathlib import Path
from tempfile import NamedTemporaryFile

from database import connect_database, initialize_database
from scenario_models import MortgageScenario


EXPECTED_COLUMNS = {
    "id": "INTEGER",
    "name": "TEXT",
    "property_price": "REAL",
    "down_payment_value": "REAL",
    "down_payment_unit": "TEXT",
    "down_payment_amount": "REAL",
    "loan_amount": "REAL",
    "annual_rate_percent": "REAL",
    "term_years": "INTEGER",
    "payment_type": "TEXT",
    "monthly_payment_first": "REAL",
    "monthly_payment_last": "REAL",
    "total_payment": "REAL",
    "total_interest": "REAL",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MortgageScenarioModelTests(unittest.TestCase):
    def test_model_contains_all_required_scenario_fields(self) -> None:
        self.assertEqual(
            {field.name for field in fields(MortgageScenario)},
            set(EXPECTED_COLUMNS),
        )


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = self.create_temporary_database_path()

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

    def test_initialization_creates_database_file_and_scenarios_table(self) -> None:
        self.assertFalse(self.database_path.exists())

        initialize_database(self.database_path)

        self.assertTrue(self.database_path.is_file())
        with closing(connect_database(self.database_path)) as connection:
            table_names = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertIn("scenarios", table_names)

    def test_scenarios_table_contains_required_columns_and_types(self) -> None:
        initialize_database(self.database_path)

        with closing(connect_database(self.database_path)) as connection:
            columns = {
                row["name"]: row["type"]
                for row in connection.execute("PRAGMA table_info(scenarios)")
            }
            primary_keys = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(scenarios)")
                if row["pk"]
            }

        self.assertEqual(columns, EXPECTED_COLUMNS)
        self.assertEqual(primary_keys, {"id"})

    def test_reinitialization_preserves_existing_data_and_schema(self) -> None:
        initialize_database(self.database_path)
        with closing(connect_database(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO scenarios (
                        name,
                        property_price,
                        down_payment_value,
                        down_payment_unit,
                        down_payment_amount,
                        loan_amount,
                        annual_rate_percent,
                        term_years,
                        payment_type,
                        monthly_payment_first,
                        monthly_payment_last,
                        total_payment,
                        total_interest,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Тестовый вариант",
                        7_000_000,
                        20,
                        "percent",
                        1_400_000,
                        5_600_000,
                        15,
                        20,
                        "annuity",
                        73_731.51,
                        73_731.51,
                        17_695_562.40,
                        12_095_562.40,
                        "2026-09-21T12:00:00+03:00",
                        "2026-09-21T12:00:00+03:00",
                    ),
                )
            columns_before = tuple(
                row["name"]
                for row in connection.execute("PRAGMA table_info(scenarios)")
            )
            row_before = dict(
                connection.execute("SELECT * FROM scenarios").fetchone()
            )

        initialize_database(self.database_path)

        with closing(connect_database(self.database_path)) as connection:
            row_count = connection.execute(
                "SELECT COUNT(*) FROM scenarios"
            ).fetchone()[0]
            columns_after = tuple(
                row["name"]
                for row in connection.execute("PRAGMA table_info(scenarios)")
            )
            row_after = dict(
                connection.execute("SELECT * FROM scenarios").fetchone()
            )

        self.assertEqual(row_count, 1)
        self.assertEqual(columns_after, columns_before)
        self.assertEqual(row_after, row_before)

    def test_separate_custom_database_paths_are_independent(self) -> None:
        first_path = self.create_temporary_database_path()
        second_path = self.create_temporary_database_path()

        initialize_database(first_path)
        initialize_database(second_path)

        self.assertTrue(first_path.is_file())
        self.assertTrue(second_path.is_file())
        self.assertNotEqual(first_path, second_path)

    def test_import_does_not_create_default_database(self) -> None:
        import_check = """
from unittest.mock import patch

with patch(
    "pathlib.Path.mkdir",
    side_effect=AssertionError("database import created a directory"),
), patch(
    "sqlite3.connect",
    side_effect=AssertionError("database import opened a connection"),
):
    import database
"""

        subprocess.run(
            [sys.executable, "-B", "-c", import_check],
            cwd=PROJECT_ROOT,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
