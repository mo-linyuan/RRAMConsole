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
    def test_old_readback_defaults_migrate_once(self):
        import json
        from pathlib import Path
        import i1003.ui.app as A
        from i1003.ui.panels.quick_panel import AFTER
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"quick.check_reg8": True, "quick.check_inst": True,
                                        "quick.poll_after": True, "quick.after": AFTER[0], "quick.repeat": "9"}), encoding="utf-8")
            with patch.object(A, "SETTINGS_FILE", str(path)):
                root = tk.Tk()
                root.withdraw()
                try:
                    app = A.App(root)
                    spec = app.quick.spec()
                    self.assertFalse(spec.check_reg8 or spec.check_inst or spec.poll_after)
                    self.assertEqual(spec.repeat, 9)
                    self.assertTrue(app.route_bar.vars["ready"].get())
                    app.quick.vars["check_reg8"].set(True)
                    app.quick.after.set(AFTER[0])
                    app._save_settings()
                finally:
                    root.destroy()
                root = tk.Tk()
                root.withdraw()
                try:
                    app = A.App(root)
                    self.assertTrue(app.quick.spec().check_reg8)
                    self.assertTrue(app.quick.spec().poll_after)
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
                    rows = [json.loads(line) for line in next(Path(directory).glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(rows[0]["chip_family"], "i1003")
                    self.assertEqual(len(rows[0]["sequence"]), 3)
                    self.assertTrue(any(row["event"] == "rx" for row in rows))
                    self.assertTrue(any(row["event"] == "tx" for row in rows))
                    self.assertEqual(rows[-1]["event"], "finished")
                    self.assertTrue(rows[-1]["ok"])
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
            self.assertEqual(app.templates.build().data & 0xFFFF, 0x3FFF)
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
