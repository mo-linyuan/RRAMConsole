"""Large-list edits preserve state; pacing/progress don't churn the whole UI."""
from pathlib import Path
import tempfile
import json
import time
import unittest
from unittest.mock import patch

from tests.test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "没有图形环境")
class ResponsivenessTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        import i1003.ui.app as A
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        setting = patch.object(A, "SETTINGS_FILE", str(Path(self.folder.name) / "settings.json"))
        setting.start()
        self.addCleanup(setting.stop)
        self.root = tk.Tk()
        self.app = A.App(self.root)
        self.root.geometry("1200x800+30000+30000")
        self.root.update()
        self.app.surface.flush()
        self.root.update()
        self.addCleanup(self.root.destroy)

    def test_large_list_yields_to_input_and_finishes_in_order(self):
        from i1003.model.items import FpgaItem
        app = self.app
        app.seq.set_items([FpgaItem(addr=2, desc="row {}".format(i)) for i in range(5000)])
        self.assertTrue(app.seq.rendering)
        self.assertLess(len(app.seq.tv.get_children()), 5000)
        self.assertTrue(app.seq.btn_run.instate(["disabled"]))
        self.assertFalse(app.seq.btn_clear.instate(["disabled"]))
        inputs = []
        self.root.after(0, lambda: inputs.append(app.seq.rendering))
        app.seq.set_state(4000, "已发送")
        deadline = time.monotonic() + 6
        while app.seq.rendering and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.001)
        self.assertEqual(inputs, [True])
        self.assertFalse(app.seq.rendering)
        self.assertEqual(app.seq.tv.get_children(), tuple(str(i) for i in range(5000)))
        self.assertEqual(app.seq.tv.item("4000", "values")[3], "已发送")
        self.assertEqual(app.seq.tv.item("4999", "values")[1], "row 4999")
        self.assertFalse(app.seq.btn_run.instate(["disabled"]))

    def test_replace_or_clear_cancels_unfinished_list_paint(self):
        from i1003.model.items import FpgaItem
        seq = self.app.seq
        seq.set_items([FpgaItem(addr=2) for _ in range(5000)])
        job = seq._render_job
        seq.set_items([FpgaItem(addr=1, desc="new")])
        self.assertFalse(seq.rendering)
        self.assertNotIn(job, self.root.tk.call("after", "info"))
        self.root.update()
        self.assertEqual(seq.tv.get_children(), ("0",))
        self.assertEqual(seq.tv.item("0", "values")[1], "new")
        seq.set_items([FpgaItem(addr=2) for _ in range(5000)])
        seq.clear()
        self.root.update()
        self.assertFalse(seq.rendering)
        self.assertEqual(seq.tv.get_children(), ())

    def test_large_loaded_sequence_can_start_before_status_repaint(self):
        from i1003.model.items import FpgaItem
        seq = self.app.seq
        seq.set_items([FpgaItem(addr=2) for _ in range(1600)])
        deadline = time.monotonic() + 6
        while seq.rendering and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.001)
        self.assertFalse(seq.rendering)
        admitted = []
        def start(items, rows):
            admitted.append((len(items), seq.rendering))
            seq.set_busy(True)
            return True
        with patch.object(self.app, "run", side_effect=start):
            seq.run(False)
        self.assertEqual(admitted, [(1600, False)])
        self.assertTrue(seq.rendering)
        self.assertTrue(seq.btn_run.instate(["disabled"]))

    def test_large_receive_keeps_full_archive_but_small_preview(self):
        from rram_console.run_record import RunRecord
        record = RunRecord({"simulation": True}, self.folder.name)
        app = self.app
        app._record = record
        payload = bytes(range(256)) * 200
        app._on_receive("unmatched", payload)
        log = app.q.get_nowait()
        self.assertLess(len(log[3]), 1000)
        self.assertIn(str(len(payload)), log[3])
        app._record_event("finished", ok=True)
        rows = [json.loads(line) for line in record.path.read_text(encoding="utf-8").splitlines()]
        received = next(row for row in rows if row["event"] == "rx")
        self.assertEqual(bytes.fromhex(received["hex"]), payload)

    def test_oversized_log_lines_are_bounded_per_ui_batch(self):
        app = self.app
        self.root.after_cancel(app._pump_job)
        for _ in range(100):
            app.log("info", "test", "x" * 100000)
        app._pump()
        self.assertGreater(app.q.qsize(), 0)
        visible = app.logp.text.get("1.0", "end")
        self.assertLess(len(visible), 50000)
        self.assertIn("长报文仅显示预览", visible)

    def test_log_only_writes_file_after_manual_save_and_cancel_is_noop(self):
        panel = self.app.logp
        destination = Path(self.folder.name) / "manual-log.txt"
        panel.append("info", "提示", "仅手动保存", "12:34:56.789")
        self.assertFalse(destination.exists())
        with patch("i1003.ui.panels.log_panel.filedialog.asksaveasfilename", return_value=""):
            panel.save()
        self.assertFalse(destination.exists())
        with patch("i1003.ui.panels.log_panel.filedialog.asksaveasfilename", return_value=str(destination)):
            panel.save()
        self.assertIn("12:34:56.789  提示  仅手动保存", destination.read_text(encoding="utf-8"))
        panel.clear()
        self.assertEqual(panel.text.get("1.0", "end").strip(), "")
        self.assertIn("仅手动保存", destination.read_text(encoding="utf-8"))

    def test_pacing_edits_preserve_large_sequence_selection_and_scroll(self):
        from i1003.model.items import FpgaItem
        app = self.app
        app.seq.set_items([FpgaItem(addr=2, desc=str(index)) for index in range(1000)])
        self.root.update()
        app.seq.tv.selection_set("700")
        app.seq.tv.see("700")
        self.root.update()
        previous = app.seq.tv.yview()
        with patch.object(app.seq, "refresh", side_effect=AssertionError("pacing must not rebuild packets")), \
                patch.object(app.templates, "update_preview", side_effect=AssertionError("packet bytes unchanged")):
            app.route_bar.vars["gap"].set("1")
            app.route_bar.vars["download_gap"].set("2")
        self.assertEqual(app.seq.selected(), [700])
        self.assertEqual(app.seq.tv.yview(), previous)
        self.assertIn("写入等待预算 4.000 ms", app.quick.time_description.get())

    def test_incremental_row_edits_keep_order_data_and_refresh_failure_tags(self):
        from i1003.model.items import PkgItem
        app = self.app
        items = [PkgItem(desc=str(index), type=0, addr=8) for index in range(200)]
        app.seq.set_items(items)
        self.root.update()
        app.seq.tv.selection_set("150")
        app.seq.tv.see("150")
        self.root.update()
        scroll = app.seq.tv.yview()
        tricky = '[set ::rram_ui_injected 1]; {literal} $value "quote"'
        app.seq.replace_selected(PkgItem(desc=tricky, type=0, addr=8))
        self.assertEqual(app.seq.tv.item("150", "values")[1], tricky)
        self.assertFalse(self.root.tk.call("info", "exists", "::rram_ui_injected"))
        self.assertEqual(app.seq.selected(), [150])
        self.assertEqual(app.seq.tv.yview(), scroll)
        app.seq.move(-1)
        self.assertEqual(app.seq.items[149].desc, tricky)
        self.assertEqual(app.seq.tv.item("149", "values")[1], tricky)
        app.seq.add(PkgItem(desc="inserted", type=0, addr=8))
        self.assertEqual(app.seq.items[150].desc, "inserted")
        self.assertEqual(len(app.seq.tv.get_children()), 201)
        app.seq.delete()
        self.assertEqual(len(app.seq.tv.get_children()), 200)
        self.assertEqual(app.seq.items[149].desc, tricky)
        app.seq.set_state(0, "失败")
        app.seq.states[0] = ""
        app.seq.refresh()
        self.assertNotIn("failed", app.seq.tv.item("0", "tags"))
        app.route_bar.vars["core"].set("11")
        app.on_route_changed()
        self.assertIn("00 C5", app.seq.tv.item("0", "values")[2])

    def test_progress_burst_is_coalesced_without_overwriting_final_result(self):
        from i1003.engine.runner import RunResult
        app = self.app
        app.root.after_cancel(app._pump_job)
        for index in range(100):
            app.control_q.put(("progress", index, 100))
        app.control_q.put(("result", RunResult("sent", 100, 100, 1, "报文已发送")))
        app.control_q.put(("finished", True))
        with patch.object(app.seq, "set_progress", wraps=app.seq.set_progress) as progress:
            app._pump()
            progress.assert_called_once_with(99, 100)
        self.assertIn("报文已发送", app.seq.result_text.get())
        self.assertNotIn("运行中", app.seq.result_text.get())
