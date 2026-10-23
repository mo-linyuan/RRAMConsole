"""界面冒烟测试：没有图形环境时自动跳过。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAS_DISPLAY = True
except Exception:  # noqa: BLE001
    HAS_DISPLAY = False


@unittest.skipUnless(HAS_DISPLAY, "没有图形环境")
class UiSmokeTest(unittest.TestCase):
    def test_build_and_plan(self):
        import i1003.ui.app as A
        A.SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "_tmp_settings.json")
        root = tk.Tk()
        try:
            app = A.App(root)
            app.quick.scene.set("一行遍历 128 个器件（I1000 traversal）")
            app.quick.apply_scene()
            p = app.quick.plan()
            self.assertEqual(p.instructions, 128)
            app.seq.set_items(p.items)
            self.assertEqual(len(app.seq.tv.get_children()), len(p.items))
            for name in ("写 WRITEB 指令", "批量写指令（long_tx）", "原始 HEX", "boot_mode 0004"):
                app.templates.select(name)
                app.templates.build()
            root.update()
        finally:
            root.destroy()
            if os.path.exists(A.SETTINGS_FILE):
                os.remove(A.SETTINGS_FILE)


if __name__ == "__main__":
    unittest.main()
