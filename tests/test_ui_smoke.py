"""界面冒烟测试：没有图形环境时自动跳过。"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

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
    def test_coordinate_fields_follow_scope_and_single_edits_stay_single(self):
        from pathlib import Path
        import i1003.ui.app as A
        with tempfile.TemporaryDirectory() as folder, patch.object(A, "SETTINGS_FILE", str(Path(folder) / "settings.json")):
            root = tk.Tk()
            try:
                app = A.App(root)
                panel = app.quick
                panel.scene_display.set("单个器件")
                panel._select_scene()
                visible = lambda key: bool(panel.coordinates[key].winfo_manager())
                self.assertTrue(visible("row_from") and visible("col_from"))
                for key in ("row_to_label", "row_to", "col_to_label", "col_to"):
                    self.assertFalse(visible(key))
                panel.coordinates["row_from"].set("12")
                panel.coordinates["col_from"].set("37")
                spec = panel.spec()
                self.assertEqual((spec.row_from, spec.row_to, spec.col_from, spec.col_to), (12, 12, 37, 37))
                self.assertEqual(panel.plan().cells, 1)
                self.assertEqual(panel.scene_display.get(), "单个器件")
                panel.vars["row_to"].set("127")  # Hidden stale values cannot broaden the operation.
                panel.vars["col_to"].set("bad")
                self.assertEqual(panel.plan().cells, 1)
                panel.scene_display.set("一整行")
                panel._select_scene()
                self.assertTrue(visible("row_from"))
                self.assertFalse(visible("col_from"))
                self.assertTrue(panel.row_columns_hint.winfo_manager())
                panel.coordinates["row_from"].set("9")
                spec = panel.spec()
                self.assertEqual((spec.row_from, spec.row_to, spec.col_from, spec.col_to), (9, 9, 0, 127))
                self.assertEqual(panel.plan().cells, 128)
                panel.scene_display.set("自定义范围")
                panel._select_scene()
                self.assertTrue(all(visible(key) for key in panel.coordinates))
                panel.vars["row_to"].set("9")
                panel.vars["col_to"].set("0")
                self.assertEqual(panel.scene_display.get(), "自定义范围")
                self.assertTrue(visible("row_to"))  # Editing equal endpoints must not hide the entry mid-typing.
                panel.vars["row_to"].set("10")
                panel.vars["col_to"].set("4")
                self.assertEqual(panel.plan().cells, 10)
                app._save_settings()
                root.update_idletasks()
            finally:
                root.destroy()
            root = tk.Tk()
            try:
                app = A.App(root)
                self.assertEqual(app.quick.scene_display.get(), "自定义范围")
                self.assertEqual(app.quick.plan().cells, 10)
                root.update_idletasks()
            finally:
                root.destroy()

    def test_scope_controls_and_combined_preview_preserve_parameters(self):
        from pathlib import Path
        import i1003.ui.app as A
        from i1003.recipes import write_test as W
        from i1003.model.items import ProgItem, FpgaProbeItem
        with tempfile.TemporaryDirectory() as folder, patch.object(A, "SETTINGS_FILE", str(Path(folder) / "settings.json")):
            root = tk.Tk()
            try:
                app = A.App(root)
                app.quick.vars["op"].set(W.OP_FORMING)
                app.quick.vars["repeat"].set("7")
                app.quick.vars["wwv_base"].set("13")
                for scope, expected in (("一整行", 896), ("单个器件", 7), ("自定义范围", 14)):
                    app.quick.scene_display.set(scope)
                    app.quick._select_scene()
                    self.assertEqual(app.quick.plan().instructions, expected)
                    self.assertEqual(app.quick.spec().op, W.OP_RESET)  # Same opcode, no external-experiment alias.
                    self.assertEqual(app.quick.spec().repeat, 7)
                    self.assertEqual(app.quick.spec().wwv_base, 13)
                self.assertEqual(tuple(app.quick.scope_combo["values"]), ("单个器件", "一整行", "自定义范围"))
                for item in (ProgItem(segs=[[0x40100002, 2], [0x40100003, 3]]), FpgaProbeItem()):
                    app.templates.load(item)
                    self.assertIsNone(app.templates.cur)
                    self.assertTrue(all(button.instate(["disabled"]) for button in app.templates.actions))
                app.templates.select("写入 WRITEB 指令")
                self.assertTrue(all(not button.instate(["disabled"]) for button in app.templates.actions))
                root.update_idletasks()
            finally:
                root.destroy()

    def test_old_repeat_default_migrates_once_and_single_shot_label_tracks_edits(self):
        import json
        from pathlib import Path
        import i1003.ui.app as A
        from i1003.recipes import write_test as W
        with tempfile.TemporaryDirectory() as folder, patch.object(A, "SETTINGS_FILE", str(Path(folder) / "settings.json")):
            Path(A.SETTINGS_FILE).write_text(json.dumps({"quick.repeat": "4095", "quick.scene": "单器件只打一次",
                "_extra": {"i1003.send_only_defaults_v1": True}}), encoding="utf-8")
            root = tk.Tk()
            try:
                app = A.App(root)
                self.assertEqual(app.quick.spec().repeat, 1)
                self.assertEqual(app.quick.plan().instructions, 1)
                app.quick.vars["repeat"].set("7")
                self.assertEqual(app.quick.scene_display.get(), "单个器件")
                app.quick.scene.set("单器件只打一次")
                app.quick.apply_scene()
                self.assertEqual(app.quick.spec().repeat, 1)
                self.assertEqual(app.quick.scene_display.get(), "单个器件")
                app.templates.select("批量写指令（long_tx）")
                self.assertEqual(app.templates.lbl_name["text"], "写入 WRITEB 指令")
                app.quick.vars["repeat"].set("4095")
                app._save_settings()
                root.update_idletasks()
            finally:
                root.destroy()
            root = tk.Tk()
            try:
                app = A.App(root)
                self.assertEqual(app.quick.spec().repeat, 4095)  # Explicit choice survives migration.
                root.update_idletasks()
            finally:
                root.destroy()

    def test_old_readback_defaults_migrate_once(self):
        import json
        from pathlib import Path
        import i1003.ui.app as A
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"quick.check_reg8": True, "quick.check_inst": True,
                                        "quick.poll_after": True, "quick.after": "等待后查询结束状态",
                                        "quick.remind_4200": True, "quick.repeat": "9"}), encoding="utf-8")
            with patch.object(A, "SETTINGS_FILE", str(path)):
                root = tk.Tk()
                root.withdraw()
                try:
                    app = A.App(root)
                    spec = app.quick.spec()
                    self.assertFalse(spec.check_reg8 or spec.check_inst or spec.poll_after)
                    self.assertEqual(spec.repeat, 9)
                    self.assertTrue(app.route_bar.vars["ready"].get())
                    self.assertFalse(hasattr(app.quick, "after"))
                    for removed in ("poll_after", "check_reg8", "check_inst", "remind_4200"):
                        self.assertNotIn(removed, app.quick.vars)
                    self.assertEqual([item.kind for item in app.quick.plan().items], ["pkg", "prog", "pkg"])
                    app._save_settings()
                finally:
                    root.destroy()
                root = tk.Tk()
                root.withdraw()
                try:
                    app = A.App(root)
                    self.assertFalse(app.quick.spec().check_reg8)
                    self.assertFalse(app.quick.spec().poll_after)
                    self.assertFalse(app.quick.spec().remind_4200)
                finally:
                    root.destroy()

    def test_offline_run_records_and_locks_sequence(self):
        import json
        import time
        from pathlib import Path
        import i1003.ui.app as A
        from i1003.model.items import PkgItem, VerifyItem, WaitItem
        from rram_console.run_record import RunRecord
        from tests.test_execution_safety import peer, reply_to
        from i1003.protocol import fpga
        from i1003.protocol.pkg import Pkg

        registers = {}
        def respond(data):
            write, addr, payload = fpga.parse_frame(data)
            if not write:
                return [bytes(7) + b"\x01"]
            pkg = Pkg.decode(payload)
            if pkg.type == 4:
                registers[pkg.addr] = pkg.data
                return []
            return [reply_to(data, data=registers.get(pkg.addr, 0))]

        with tempfile.TemporaryDirectory() as directory, peer(respond) as (unused, _, _, server):
            with patch.object(A, "SETTINGS_FILE", str(Path(directory) / "settings.json")), \
                    patch.object(A, "RunRecord", lambda metadata: RunRecord(metadata, directory)):
                root = tk.Tk()
                root.withdraw()
                app = A.App(root)
                try:
                    app.conn.vars["lip"].set("127.0.0.1")
                    app.conn.vars["lport"].set("0")
                    app.conn.vars["rip"].set("127.0.0.1")
                    app.conn.vars["rport"].set(str(server.getsockname()[1]))
                    app._toggle_connection()
                    items = [PkgItem(type=4, addr=8, data=7), VerifyItem(addr=8, expect=7), WaitItem(ms=50)]
                    app.seq.set_items(items)
                    self.assertTrue(app.run(items, [0, 1, 2], confirm=False))
                    app.seq.add(WaitItem(ms=99))
                    app.seq.tv.selection_set("0")
                    app.seq.delete()
                    app.seq.move(1)
                    self.assertEqual(app.seq.items, items)
                    self.assertEqual(str(app.seq.btn_run["state"]), "disabled")
                    self.assertTrue(all(str(entry["state"]) == "disabled" for entry in app.conn.entries))
                    self.assertTrue(all(str(widget["state"]) == "disabled" for widget in app.route_bar.frame.winfo_children()
                                        if isinstance(widget, (A.ttk.Entry, A.ttk.Checkbutton))))
                    deadline = time.monotonic() + 3
                    while (app.is_busy() or not app.q.empty()) and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.005)
                    self.assertFalse(app.is_busy())
                    self.assertIn("核对通过", app.seq.result_text.get())
                    self.assertEqual(app.seq.states, ["已发送", "已核对", "已等待"])
                    self.assertEqual(list(Path(directory).glob("*.jsonl")), [])
                    self.assertIsNone(app._record)
                    self.assertEqual(str(app.route_bar.frame.winfo_children()[1]["state"]), "readonly")
                finally:
                    app.runner.stop()
                    app.link.close()
                    root.destroy()

    def test_family_switch_preserves_each_configuration(self):
        import i1003.ui.app as A
        from rram_console.chips import ChipFamily, _families, register_family
        from rram_console.chips.i1003 import I1003Backend

        # Test-only stand-in exercises backend dispatch; it is never exposed in production.
        class TestBackend(I1003Backend):
            settings_prefix = "test-family."

        with tempfile.TemporaryDirectory() as folder, patch.dict(_families):
            register_family(ChipFamily("test-family", "测试系列", TestBackend))
            previous = A.SETTINGS_FILE
            A.SETTINGS_FILE = os.path.join(folder, "settings.json")
            root = tk.Tk()
            try:
                app = A.App(root)
                root.update()
                app.quick.vars["repeat"].set("7")
                app._switch_family("test-family")
                self.assertEqual(app.chip_family_id(), "test-family")
                app.quick.vars["repeat"].set("3")
                app._switch_family("i1003")
                self.assertEqual(app.quick.vars["repeat"].get(), "7")
                app._switch_family("test-family")
                self.assertEqual(app.quick.vars["repeat"].get(), "3")
                with self.assertRaises(ValueError):
                    app.apply_header({})  # Legacy untagged sequences belong to I1003.
                root.update()
            finally:
                root.destroy()
                A.SETTINGS_FILE = previous

    def test_build_and_plan(self):
        import i1003.ui.app as A
        A.SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "_tmp_settings.json")
        root = tk.Tk()
        try:
            app = A.App(root)
            self.assertEqual(root.title(), "RRAM芯片控制台")
            self.assertEqual(app.chip_family_id(), "i1003")
            self.assertEqual(app.chip_selector.selected.get(), "I1003 系列")
            self.assertEqual(app.quick.plan().wwv.word, 0x00FF00FE)
            app.quick.vars["repeat"].set("100")
            self.assertEqual(app.quick.total_time_text.get(), "647.700 ms")
            self.assertIn("写入等待预算 0.000 µs", app.quick.time_description.get())
            app.route_bar.vars["download_gap"].set("20")
            self.assertIn("写入等待预算 2.020000 s", app.quick.time_description.get())
            app.route_bar.vars["gap"].set("1")
            self.assertIn("写入等待预算 2.020000 s", app.quick.time_description.get())
            app.route_bar.vars["download_gap"].set("1")
            self.assertIn("写入等待预算 101.000 ms", app.quick.time_description.get())
            self.assertEqual(app.quick.total_time_text.get(), "647.700 ms")
            app.route_bar.vars["gap"].set("bad")
            self.assertEqual(app.quick.total_time_text.get(), "—")
            with self.assertRaises(ValueError):
                app.route_bar.options()
            app.route_bar.vars["gap"].set("20")
            app.quick.vars["col_to"].set("3")
            self.assertEqual(app.quick.total_time_text.get(), "1.295400 s")
            app.quick.vars["col_to"].set("2")
            app.quick.vars["repeat"].set("")
            self.assertEqual(app.quick.total_time_text.get(), "—")
            app.quick.vars["wwv_base"].set("13")
            app.quick.vars["wwv_times"].set("17")
            app.quick.vars["repeat"].set("2")
            self.assertEqual(app.quick.plan().items[0].data, 0x0011000D)
            self.assertEqual(app.quick.plan().instructions, 2)
            self.assertEqual(app.quick.total_time_text.get(), "44.200 µs")
            app.quick.vars["repeat"].set("7")
            for name in ("单器件长时间（I1000 实验台：4095 次）", "Forming 单器件（反向，4095 次）"):
                app.quick.scene.set(name)
                app.quick.apply_scene()
                self.assertEqual(app.quick.plan().instructions, 7)
            app.quick.scene.set("一行遍历 128 个器件（I1000 traversal）")
            app.quick.apply_scene()
            p = app.quick.plan()
            self.assertEqual(p.instructions, 128)
            app.seq.set_items(p.items)
            self.assertEqual(len(app.seq.tv.get_children()), len(p.items))
            for name in ("写 WRITEB 指令", "批量写指令（long_tx）", "原始 HEX", "boot_mode 0004"):
                app.templates.select(name)
                app.templates.build()
            app.templates.select("写 WRITEB 指令", {"dev": "3FFF"})
            self.assertEqual(app.templates.vars["row"].get(), "127")
            self.assertEqual(app.templates.vars["col"].get(), "127")
            self.assertEqual(app.templates.build().segs[0][0] & 0xFFFF, 0x3FFF)
            app.templates.vars["row"].set("128")
            with self.assertRaises(ValueError):
                app.templates.build()
            root.update()
        finally:
            root.destroy()
            if os.path.exists(A.SETTINGS_FILE):
                os.remove(A.SETTINGS_FILE)


if __name__ == "__main__":
    unittest.main()
