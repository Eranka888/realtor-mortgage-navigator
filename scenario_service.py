from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from mortgage_calc import MortgageInput, MortgageInputError, calculate_mortgage
from scenario_models import MortgageScenario, ScenarioDraft


class ScenarioRepositoryProtocol(Protocol):
    def list_all(self) -> list[MortgageScenario]: ...

    def get_by_id(self, scenario_id: int) -> MortgageScenario | None: ...

    def create(self, draft: ScenarioDraft) -> MortgageScenario: ...

    def update(
        self,
        scenario_id: int,
        draft: ScenarioDraft,
    ) -> MortgageScenario | None: ...


class ScenarioServiceError(Exception):
    """Base error that can be safely handled by an application interface."""


class ScenarioValidationError(ScenarioServiceError):
    pass


class ScenarioNotFoundError(ScenarioServiceError):
    pass


class ScenarioStorageError(ScenarioServiceError):
    pass


@dataclass(frozen=True)
class ScenarioComparison:
    scenarios: tuple[MortgageScenario, ...]


class ScenarioService:
    def __init__(self, repository: ScenarioRepositoryProtocol) -> None:
        self._repository = repository

    def list_scenarios(self) -> list[MortgageScenario]:
        try:
            return self._repository.list_all()
        except Exception as error:
            raise ScenarioStorageError(
                "Не удалось получить сохраненные сценарии."
            ) from error

    def get_scenario(self, scenario_id: int) -> MortgageScenario:
        try:
            scenario = self._repository.get_by_id(scenario_id)
        except Exception as error:
            raise ScenarioStorageError(
                "Не удалось открыть сохраненный сценарий."
            ) from error

        if scenario is None:
            raise ScenarioNotFoundError("Сценарий не найден.")
        return scenario

    def save_scenario(
        self,
        name: str,
        mortgage_input: MortgageInput,
        scenario_id: int | None = None,
    ) -> MortgageScenario:
        if not name.strip():
            raise ScenarioValidationError("Введите название сценария.")

        try:
            result = calculate_mortgage(mortgage_input)
        except MortgageInputError as error:
            raise ScenarioValidationError(str(error)) from error

        draft = ScenarioDraft(
            name=name,
            property_price=mortgage_input.property_price,
            down_payment_value=mortgage_input.down_payment,
            down_payment_unit=(
                "percent" if mortgage_input.down_payment_in_percent else "rubles"
            ),
            down_payment_amount=result.down_payment_amount,
            loan_amount=result.loan_amount,
            annual_rate_percent=mortgage_input.annual_rate_percent,
            term_years=mortgage_input.term_years,
            payment_type=mortgage_input.payment_type,
            monthly_payment_first=result.monthly_payment_first,
            monthly_payment_last=result.monthly_payment_last,
            total_payment=result.total_payment,
            total_interest=result.total_interest,
        )

        try:
            if scenario_id is None:
                return self._repository.create(draft)
            saved = self._repository.update(scenario_id, draft)
        except Exception as error:
            action = "сохранить" if scenario_id is None else "обновить"
            raise ScenarioStorageError(
                f"Не удалось {action} сценарий."
            ) from error

        if saved is None:
            raise ScenarioNotFoundError("Сценарий не найден.")
        return saved

    def compare_scenarios(
        self,
        scenario_ids: Sequence[int],
    ) -> ScenarioComparison:
        selected_ids = tuple(scenario_ids)
        if not 2 <= len(selected_ids) <= 3:
            raise ScenarioValidationError(
                "Для сравнения выберите 2–3 разных сценария."
            )
        if len(set(selected_ids)) != len(selected_ids):
            raise ScenarioValidationError(
                "Для сравнения выберите 2–3 разных сценария."
            )

        return ScenarioComparison(
            scenarios=tuple(
                self.get_scenario(scenario_id) for scenario_id in selected_ids
            )
        )
