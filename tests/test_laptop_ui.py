"""Small-screen layout and bounded, batched log rendering."""
import os
import tempfile
import unittest
from unittest.mock import patch

from i1003.ui.display import window_size
from tests.test_ui_smoke import HAS_DISPLAY


class DisplaySizeTest(unittest.TestCase):
    def test_initial_window_and_minimum_fit_work_area(self):
        for width, height, scale in ((1366, 728, 1), (1920, 1040, 1.5), (1920, 1040, 2), (1280, 760, 1.25)):
            with self.subTest(width=width, height=height, scale=scale):
                w, h, minimum_w, minimum_h = window_size(width, height, scale)
                self.assertLess(w, width)
                self.assertLess(h + 40 * scale, height)
                self.assertLessEqual(minimum_w, w)
                self.assertLessEqual(minimum_h, h)


@unittest.skipUnless(HAS_DISPLAY, "No graphical display")
class LaptopUiTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        import i1003.ui.app as A
        self.folder = tempfile.TemporaryDirectory()
        self.settings_patch = patch.object(A, "SETTINGS_FILE", os.path.join(self.folder.name, "settings.json"))
        self.settings_patch.start()
        self.root = tk.Tk()
        self.root.tk.call("tk", "scaling", 96 / 72)
        self.app = A.App(self.root)
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.settings_patch.stop()
        self.folder.cleanup()

    def test_small_window_reflows_header_and_can_toggle_log(self):
        self.root.geometry("820x680")
        self.root.update()
        self.app._adapt_layout()
        self.root.update()
        self.assertTrue(self.app._log_visible)
        self.assertEqual(len(self.app.workspace.panes()), 2)
        self.assertTrue(self.app._header_stacked)
        self.assertGreater(self.app.connection_area.winfo_rooty(), self.app.family_area.winfo_rooty())
        self.app.quick.vars["repeat"].set("13")
        self.app._toggle_log()
        self.assertFalse(self.app._log_visible)
        self.assertEqual(len(self.app.workspace.panes()), 1)
        self.app._toggle_log()
        self.assertTrue(self.app._log_visible)
        self.assertEqual(self.app.quick.vars["repeat"].get(), "13")
        self.assertLessEqual(self.app.seq.btn_run.winfo_rooty() + self.app.seq.btn_run.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())
        self.assertGreater(self.app.seq.tv.winfo_height(), 55)

    def test_logs_stay_below_operation_and_right_sequence_on_resize(self):
        self.root.geometry("1000x680")
        self.root.update()
        self.app._adapt_layout()
        self.assertTrue(self.app._log_visible)
        self.root.geometry("1300x720")
        self.root.update()
        self.app._adapt_layout()
        self.root.update()
        self.assertTrue(self.app._log_visible)
        self.assertGreater(self.app.seq.outer.winfo_rootx(), self.app.nb.winfo_rootx())
        self.assertGreaterEqual(self.app.logp.outer.winfo_rooty(),
                                self.app.seq.outer.winfo_rooty() + self.app.seq.outer.winfo_height())
        self.assertGreater(self.app.logp.outer.winfo_width(), self.app.seq.outer.winfo_width())

    def test_layout_does_not_override_manual_sash_positions(self):
        self.app.main_split.sashpos(0, 450)
        self.app.workspace.sashpos(0, 350)
        self.root.update()
        positions = self.app.main_split.sashpos(0), self.app.workspace.sashpos(0)
        self.app._adapt_layout()
        self.root.update()
        self.assertEqual(positions, (self.app.main_split.sashpos(0), self.app.workspace.sashpos(0)))

    def test_native_sashes_handle_repeated_mouse_events_and_release(self):
        self.root.geometry("1300x850")
        self.root.update()
        self.app.nb.select(self.app.tab_templates)
        self.root.update()
        for pane in (self.app.main_split, self.app.workspace, self.app.templates.split):
            with self.subTest(orientation=pane.cget("orient"), widget=str(pane)):
                self.assertEqual(pane.winfo_class(), "Panedwindow")
                self.assertFalse(pane.bind("<ButtonPress-1>"))
                self.assertFalse(pane.bind("<B1-Motion>"))
                for delta in (35, -25, 20):
                    original = pane.sashpos(0)
                    x, y = pane.sash_coord(0)
                    if pane._vertical:
                        x, y = pane.winfo_width() // 2, y + 2
                    else:
                        x, y = x + 2, pane.winfo_height() // 2
                    pane.event_generate("<ButtonPress-1>", x=x, y=y)
                    self.root.update()
                    end_x = x if pane._vertical else x + delta
                    end_y = y + delta if pane._vertical else y
                    for step in range(1, 5):
                        pane.event_generate("<B1-Motion>", x=x + (end_x-x)*step//4,
                                            y=y + (end_y-y)*step//4, state=0x100)
                        self.root.update()
                    self.assertEqual(pane.sashpos(0), original)
                    pane.event_generate("<ButtonRelease-1>", x=end_x, y=end_y)
                    self.root.update()
                    self.assertAlmostEqual(pane.sashpos(0), original + delta, delta=2)
                    self.assertIsNone(pane.grab_current())
                    heartbeat = []
                    self.root.after_idle(lambda: heartbeat.append(True))
                    self.root.update()
                    self.assertTrue(heartbeat)

    def test_download_controls_wrap_without_clipping_and_remain_lockable(self):
        from tkinter import ttk
        bar = self.app.route_bar
        for width, inline in ((1360, True), (820, False), (1360, True)):
            self.root.geometry("{}x800".format(width))
            self.root.update()
            self.app.surface.flush()
            self.root.update()
            self.assertEqual(bar._download_inline, inline)
            self.assertLessEqual(bar.download_row.winfo_rootx() + bar.download_row.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
            for locked in (True, False):
                bar.set_locked(locked)
                for widget in bar.download_row.winfo_children():
                    if isinstance(widget, ttk.Entry):
                        self.assertEqual(str(widget["state"]), "disabled" if locked else "normal")

    def test_log_batch_uses_one_insert_and_preserves_timestamps(self):
        panel = self.app.logp
        entries = [("send", "发送", "frame-{}".format(i), "12:00:00.123") for i in range(200)]
        with patch.object(panel.text, "insert", wraps=panel.text.insert) as insert:
            panel.append_many(entries)
            insert.assert_called_once()
        content = panel.text.get("1.0", "end")
        self.assertEqual(content.count("12:00:00.123"), 200)
        self.assertIn("frame-199", content)

    def test_scrolling_up_does_not_jump_to_latest(self):
        self.app._set_log_visible(True)
        panel = self.app.logp
        self.root.update()
        panel.append_many([("info", "提示", "line-{}".format(i)) for i in range(500)])
        self.root.update()
        panel.text.yview_moveto(0)
        self.root.update()
        panel.append("info", "提示", "new line")
        self.root.update()
        self.assertLess(panel.text.yview()[0], .01)

    def test_message_pump_limits_each_batch_without_dropping_logs(self):
        self.root.after_cancel(self.app._pump_job)
        self.app._pump_job = None
        while not self.app.q.empty():
            self.app.q.get_nowait()
        for i in range(500):
            self.app.q.put(("log", "info", "提示", "queued-{}".format(i)))
        collected = []
        append = self.app.logp.append_many
        def capture(entries):
            collected.append(list(entries))
            append(entries)
        with patch.object(self.app.logp, "append_many", side_effect=capture) as batches:
            self.app._pump()
            self.assertEqual(batches.call_count, 1)
            self.assertGreater(len(collected[0]), 0)
            self.assertLessEqual(len(collected[0]), 200)
        self.assertGreaterEqual(self.app.q.qsize(), 300)
        for _ in range(10):
            if self.app.q.empty():
                break
            self.root.after_cancel(self.app._pump_job)
            self.app._pump()
        self.assertTrue(self.app.q.empty())
        self.assertIn("queued-499", self.app.logp.text.get("1.0", "end"))

    def test_high_dpi_laptop_keeps_action_buttons_accessible(self):
        import tkinter as tk
        import i1003.ui.app as A
        self.root.destroy()
        self.root = tk.Tk()
        self.root.tk.call("tk", "scaling", 2.0)
        self.app = A.App(self.root)
        self.root.geometry("1350x850")
        self.root.update()
        self.app._adapt_layout()
        self.root.update()
        self.assertTrue(self.app._log_visible)
        self.assertGreater(self.app.quick.viewport.winfo_width(), 0)
        self.assertLessEqual(self.app.seq.btn_run.winfo_rooty() + self.app.seq.btn_run.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())
        self.assertGreater(self.app.seq.tv.winfo_height(), 80)

    def test_narrow_form_can_scroll_horizontally(self):
        import tkinter as tk
        from tkinter import ttk
        from i1003.ui.theme import FormViewport
        top = tk.Toplevel(self.root)
        top.geometry("320x220")
        viewport = FormViewport(top, min_width=800)
        viewport.pack(fill="both", expand=True)
        ttk.Entry(viewport.content, width=80).pack()
        self.root.update()
        self.assertTrue(viewport.horizontal.winfo_manager())
        self.assertLess(viewport.canvas.xview()[1], 1)
        viewport.canvas.xview_moveto(1)
        self.assertGreater(viewport.canvas.xview()[0], 0)
        top.destroy()


if __name__ == "__main__":
    unittest.main()
