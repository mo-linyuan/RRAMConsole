"""GUI connection mode, explicit simulation markings and run provenance."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tests.test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "没有图形环境")
class SimulatorUiTest(unittest.TestCase):
    def test_simulated_run_marks_ui_packets_results_and_record(self):
        import tkinter as tk
        import i1003.ui.app as A
        from i1003.model.items import PkgItem, VerifyItem
        from i1003.transport.simulator import PROFILES
        from rram_console.run_record import RunRecord

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(A, "SETTINGS_FILE", str(Path(directory) / "settings.json")), \
                patch.object(A, "RunRecord", lambda metadata: RunRecord(metadata, directory)):
            root = tk.Tk()
            root.withdraw()
            app = A.App(root)
            try:
                original_endpoints = app.conn.endpoints()
                app.conn.mode.set("离线模拟")
                app.conn.profile.set(next(label for label, key in PROFILES.items() if key == "readback"))
                app.conn._refresh_mode()
                self.assertTrue(all(str(entry["state"]) == "disabled" for entry in app.conn.entries))
                with patch.object(A.messagebox, "showerror") as error:
                    app._toggle_connection()
                error.assert_not_called()
                self.assertTrue(app.is_connected())
                self.assertIn("离线模拟", root.title())
                self.assertIn("离线模拟", app.conn.lbl_state["text"])
                self.assertEqual(str(app.conn.mode_combo["state"]), "disabled")
                items = [PkgItem(type=4, addr=8, data=7), VerifyItem(addr=8, expect=7)]
                app.seq.set_items(items)
                self.assertTrue(app.run(items, [0, 1], confirm=False))
                deadline = time.monotonic() + 4
                while (app.is_busy() or not app.q.empty()) and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.005)
                self.assertFalse(app.is_busy())
                self.assertIn("离线模拟", app.seq.result_text.get())
                self.assertEqual(list(Path(directory).glob("*.jsonl")), [])
                self.assertIsNone(app._record)
                self.assertIn("模拟", app.logp.text.get("1.0", "end"))
                self.assertIn("不代表实物结果", app.seq.result_text.get())
                previous_states = list(app.seq.states)
                previous_items = list(app.seq.items)
                received = app.link._simulator.received_frames
                app.templates.select("查询芯片 Ready 0002")
                app.templates._send()
                deadline = time.monotonic() + 4
                while (app.is_busy() or not app.q.empty()) and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.005)
                self.assertFalse(app.is_busy())
                self.assertGreater(app.link._simulator.received_frames, received)
                self.assertEqual(app.seq.items, previous_items)
                self.assertEqual(app.seq.states, previous_states)
                self.assertEqual(list(Path(directory).glob("*.jsonl")), [])
                simulator = app.link._simulator
                app._toggle_connection()
                self.assertFalse(simulator._thread.is_alive())
                self.assertEqual(app.conn.endpoints(), original_endpoints)
                app.conn.mode.set("真实板卡")
                app.conn._refresh_mode()
                self.assertTrue(all(str(entry["state"]) == "normal" for entry in app.conn.entries))
                self.assertNotIn("离线模拟", root.title())
            finally:
                app.runner.stop()
                app.link.close()
                root.destroy()

    def test_window_close_stops_simulator(self):
        import tkinter as tk
        import i1003.ui.app as A
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(A, "SETTINGS_FILE", str(Path(directory) / "settings.json")):
            root = tk.Tk()
            root.withdraw()
            app = A.App(root)
            try:
                app.conn.mode.set("离线模拟")
                app.conn._refresh_mode()
                app._toggle_connection()
                simulator = app.link._simulator
                root.update_idletasks()
                app._on_close()
                self.assertFalse(simulator._thread.is_alive())
                self.assertFalse(app.link.is_open)
            finally:
                app.link.close()
                if root.tk.call("info", "commands", "."):
                    root.destroy()
