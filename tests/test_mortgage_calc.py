import unittest

from mortgage_calc import (
    ANNUITY,
    DIFFERENTIATED,
    MortgageInput,
    MortgageInputError,
    calculate_mortgage,
)


def make_input(**overrides: object) -> MortgageInput:
    values = {
        "property_price": 1_200_000,
        "down_payment": 0,
        "down_payment_in_percent": False,
        "annual_rate_percent": 12,
        "term_years": 1,
        "payment_type": ANNUITY,
    }
    values.update(overrides)
    return MortgageInput(**values)


class MortgageCalculationTests(unittest.TestCase):
    def test_annuity_calculation_matches_known_result(self) -> None:
        result = calculate_mortgage(make_input(payment_type=ANNUITY))

        self.assertEqual(result.loan_amount, 1_200_000)
        self.assertEqual(result.monthly_payment_first, 106_618.55)
        self.assertEqual(result.monthly_payment_last, 106_618.55)
        self.assertEqual(result.total_payment, 1_279_422.56)
        self.assertEqual(result.total_interest, 79_422.56)

    def test_differentiated_calculation_matches_known_result(self) -> None:
        result = calculate_mortgage(make_input(payment_type=DIFFERENTIATED))

        self.assertEqual(result.loan_amount, 1_200_000)
        self.assertEqual(result.monthly_payment_first, 112_000.00)
        self.assertEqual(result.monthly_payment_last, 101_000.00)
        self.assertEqual(result.total_payment, 1_278_000.00)
        self.assertEqual(result.total_interest, 78_000.00)

    def test_reported_payments_match_schedule_endpoints(self) -> None:
        for payment_type in (ANNUITY, DIFFERENTIATED):
            with self.subTest(payment_type=payment_type):
                result = calculate_mortgage(make_input(payment_type=payment_type))

                self.assertEqual(
                    result.monthly_payment_first,
                    float(result.schedule["Платёж"].iloc[0]),
                )
                self.assertEqual(
                    result.monthly_payment_last,
                    float(result.schedule["Платёж"].iloc[-1]),
                )

    def test_totals_match_rounded_schedule_sums(self) -> None:
        for payment_type in (ANNUITY, DIFFERENTIATED):
            with self.subTest(payment_type=payment_type):
                result = calculate_mortgage(make_input(payment_type=payment_type))

                self.assertEqual(
                    result.total_payment,
                    round(float(result.schedule["Платёж"].sum()), 2),
                )
                self.assertEqual(
                    result.total_interest,
                    round(float(result.schedule["Проценты"].sum()), 2),
                )
                self.assertEqual(
                    result.total_payment,
                    round(result.loan_amount + result.total_interest, 2),
                )


class MortgageInputValidationTests(unittest.TestCase):
    def assert_invalid(self, **overrides: object) -> None:
        with self.assertRaises(MortgageInputError):
            calculate_mortgage(make_input(**overrides))

    def test_rejects_non_positive_property_price(self) -> None:
        for property_price in (0, -1):
            with self.subTest(property_price=property_price):
                self.assert_invalid(property_price=property_price)

    def test_rejects_negative_down_payment(self) -> None:
        self.assert_invalid(down_payment=-1)

    def test_rejects_down_payment_equal_to_or_above_property_price(self) -> None:
        for down_payment in (1_200_000, 1_200_001):
            with self.subTest(down_payment=down_payment):
                self.assert_invalid(down_payment=down_payment)

    def test_rejects_percent_down_payment_at_or_above_one_hundred(self) -> None:
        for down_payment in (100, 101):
            with self.subTest(down_payment=down_payment):
                self.assert_invalid(
                    down_payment=down_payment,
                    down_payment_in_percent=True,
                )

    def test_rejects_rate_outside_supported_range(self) -> None:
        for annual_rate_percent in (0, -0.01, 100.01):
            with self.subTest(annual_rate_percent=annual_rate_percent):
                self.assert_invalid(annual_rate_percent=annual_rate_percent)

    def test_accepts_rate_at_upper_boundary(self) -> None:
        result = calculate_mortgage(make_input(annual_rate_percent=100))

        self.assertEqual(len(result.schedule), 12)

    def test_rejects_term_outside_supported_range(self) -> None:
        for term_years in (0, -1, 41):
            with self.subTest(term_years=term_years):
                self.assert_invalid(term_years=term_years)

    def test_accepts_term_at_upper_boundary(self) -> None:
        result = calculate_mortgage(make_input(term_years=40))

        self.assertEqual(len(result.schedule), 480)

    def test_rejects_unknown_payment_type(self) -> None:
        self.assert_invalid(payment_type="unknown")


class MortgageScheduleRoundingTests(unittest.TestCase):
    def test_principal_sum_matches_loan_amount_to_the_kopeck(self) -> None:
        for payment_type in (ANNUITY, DIFFERENTIATED):
            with self.subTest(payment_type=payment_type):
                result = calculate_mortgage(
                    MortgageInput(
                        property_price=1_000_000,
                        down_payment=0,
                        down_payment_in_percent=False,
                        annual_rate_percent=12,
                        term_years=1,
                        payment_type=payment_type,
                    )
                )

                principal_total = result.schedule["Основной долг"].sum()

                self.assertEqual(round(float(principal_total), 2), result.loan_amount)
                self.assertEqual(result.schedule["Остаток долга"].iloc[-1], 0)

    def test_percent_down_payment_produces_a_loan_amount_in_kopecks(self) -> None:
        result = calculate_mortgage(
            MortgageInput(
                property_price=1_000_000.01,
                down_payment=20,
                down_payment_in_percent=True,
                annual_rate_percent=12,
                term_years=1,
                payment_type=ANNUITY,
            )
        )

        self.assertEqual(result.loan_amount, 800_000.01)
        self.assertEqual(
            round(float(result.schedule["Основной долг"].sum()), 2),
            result.loan_amount,
        )

    def test_schedule_money_values_are_rounded_to_kopecks(self) -> None:
        money_columns = ("Платёж", "Основной долг", "Проценты", "Остаток долга")

        for payment_type in (ANNUITY, DIFFERENTIATED):
            with self.subTest(payment_type=payment_type):
                result = calculate_mortgage(
                    MortgageInput(
                        property_price=1_000_000.01,
                        down_payment=123_456.78,
                        down_payment_in_percent=False,
                        annual_rate_percent=17.35,
                        term_years=7,
                        payment_type=payment_type,
                    )
                )

                for column in money_columns:
                    with self.subTest(payment_type=payment_type, column=column):
                        self.assertTrue(
                            all(
                                float(value) == round(float(value), 2)
                                for value in result.schedule[column]
                            )
                        )

                for total in (result.total_payment, result.total_interest):
                    self.assertEqual(total, round(total, 2))


if __name__ == "__main__":
    unittest.main()
