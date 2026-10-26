"""Deterministic host timing: include Ready, transport and scheduler overhead."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from i1003.engine.runner import Runner, RunEvents, RunOptions
from i1003.model.items import ProgItem
from i1003.protocol.pkg import Route


class Clock:
    def __init__(self):
        self.now = 0.0
    def advance(self, seconds):
        self.now += seconds


class Gate:
    def __init__(self, clock):
        self.clock = clock
    def is_set(self):
        return False
    def wait(self, seconds):
        self.clock.advance(seconds)


class Events(RunEvents):
    def __init__(self):
        self.logs = []
    def log(self, tag, head, text):
        self.logs.append(text)


class DownloadTimingTest(unittest.TestCase):
    def run_download(self, fail_second=False, gap=.02):
        clock, events = Clock(), Events()
        sent = []
        def ready(*args, **kwargs):
            clock.advance(.003)
            return True
        def send(data, *args, **kwargs):
            if fail_second and sent:
                raise OSError("offline send failure")
            sent.append(data)
            clock.advance(.001)
        runner = Runner(SimpleNamespace(send=send, wait_chip_ready=ready), events)
        runner._stop = Gate(clock)
        with patch("i1003.engine.runner.time", SimpleNamespace(monotonic=lambda: clock.now, sleep=clock.advance)):
            ok = runner.run([ProgItem(segs=[[0x40100001, 2]])], RunOptions(Route(), download_gap_s=gap), [0])
        return ok, runner.last_result, events.logs

    def test_download_measurement_includes_ready_and_send_overhead(self):
        ok, result, logs = self.run_download()
        self.assertTrue(ok)
        self.assertEqual(result.sent, 3)
        self.assertAlmostEqual(result.download_s, .072)
        self.assertAlmostEqual(result.elapsed_s, .072)
        self.assertTrue(any("写入间隔预算 0.060 s" in text for text in logs))
        self.assertTrue(any("实际指令写入耗时 0.072 s" in text for text in logs))

    def test_zero_interval_still_has_ready_and_transport_time(self):
        ok, result, _ = self.run_download(gap=0)
        self.assertTrue(ok)
        self.assertAlmostEqual(result.download_s, .012)

    def test_partial_download_records_actual_elapsed_time(self):
        ok, result, logs = self.run_download(fail_second=True)
        self.assertFalse(ok)
        self.assertEqual(result.sent, 1)
        self.assertAlmostEqual(result.download_s, .027)
        self.assertTrue(any("指令写入中断：1 / 3 条" in text for text in logs))


if __name__ == "__main__":
    unittest.main()
