"""Offline UI edit benchmark with a 1000-row sequence; sends no packets."""
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


def measure():
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "SETTINGS_FILE", str(Path(folder) / "settings.json")):
        root = tk.Tk()
        app = module.App(root)
        root.geometry("1200x800+30000+30000")
        try:
            app.seq.set_items([FpgaItem(desc="读取Ready {}".format(i), addr=2) for i in range(1000)])
            root.update()
            app.surface.flush()
            root.update()
            result = {"rows": 1000, "simulation": True, "hardware_commands_sent": 0}
            for name in ("interval_edit", "replace_one", "refresh_all"):
                samples = []
                for index in range(8):
                    if name == "replace_one":
                        app.seq.tv.selection_set("500")
                    started = time.perf_counter()
                    if name == "interval_edit":
                        app.route_bar.vars["download_gap"].set(str(index))
                    elif name == "replace_one":
                        app.seq.replace_selected(FpgaItem(desc="replacement {}".format(index), addr=2))
                    else:
                        app.seq.refresh()
                    root.update()
                    samples.append((time.perf_counter() - started) * 1000)
                result[name] = {"median_ms": round(statistics.median(samples), 3), "max_ms": round(max(samples), 3)}
            return result
        finally:
            app.link.close()
            root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = measure()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
