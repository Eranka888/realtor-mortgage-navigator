import os
import unittest
from unittest.mock import patch

import app
import scenario_repository
from mortgage_calc import ANNUITY, MortgageInput
from scenario_service import ScenarioService


DEMO_NOTICE = (
    "Демонстрационный режим. Сценарии хранятся только в текущей сессии "
    "и могут исчезнуть после ее завершения. Не вводите персональные данные."
)


def make_mortgage_input() -> MortgageInput:
    return MortgageInput(
        property_price=7_000_000,
        down_payment=20,
        down_payment_in_percent=True,
        annual_rate_percent=15,
        term_years=20,
        payment_type=ANNUITY,
    )


class PublicDemoModeTests(unittest.TestCase):
    def test_public_demo_is_enabled_only_by_true_value(self) -> None:
        is_public_demo = getattr(app, "is_public_demo", None)
        self.assertTrue(callable(is_public_demo))

        for value in ("true", "TRUE", " True "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"PUBLIC_DEMO": value}, clear=False):
                    self.assertTrue(is_public_demo())

        for value in ("false", "1", "yes", ""):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"PUBLIC_DEMO": value}, clear=False):
                    self.assertFalse(is_public_demo())

    def test_local_mode_uses_sqlite_repository(self) -> None:
        sqlite_repository = object()
        with patch("app.ScenarioRepository", return_value=sqlite_repository):
            service, error_message = app.initialize_scenario_service(
                public_demo=False,
                session_state={},
            )

        self.assertIsNone(error_message)
        self.assertIsInstance(service, ScenarioService)
        assert service is not None
        self.assertIs(service._repository, sqlite_repository)

    def test_demo_mode_reuses_repository_inside_one_session(self) -> None:
        repository_class = getattr(
            scenario_repository,
            "InMemoryScenarioRepository",
            None,
        )
        self.assertIsNotNone(repository_class)
        state: dict[str, object] = {}

        first_service, first_error = app.initialize_scenario_service(
            public_demo=True,
            session_state=state,
        )
        second_service, second_error = app.initialize_scenario_service(
            public_demo=True,
            session_state=state,
        )

        self.assertIsNone(first_error)
        self.assertIsNone(second_error)
        assert first_service is not None
        assert second_service is not None
        self.assertIs(first_service._repository, second_service._repository)
        self.assertIsInstance(first_service._repository, repository_class)

    def test_independent_sessions_do_not_share_saved_scenarios_or_open_sqlite(self) -> None:
        first_state: dict[str, object] = {}
        second_state: dict[str, object] = {}

        with patch(
            "app.ScenarioRepository",
            side_effect=AssertionError("SQLite must not open in demo mode"),
        ):
            with patch.dict(os.environ, {"PUBLIC_DEMO": "true"}, clear=False):
                first_service, first_error = app.initialize_scenario_service(
                    session_state=first_state,
                )
                second_service, second_error = app.initialize_scenario_service(
                    session_state=second_state,
                )

        self.assertIsNone(first_error)
        self.assertIsNone(second_error)
        assert first_service is not None
        assert second_service is not None

        saved = first_service.save_scenario("Первый посетитель", make_mortgage_input())

        self.assertEqual(first_service.list_scenarios(), [saved])
        self.assertEqual(second_service.list_scenarios(), [])
        self.assertIsNot(first_service._repository, second_service._repository)

    def test_demo_mode_shows_session_storage_warning(self) -> None:
        render_demo_notice = getattr(app, "render_demo_notice", None)
        self.assertTrue(callable(render_demo_notice))

        with patch("app.st.info") as info:
            render_demo_notice(True)

        info.assert_called_once_with(DEMO_NOTICE)

    def test_local_mode_does_not_show_demo_warning(self) -> None:
        render_demo_notice = getattr(app, "render_demo_notice", None)
        self.assertTrue(callable(render_demo_notice))

        with patch("app.st.info") as info:
            render_demo_notice(False)

        info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
