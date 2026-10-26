"""Offline resize/sash benchmark. Timings measure Tk updates, not display FPS."""
import argparse
import cProfile
import json
from pathlib import Path
import statistics
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from i1003.ui import app as module


def measure(frames=90):
    with tempfile.TemporaryDirectory() as directory, patch.object(module, "SETTINGS_FILE", str(Path(directory) / "settings.json")):
        root = tk.Tk()
        root.tk.call("tk", "scaling", 96 / 72)
        app = module.App(root)
        root.geometry("1380x900+30000+30000")
        root.update()
        print("Initial layout ready", flush=True)
        # Let the initial layout settle before measuring repeated input.
        until = time.monotonic() + .25
        while time.monotonic() < until:
            root.update()
            time.sleep(.005)
        app._log_override = True
        app._set_log_visible(True)
        root.update()
        results = {}
        profile = cProfile.Profile()
        try:
            for scenario in ("window", "workspace_sash", "log_sash", "preview_drag", "template_sash"):
                print("Measuring " + scenario, flush=True)
                if scenario == "template_sash":
                    app.nb.select(app.tab_templates)
                    root.update()
                if scenario == "preview_drag":
                    pane = app.main_split
                    origin = pane.sashpos(0)
                    drag_x, drag_y = origin + 2, pane.winfo_height() // 2
                    pane.event_generate("<ButtonPress-1>", x=drag_x, y=drag_y)
                    root.update()
                samples = []
                profile.enable()
                for step in range(frames):
                    offset = (step % 30) * 6
                    started = time.perf_counter()
                    if scenario == "window":
                        root.geometry("{}x{}".format(1200 + offset, 780 + offset // 2))
                    elif scenario == "workspace_sash":
                        app.main_split.sashpos(0, 680 + offset)
                    elif scenario == "log_sash":
                        app.workspace.sashpos(0, 400 + offset)
                    elif scenario == "preview_drag":
                        pane.event_generate("<B1-Motion>", x=drag_x + offset, y=drag_y, state=0x100)
                    else:
                        app.templates.split.sashpos(0, 200 + offset)
                    root.update()
                    samples.append((time.perf_counter() - started) * 1000)
                profile.disable()
                results[scenario] = dict(median_ms=round(statistics.median(samples), 3),
                    p95_ms=round(sorted(samples)[int((len(samples)-1)*.95)], 3),
                    max_ms=round(max(samples), 3), frames=frames)
                if scenario == "window":
                    # Include deferred final layout separately; this benchmark
                    # must not pretend the omitted redraw disappeared.
                    started = time.perf_counter()
                    deadline = time.monotonic() + 2
                    while app.surface._resize_job is not None and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.005)
                    root.update()
                    results[scenario]["final_settle_ms"] = round((time.perf_counter() - started) * 1000, 3)
                if scenario == "preview_drag":
                    started = time.perf_counter()
                    pane.event_generate("<ButtonRelease-1>", x=drag_x + offset, y=drag_y)
                    root.update()
                    results[scenario]["release_ms"] = round((time.perf_counter() - started) * 1000, 3)
            callbacks = []
            import pstats
            for (filename, line, name), (primitive, calls, own, cumulative, _) in pstats.Stats(profile).stats.items():
                if "i1003" in filename.replace("\\", "/"):
                    callbacks.append(dict(file=Path(filename).name, function=name, calls=calls,
                                          cumulative_ms=round(cumulative * 1000, 3)))
            results["callbacks"] = sorted(callbacks, key=lambda row: row["cumulative_ms"], reverse=True)[:20]
            return results
        finally:
            app.link.close()
            root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames", type=int, default=90)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = measure(args.frames)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "callbacks"}, indent=2))
