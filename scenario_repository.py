from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from database import DEFAULT_DATABASE_PATH, connect_database, initialize_database
from scenario_models import MortgageScenario, ScenarioDraft


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScenarioRepository:
    def __init__(
        self,
        database_path: str | Path = DEFAULT_DATABASE_PATH,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.database_path = Path(database_path)
        self._clock = clock
        initialize_database(self.database_path)

    def create(self, draft: ScenarioDraft) -> MortgageScenario:
        timestamp = self._clock().isoformat()

        with closing(connect_database(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
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
                    (*_draft_values(draft), timestamp, timestamp),
                )
                scenario_id = cursor.lastrowid

        if scenario_id is None:
            raise RuntimeError("SQLite did not assign an id to the scenario")

        scenario = self.get_by_id(scenario_id)
        if scenario is None:
            raise RuntimeError("Saved scenario could not be read back")
        return scenario

    def get_by_id(self, scenario_id: int) -> MortgageScenario | None:
        with closing(connect_database(self.database_path)) as connection:
            row = connection.execute(
                "SELECT * FROM scenarios WHERE id = ?",
                (scenario_id,),
            ).fetchone()

        return _row_to_scenario(row) if row is not None else None

    def list_all(self) -> list[MortgageScenario]:
        with closing(connect_database(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT * FROM scenarios ORDER BY id ASC"
            ).fetchall()

        return [_row_to_scenario(row) for row in rows]

    def update(
        self,
        scenario_id: int,
        draft: ScenarioDraft,
    ) -> MortgageScenario | None:
        with closing(connect_database(self.database_path)) as connection:
            with connection:
                existing_row = connection.execute(
                    "SELECT updated_at FROM scenarios WHERE id = ?",
                    (scenario_id,),
                ).fetchone()
                if existing_row is None:
                    return None

                previous_updated_at = datetime.fromisoformat(
                    existing_row["updated_at"]
                )
                updated_at = self._clock()
                if updated_at <= previous_updated_at:
                    updated_at = previous_updated_at + timedelta(microseconds=1)

                connection.execute(
                    """
                    UPDATE scenarios SET
                        name = ?,
                        property_price = ?,
                        down_payment_value = ?,
                        down_payment_unit = ?,
                        down_payment_amount = ?,
                        loan_amount = ?,
                        annual_rate_percent = ?,
                        term_years = ?,
                        payment_type = ?,
                        monthly_payment_first = ?,
                        monthly_payment_last = ?,
                        total_payment = ?,
                        total_interest = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (*_draft_values(draft), updated_at.isoformat(), scenario_id),
                )

        return self.get_by_id(scenario_id)


class InMemoryScenarioRepository:
    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._scenarios: dict[int, MortgageScenario] = {}
        self._next_id = 1

    def create(self, draft: ScenarioDraft) -> MortgageScenario:
        timestamp = self._clock()
        scenario = _scenario_from_draft(
            draft,
            scenario_id=self._next_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._scenarios[scenario.id] = scenario
        self._next_id += 1
        return scenario

    def get_by_id(self, scenario_id: int) -> MortgageScenario | None:
        return self._scenarios.get(scenario_id)

    def list_all(self) -> list[MortgageScenario]:
        return [self._scenarios[scenario_id] for scenario_id in sorted(self._scenarios)]

    def update(
        self,
        scenario_id: int,
        draft: ScenarioDraft,
    ) -> MortgageScenario | None:
        existing = self._scenarios.get(scenario_id)
        if existing is None:
            return None

        updated_at = self._clock()
        if updated_at <= existing.updated_at:
            updated_at = existing.updated_at + timedelta(microseconds=1)

        updated = _scenario_from_draft(
            draft,
            scenario_id=scenario_id,
            created_at=existing.created_at,
            updated_at=updated_at,
        )
        self._scenarios[scenario_id] = updated
        return updated


def _scenario_from_draft(
    draft: ScenarioDraft,
    scenario_id: int,
    created_at: datetime,
    updated_at: datetime,
) -> MortgageScenario:
    return MortgageScenario(
        id=scenario_id,
        name=draft.name,
        property_price=draft.property_price,
        down_payment_value=draft.down_payment_value,
        down_payment_unit=draft.down_payment_unit,
        down_payment_amount=draft.down_payment_amount,
        loan_amount=draft.loan_amount,
        annual_rate_percent=draft.annual_rate_percent,
        term_years=draft.term_years,
        payment_type=draft.payment_type,
        monthly_payment_first=draft.monthly_payment_first,
        monthly_payment_last=draft.monthly_payment_last,
        total_payment=draft.total_payment,
        total_interest=draft.total_interest,
        created_at=created_at,
        updated_at=updated_at,
    )


def _draft_values(draft: ScenarioDraft) -> tuple[object, ...]:
    return (
        draft.name,
        draft.property_price,
        draft.down_payment_value,
        draft.down_payment_unit,
        draft.down_payment_amount,
        draft.loan_amount,
        draft.annual_rate_percent,
        draft.term_years,
        draft.payment_type,
        draft.monthly_payment_first,
        draft.monthly_payment_last,
        draft.total_payment,
        draft.total_interest,
    )


def _row_to_scenario(row: sqlite3.Row) -> MortgageScenario:
    return MortgageScenario(
        id=row["id"],
        name=row["name"],
        property_price=row["property_price"],
        down_payment_value=row["down_payment_value"],
        down_payment_unit=row["down_payment_unit"],
        down_payment_amount=row["down_payment_amount"],
        loan_amount=row["loan_amount"],
        annual_rate_percent=row["annual_rate_percent"],
        term_years=row["term_years"],
        payment_type=row["payment_type"],
        monthly_payment_first=row["monthly_payment_first"],
        monthly_payment_last=row["monthly_payment_last"],
        total_payment=row["total_payment"],
        total_interest=row["total_interest"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
