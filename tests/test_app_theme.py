import unittest

import plotly.graph_objects as go

from app import apply_plotly_theme


class PlotlyThemeTests(unittest.TestCase):
    def test_dark_theme_sets_a_dark_plotly_layout(self) -> None:
        figure = go.Figure()

        apply_plotly_theme([figure], is_dark=True)

        self.assertEqual(figure.layout.paper_bgcolor, "#0e1117")
        self.assertEqual(figure.layout.plot_bgcolor, "#161b24")
        self.assertEqual(figure.layout.font.color, "#fafafa")

    def test_light_theme_sets_a_light_plotly_layout(self) -> None:
        figure = go.Figure()

        apply_plotly_theme([figure], is_dark=False)

        self.assertEqual(figure.layout.paper_bgcolor, "#ffffff")
        self.assertEqual(figure.layout.plot_bgcolor, "#f0f4f8")
        self.assertEqual(figure.layout.font.color, "#20232a")


if __name__ == "__main__":
    unittest.main()
