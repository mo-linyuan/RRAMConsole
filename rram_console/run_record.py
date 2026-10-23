"""Append-only local run records, independent of chip family and Tk."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
import uuid

RUNS_DIR = Path.home() / ".rram_console" / "runs"


class RunRecord:
    def __init__(self, metadata, directory=RUNS_DIR):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.path = directory / (stamp + "-" + uuid.uuid4().hex[:8] + ".jsonl")
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._file = self.path.open("x", encoding="utf-8")
        try:
            self.write("start", schema_version=1, **metadata)
        except Exception:
            self._file.close()
            raise

    def write(self, event, **fields):
        with self._lock:
            if self._file.closed:
                return
            record = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                      "elapsed_s": time.monotonic() - self._start, "event": event, **fields}
            self._file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            # Preserve each packet even if the process exits unexpectedly.
            self._file.flush()

    def close(self):
        with self._lock:
            self._file.close()
