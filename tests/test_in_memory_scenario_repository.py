import unittest
from datetime import datetime, timedelta, timezone

import scenario_repository
from scenario_models import MortgageScenario, ScenarioDraft


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
        "monthly_payment_last": 74_123.45,
        "total_payment": 17_789_628.12,
        "total_interest": 12_189_627.92,
    }
    values.update(overrides)
    return ScenarioDraft(**values)


def make_repository(clock: IncrementingClock):
    repository_class = getattr(
        scenario_repository,
        "InMemoryScenarioRepository",
        None,
    )
    if repository_class is None:
        raise AssertionError("InMemoryScenarioRepository is not implemented")
    return repository_class(clock=clock)


class InMemoryScenarioRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start_time = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
        self.repository = make_repository(IncrementingClock(self.start_time))

    def test_create_and_read_scenario(self) -> None:
        saved = self.repository.create(make_scenario_draft())

        self.assertIsInstance(saved, MortgageScenario)
        self.assertEqual(saved.id, 1)
        self.assertEqual(saved.created_at, self.start_time)
        self.assertEqual(self.repository.get_by_id(saved.id), saved)
        self.assertEqual(self.repository.list_all(), [saved])

    def test_separate_repository_instances_do_not_share_scenarios(self) -> None:
        self.repository.create(make_scenario_draft())
        other = make_repository(IncrementingClock(self.start_time))

        self.assertEqual(other.list_all(), [])

    def test_update_keeps_id_and_does_not_create_duplicate(self) -> None:
        saved = self.repository.create(make_scenario_draft(name="Первый вариант"))

        updated = self.repository.update(
            saved.id,
            make_scenario_draft(name="Обновлённый вариант", annual_rate_percent=12.5),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.id, saved.id)
        self.assertEqual(updated.created_at, saved.created_at)
        self.assertGreater(updated.updated_at, saved.updated_at)
        self.assertEqual(updated.name, "Обновлённый вариант")
        self.assertEqual(updated.annual_rate_percent, 12.5)
        self.assertEqual(self.repository.list_all(), [updated])


if __name__ == "__main__":
    unittest.main()
