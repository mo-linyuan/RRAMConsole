"""Cancel downloads, pending replies and waits through the real GUI button."""
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from i1003.engine.runner import Runner, RunOptions
from i1003.model.items import PkgItem, ProgItem, WaitItem
from i1003.protocol import fpga
from i1003.protocol.pkg import Route
from tests.test_execution_safety import Events
from tests.test_ui_smoke import HAS_DISPLAY


class DownloadStopTest(unittest.TestCase):
    def test_cancel_download_does_not_send_later_start(self):
        first = threading.Event()
        sent = []
        def send(data, *args, **kwargs):
            sent.append(data)
            first.set()
        link = SimpleNamespace(send=send, cancel_pending=lambda: None)
        runner = Runner(link, Events())
        items = [ProgItem(segs=[[0x40000002, 4095]]), PkgItem(type=4, addr=0, data=1)]
        self.assertTrue(runner.start(items, RunOptions(Route(), check_ready=False, download_gap_s=.2)))
        self.assertTrue(first.wait(1))
        runner.stop()
        runner._thread.join(1)
        self.assertFalse(runner.busy)
        self.assertEqual(runner.last_result.outcome, "cancelled")
        self.assertEqual(len(sent), 1)

    def test_instruction_slot_and_device_address_match_given_packet_bytes(self):
        frames = ProgItem(segs=[[0x40000002, 4095]]).frames(Route())
        self.assertEqual(len(frames), 4096)
        self.assertEqual(frames[4090][0], bytes.fromhex("55 D5 80 03 05 C0 0F FA 40 00 00 02"))
        self.assertEqual(frames[4094][0], bytes.fromhex("55 D5 80 03 05 C0 0F FE 40 00 00 02"))
        self.assertEqual(frames[4095][0], bytes.fromhex("55 D5 80 03 05 C0 0F FF 70 F0 00 00"))


@unittest.skipUnless(HAS_DISPLAY, "没有图形环境")
class StopButtonTest(unittest.TestCase):
    def test_native_button_stops_all_three_phases_and_is_not_behind_logs(self):
        import tkinter as tk
        import i1003.ui.app as A
        from i1003.transport.simulator import PROFILES
        from rram_console.run_record import RunRecord
        for phase in ("download", "ready", "wait"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory, \
                    patch.object(A, "SETTINGS_FILE", str(Path(directory) / "settings.json")), \
                    patch.object(A, "RunRecord", lambda metadata: RunRecord(metadata, directory)):
                root = tk.Tk()
                root.geometry("1100x800+30000+30000")
                app = A.App(root)
                try:
                    app.conn.mode.set("离线模拟")
                    key = "timeout" if phase == "ready" else "standard"
                    app.conn.profile.set(next(label for label, value in PROFILES.items() if value == key))
                    app.conn._refresh_mode()
                    app._toggle_connection()
                    app.route_bar.vars["ready"].set(phase == "ready")
                    app.route_bar.vars["download_gap"].set("20")
                    items = [WaitItem(ms=10000)] if phase == "wait" else [
                        ProgItem(segs=[[0x40000002, 4095]]), PkgItem(type=4, addr=0, data=1)]
                    app.seq.set_items(items)
                    # Leave enough time for native window layout before the
                    # click: this tests cancellation, not the 1s timeout race.
                    with patch.object(app.route_bar, "options", return_value=replace(
                            app.route_bar.options(), ready_wait_s=10)):
                        self.assertTrue(app.run(items))
                    root.update()
                    self.assertFalse(app.seq.btn_stop.instate(["disabled"]))
                    # Control completion must overtake a large visible-log backlog.
                    for index in range(1200):
                        app.q.put(("log", "info", "test", str(index)))
                    button = app.seq.btn_stop
                    button.event_generate("<Enter>")
                    button.event_generate("<ButtonPress-1>", x=5, y=5)
                    button.event_generate("<ButtonRelease-1>", x=5, y=5)
                    deadline = time.monotonic() + 1.5
                    while app.is_busy() and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.005)
                    self.assertFalse(app.is_busy())
                    self.assertEqual(app.runner.last_result.outcome, "cancelled")
                    self.assertIn("已停止", app.seq.result_text.get())
                    self.assertEqual(list(Path(directory).glob("*.jsonl")), [])
                    self.assertFalse(any(key[3:] == (0, 0) and value == 1
                                         for key, value in app.link._simulator._memory.items()))
                finally:
                    app.runner.stop()
                    app.runner._thread.join(1)
                    app.link.close()
                    root.destroy()
