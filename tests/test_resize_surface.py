"""Window resize bursts must not repeatedly reflow the full child hierarchy."""
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from tests.test_ui_smoke import HAS_DISPLAY


@unittest.skipUnless(HAS_DISPLAY, "没有图形环境")
class ResizeSurfaceTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from i1003.ui.resize_surface import ResizeSurface
        self.root = tk.Tk()
        self.root.geometry("900x600")
        self.surface = ResizeSurface(self.root, 900, 600)
        tk.Label(self.surface, text="content").pack(fill="both", expand=True)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_size_burst_is_applied_once_and_child_events_are_ignored(self):
        with patch.object(self.surface, "place_configure", wraps=self.surface.place_configure) as place:
            for width in range(1000, 1200, 10):
                self.surface._queue_resize(SimpleNamespace(widget=self.root, width=width, height=700))
            self.surface._queue_resize(SimpleNamespace(widget=self.surface, width=1, height=1))
            place.assert_not_called()
            self.assertEqual(self.surface._applied, (900, 600))
            self.assertIsNotNone(self.surface._resize_job)
            self.assertEqual(len(self.root.tk.call("after", "info")), 1)
            self.surface.flush()
            place.assert_called_once_with(width=1190, height=700)
            self.assertIsNone(self.surface._resize_job)
            self.assertEqual(self.surface._applied, (1190, 700))

    def test_real_window_resizes_finish_with_correct_content_and_input(self):
        for width, height in ((1030, 710), (820, 540), (1150, 760)):
            self.root.geometry("{}x{}".format(width, height))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                self.root.update()
                if self.surface._applied == (width, height):
                    break
                time.sleep(.005)
            self.assertEqual(self.surface._applied, (width, height))
            self.root.update()
            self.assertEqual((self.surface.winfo_width(), self.surface.winfo_height()), (width, height))
            heartbeat = []
            self.root.after_idle(lambda: heartbeat.append(True))
            self.root.update()
            self.assertTrue(heartbeat)
            self.assertIsNone(self.root.grab_current())

    def test_minimized_size_is_ignored_and_pending_job_cancels_on_destroy(self):
        self.surface._queue_resize(SimpleNamespace(widget=self.root, width=0, height=0))
        self.assertIsNone(self.surface._resize_job)
        self.surface._queue_resize(SimpleNamespace(widget=self.root, width=1100, height=700))
        job = self.surface._resize_job
        self.surface.destroy()
        self.assertIsNone(self.surface._resize_job)
        self.assertNotIn(job, self.root.tk.call("after", "info"))

    def test_maximize_and_restore_eventually_match_window_bounds(self):
        import sys
        if sys.platform != "win32":
            self.skipTest("Windows window state test")
        for state in ("zoomed", "normal"):
            self.root.state(state)
            if state == "normal":
                self.root.geometry("900x600")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                self.root.update()
                target = (self.root.winfo_width(), self.root.winfo_height())
                if self.surface._applied == target and self.surface._resize_job is None:
                    break
                time.sleep(.005)
            self.assertEqual(self.surface._applied, target)
            self.assertIsNone(self.root.grab_current())
