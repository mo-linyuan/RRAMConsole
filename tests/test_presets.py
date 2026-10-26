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
    def test_default_device_operation_is_one_writeb_and_one_stop(self):
        spec = W.WriteTestSpec()
        self.assertEqual(spec.repeat, 1)
        result = W.plan(spec)
        self.assertEqual(result.instructions, 1)
        self.assertEqual(next(item for item in result.items if isinstance(item, ProgItem)).count(), 2)

    def test_visible_templates_and_summaries_do_not_include_legacy_source_names(self):
        from i1003.ui.templates import TEMPLATES, BY_NAME
        visible = list(W.SCENE_LABELS.values()) + list(W.SCENE_DESCRIPTIONS.values())
        visible.append(W.plan(W.WriteTestSpec(op=W.OP_FORMING)).summary)
        for template in TEMPLATES:
            visible.extend((template.name, template.describe(template.defaults())))
        for text in visible:
            for phrase in ("师姐", "I1000", "实验台", "long_tx", "traversal"):
                self.assertNotIn(phrase, text)
        batch = BY_NAME["批量写入指令"]
        self.assertEqual(batch.make().count(), 2)
        self.assertIs(BY_NAME["批量写指令（long_tx）"], batch)

    def test_diagnostic_menu_does_not_duplicate_write_configuration(self):
        presets = _presets()
        self.assertEqual(len(presets), 2)
        for name, factory in presets.items():
            self.assertNotIn(name, W.SCENE_LABELS.values())
            items = factory()
            self.assertFalse(any(item.is_start() for item in items))
            self.assertFalse(any(isinstance(item, ProgItem) for item in items))

    def test_invalid_preset_does_not_replace_existing_sequence(self):
        ctx = SimpleNamespace(items=[object()], set_items=Mock())
        with patch("i1003.ui.panels.sequence_panel.messagebox.showerror") as show_error:
            SequencePanel._load_preset(ctx, "test", Mock(side_effect=ValueError("invalid count")))
            show_error.assert_called_once()
            ctx.set_items.assert_not_called()


if __name__ == "__main__":
    unittest.main()
