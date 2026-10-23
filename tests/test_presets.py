"""Variable-repeat presets use the count the user has entered at selection time."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from i1003.model.items import ProgItem
from i1003.recipes import write_test as W
from i1003.ui.panels.sequence_panel import SequencePanel, _presets


def repeat_of(items):
    return next(item for item in items if isinstance(item, ProgItem)).segs[0][1]


class RepeatPresetTest(unittest.TestCase):
    def test_variable_presets_read_current_count_each_time(self):
        value = [7]
        presets = _presets(lambda: value[0])
        for count in (7, 13):
            value[0] = count
            for key in W.VARIABLE_REPEAT_SCENES:
                self.assertEqual(repeat_of(presets[W.SCENE_LABELS[key]]()), count)

    def test_single_and_row_presets_still_mean_one_per_cell(self):
        presets = _presets(lambda: 37)
        for key in W.SCENES:
            if key not in W.VARIABLE_REPEAT_SCENES:
                self.assertEqual(repeat_of(presets[W.SCENE_LABELS[key]]()), 1)

    def test_invalid_counts_are_rejected(self):
        key = W.SCENE_LABELS[next(iter(W.VARIABLE_REPEAT_SCENES))]
        for count in (0, -1, "not a number", 8192):
            with self.subTest(count=count), self.assertRaises(ValueError):
                _presets(lambda: count)[key]()

    def test_invalid_preset_does_not_replace_existing_sequence(self):
        ctx = SimpleNamespace(items=[object()], set_items=Mock())
        with patch("i1003.ui.panels.sequence_panel.messagebox.showerror") as show_error:
            SequencePanel._load_preset(ctx, "test", Mock(side_effect=ValueError("invalid count")))
            show_error.assert_called_once()
            ctx.set_items.assert_not_called()


if __name__ == "__main__":
    unittest.main()
