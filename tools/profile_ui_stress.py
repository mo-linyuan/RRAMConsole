"""Offline startup/list/log/scroll responsiveness probe; no board connection."""
import argparse
import json
from pathlib import Path
import statistics
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from i1003.ui import app as module
from i1003.model.items import FpgaItem


def measure(synchronous=False):
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "SETTINGS_FILE", str(Path(folder) / "settings.json")):
        root = tk.Tk()
        started = time.perf_counter()
        app = module.App(root)
        root.geometry("1200x800+30000+30000")
        root.update()
        app.surface.flush()
        root.update()
        result = {"simulation": True, "hardware_commands_sent": 0,
                  "startup_ms": round((time.perf_counter()-started)*1000, 3), "synchronous_list": synchronous}
        heartbeat_job = None
        try:
            if synchronous:
                app.seq._render_rows = app.seq._paint_rows
            gaps = []
            previous = time.perf_counter()
            def heartbeat():
                nonlocal previous, heartbeat_job
                now = time.perf_counter()
                gaps.append((now-previous)*1000)
                previous = now
                heartbeat_job = root.after(5, heartbeat)
            items = [FpgaItem(addr=2, desc="Ready {}".format(index)) for index in range(5000)]
            previous = started = time.perf_counter()
            heartbeat_job = root.after(5, heartbeat)
            app.seq.set_items(items)
            result["load_request_ms"] = round((time.perf_counter()-started)*1000, 3)
            deadline = time.monotonic() + 10
            while app.seq.rendering and time.monotonic() < deadline:
                root.update()
                time.sleep(.001)
            root.update()
            result["load_complete_ms"] = round((time.perf_counter()-started)*1000, 3)
            result["list_max_heartbeat_gap_ms"] = round(max(gaps or [0]), 3)
            assert not app.seq.rendering and len(app.seq.tv.get_children()) == 5000
            gaps.clear()
            previous = started = time.perf_counter()
            for index in range(5000):
                app.log("recv", "压力测试", "{:04d} 00 00 00 00 00 00 00 01".format(index))
            root.after_cancel(app._pump_job)
            app._pump()
            deadline = time.monotonic() + 10
            while not app.q.empty() and time.monotonic() < deadline:
                root.update()
                time.sleep(.001)
            root.update()
            result["logs_5000_ms"] = round((time.perf_counter()-started)*1000, 3)
            result["logs_max_heartbeat_gap_ms"] = round(max(gaps or [0]), 3)
            assert app.q.empty()
            samples = []
            for _ in range(30):
                started = time.perf_counter()
                app.logp.text.yview_scroll(-3, "units")
                root.update()
                samples.append((time.perf_counter()-started)*1000)
            result["scroll_median_ms"] = round(statistics.median(samples), 3)
            result["scroll_max_ms"] = round(max(samples), 3)
            return result
        finally:
            if heartbeat_job:
                root.after_cancel(heartbeat_job)
            app.link.close()
            root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sync-render", action="store_true", help="Compare with a synchronous list paint")
    args = parser.parse_args()
    result = measure(args.sync_render)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
