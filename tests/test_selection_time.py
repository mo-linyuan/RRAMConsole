"""Selection time is the sum of configured pulses, separate from runtime estimates."""

import unittest

from i1003.recipes.write_test import WriteTestSpec, plan
from i1003.ui.panels.quick_panel import duration_text


class SelectionTimeTest(unittest.TestCase):
    def test_download_interval_is_separate_from_selection_time(self):
        result = plan(WriteTestSpec(repeat=4095, wwv_base=254, wwv_times=255))
        self.assertAlmostEqual(result.nominal_selection_s, 26.523315)
        self.assertAlmostEqual(result.download_gap_budget_s(.02), 81.92)
        self.assertEqual(result.download_gap_budget_s(0), 0)
        self.assertAlmostEqual(result.download_gap_budget_s(.001), 4.096)

    def test_download_includes_stop_and_all_cells(self):
        result = plan(WriteTestSpec(repeat=2, col_from=0, col_to=3))
        self.assertAlmostEqual(result.download_gap_budget_s(.02), 9 * .02)
        for gap in (-.01, float("nan"), float("inf")):
            with self.subTest(gap=gap), self.assertRaises(ValueError):
                result.download_gap_budget_s(gap)

    def test_one_cell_repeated_pulses(self):
        result = plan(WriteTestSpec(repeat=100, wwv_base=254, wwv_times=255))
        self.assertAlmostEqual(result.nominal_selection_s, .6477)
        self.assertAlmostEqual(result.per_cell_selection_s, .6477)

    def test_total_includes_all_selected_cells(self):
        result = plan(WriteTestSpec(repeat=100, col_from=0, col_to=3, wwv_base=254, wwv_times=255))
        self.assertAlmostEqual(result.nominal_selection_s, 2.5908)
        self.assertAlmostEqual(result.per_cell_selection_s, .6477)

    def test_unverified_retry_timing_is_not_reported_as_on_time(self):
        result = plan(WriteTestSpec(repeat=100, wwv_base=254, wwv_times=255, verify_times=2))
        self.assertAlmostEqual(result.nominal_selection_s, .6477)
        self.assertGreater(result.est_s, result.nominal_selection_s)

    def test_smallest_pulse_does_not_round_to_zero(self):
        result = plan(WriteTestSpec(repeat=1, wwv_base=1, wwv_times=1))
        self.assertEqual(duration_text(result.nominal_selection_s), "0.100 µs")


if __name__ == "__main__":
    unittest.main()
