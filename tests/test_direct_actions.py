"""Routine GUI actions execute without modal confirmation dialogs."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "没有图形环境")
class DirectActionsTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        import i1003.ui.app as A
        from rram_console.run_record import RunRecord
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for target, value in [("SETTINGS_FILE", str(Path(self.directory.name) / "settings.json")),
                              ("RunRecord", lambda metadata: RunRecord(metadata, self.directory.name))]:
            mocked = patch.object(A, target, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        for name in ("askyesno", "askokcancel", "askquestion", "showinfo", "showwarning"):
            mocked = patch("tkinter.messagebox." + name, side_effect=AssertionError("unexpected modal: " + name))
            mocked.start()
            self.addCleanup(mocked.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = A.App(self.root)
        self.root.update_idletasks()
        self.addCleanup(self.root.destroy)

    def test_generate_clear_load_and_import_replace_or_append(self):
        from i1003.model.items import WaitItem, FpgaItem
        from i1003.model.sequence_io import save_json
        app = self.app
        app.seq.set_items([WaitItem(ms=12)])
        app.sequence_set([WaitItem(ms=23)])
        self.assertEqual(app.seq.items[0].ms, 23)
        app.quick.vars["repeat"].set("1")
        app.quick.to_sequence()
        self.assertGreater(len(app.seq.items), 1)
        app.seq.clear()
        self.assertEqual(app.seq.items, [])
        app.seq._load_preset("test", lambda: [WaitItem(ms=7)])
        self.assertEqual(app.seq.items[0].ms, 7)
        path = Path(self.directory.name) / "sequence.json"
        save_json(str(path), [WaitItem(ms=45)], {"chip_family": "i1003"})
        with patch("i1003.ui.panels.sequence_panel.filedialog.askopenfilename", return_value=str(path)):
            app.seq.import_()
            self.assertEqual([item.ms for item in app.seq.items], [45])
            app.seq.import_(append=True)
            self.assertEqual([item.ms for item in app.seq.items], [45, 45])
            save_json(str(path), [WaitItem(ms=26000, meta={"estimated_execution": True}), FpgaItem(addr=2)],
                      {"chip_family": "i1003"})
            app.seq.import_()
            self.assertEqual([item.kind for item in app.seq.items], ["fpga"])

    def test_real_mode_start_and_large_download_do_not_ask(self):
        from i1003.model.items import PkgItem, ProgItem
        app = self.app
        original_link = app.link
        app.link = SimpleNamespace(is_open=True, is_simulation=False, endpoints=("127.0.0.1", 1, "127.0.0.1", 2))
        items = [ProgItem(segs=[[0x40100001, 201]]), PkgItem(type=4, addr=0, data=1)]
        try:
            # Stub the worker: this tests the real-mode UI path without sending
            # hardware commands. Even legacy callers requesting confirmation
            # must no longer introduce a modal interruption.
            with patch.object(app.runner, "start", return_value=True) as start:
                self.assertTrue(app.run(items, confirm=True))
                start.assert_called_once()
            self.assertTrue(app.is_busy())
            app._record_event("finished", ok=True)
        finally:
            app.link = original_link

    def test_generation_and_queue_edits_do_not_execute_and_notifies_are_non_modal(self):
        app = self.app
        app.quick.vars["repeat"].set("1")
        with patch.object(app, "run", return_value=True) as run:
            app.quick.to_sequence()
            app.templates.select("启动核")
            app.templates._add()
            app.seq.tv.selection_set(str(len(app.seq.items)-1))
            app.templates._replace()
            run.assert_not_called()
            app.seq.run(False)
            run.assert_called_once()
        buttons = []
        def visit(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "TButton":
                    buttons.append(str(child["text"]))
                visit(child)
        visit(app.surface)
        self.assertNotIn("一键运行", buttons)
        self.assertNotIn("立即发送", buttons)
        self.assertIn("直接发送", buttons)
        self.assertIn("生成序列", buttons)
        self.root.geometry("1100x800+30000+30000")
        self.root.deiconify()
        self.root.update()
        app.surface.flush()
        self.root.update()
        self.assertLess(app.quick.generate_button.winfo_rooty(), app.quick.viewport.winfo_rooty())
        self.assertIs(app.quick.generate_button.master, app.nb)
        self.assertEqual(app.quick.generate_button.winfo_rooty(), app.nb.winfo_rooty())
        app.nb.select(app.tab_templates)
        self.root.update()
        self.assertFalse(app.quick.generate_button.winfo_manager())
        app.nb.select(0)
        self.root.update()
        self.assertEqual(app.quick.generate_button.winfo_manager(), "place")
        self.assertIn("加入序列", buttons)
        self.assertIn("运行全部", buttons)
        app.seq.clear()
        app.seq.run(False)
        app.seq.export()
        app.templates._replace()
        self.assertFalse(app.run([]))  # Not connected: log instead of dialog.
        app.q.put(("notify", "请操作4200"))
        app.root.after_cancel(app._pump_job)
        app._pump()
        self.assertEqual(app.conn.lbl_status["text"], "请操作4200")

    def test_template_direct_send_preserves_sequence_and_validates_inputs(self):
        from i1003.model.items import WaitItem
        app = self.app
        app.seq.set_items([WaitItem(ms=12)])
        app.seq.set_state(0, "已等待")
        app.templates.select("启动核")
        expected = app.templates.build()
        with patch.object(app, "run", return_value=True) as run:
            app.templates.actions[0].invoke()
            sent, rows = run.call_args.args
            self.assertEqual(sent[0].frames(app.route()), expected.frames(app.route()))
            self.assertEqual(rows, [None])
        self.assertEqual(len(app.seq.items), 1)
        self.assertEqual(app.seq.items[0].ms, 12)
        self.assertEqual(app.seq.states, ["已等待"])
        app.templates.select("原始 HEX", {"hex": "invalid"})
        with patch.object(app, "run") as run, patch("tkinter.messagebox.showerror") as error:
            app.templates._send()
            error.assert_called_once()
            run.assert_not_called()
