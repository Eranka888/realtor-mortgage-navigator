from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


DEFAULT_DATABASE_PATH = Path("data") / "scenarios.db"

_CREATE_SCENARIOS_TABLE = """
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    property_price REAL NOT NULL,
    down_payment_value REAL NOT NULL,
    down_payment_unit TEXT NOT NULL,
    down_payment_amount REAL NOT NULL,
    loan_amount REAL NOT NULL,
    annual_rate_percent REAL NOT NULL,
    term_years INTEGER NOT NULL,
    payment_type TEXT NOT NULL,
    monthly_payment_first REAL NOT NULL,
    monthly_payment_last REAL NOT NULL,
    total_payment REAL NOT NULL,
    total_interest REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def connect_database(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> None:
    with closing(connect_database(database_path)) as connection:
        with connection:
            connection.execute(_CREATE_SCENARIOS_TABLE)
