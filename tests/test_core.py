"""不需要界面的单元测试：python -m unittest discover -s tests"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from i1003.engine.runner import Runner, RunEvents, RunOptions               # noqa: E402
from i1003.model import sequence_io                                          # noqa: E402
from i1003.model.items import FpgaItem, PkgItem, ProgItem, WaitItem, from_dict, hexs  # noqa: E402
from i1003.protocol import fpga, isa                                         # noqa: E402
from i1003.protocol.pkg import Pkg, PkgType, Route, encode                   # noqa: E402
from i1003.recipes import write_test                                         # noqa: E402
from i1003.transport.udp_link import UdpLink                                 # noqa: E402
from tools.fake_board import FakeBoard                                       # noqa: E402

R = Route.from_names("00", "30", 0)


class ProtocolTest(unittest.TestCase):
    def test_known_frames(self):
        # 这几条和对话里手算、实测过的报文一致
        self.assertEqual(hexs(fpga.read_frame(fpga.Addr.CHIP_READY)), "55 D5 00 02 00 00 00 00 00 00 00 00")
        self.assertEqual(hexs(fpga.chip_frame(encode(PkgType.WRITE_REG, 8, 0x00FF00FE, R))),
                         "55 D5 80 03 04 C0 00 08 00 FF 00 FE")
        self.assertEqual(hexs(fpga.chip_frame(encode(PkgType.WRITE_INST, 1, isa.STOP_INST, R))),
                         "55 D5 80 03 05 C0 00 01 70 F0 00 00")

    def test_forbidden_write(self):
        with self.assertRaises(ValueError):
            fpga.write_frame(fpga.Addr.TEST, 1 << 63)

    def test_writeb_matches_i1000(self):
        self.assertEqual(isa.writeb(0, True, 0, 1), 0x40100001)
        self.assertEqual(isa.writeb(0, True, 0, 2), 0x40100002)
        self.assertEqual(isa.writeb(0, False, 0, 1), 0x40000001)   # I1000 forming 用的指令

    def test_wwv(self):
        w = isa.WwvConfig.from_pulse_ms(6.477)
        self.assertEqual(w.word, 0x00FF00FE)
        self.assertAlmostEqual(w.pulse_ms, 6.477, places=3)

    def test_pkg_roundtrip(self):
        b = encode(PkgType.READ_INST, 0x1234, 0xDEADBEEF, Route(1, 2, 3, 0, 1))
        p = Pkg.decode(b)
        self.assertEqual((p.type, p.addr, p.data, p.dx, p.dy, p.rgn), (PkgType.READ_INST, 0x1234, 0xDEADBEEF, 1, 2, 1))


class ModelTest(unittest.TestCase):
    def test_prog_long_tx(self):
        it = ProgItem(start=0, segs=[[0x40100002, 0x0FFF]], stop=True)
        f = it.frames(R)
        self.assertEqual(len(f), 4096)
        self.assertEqual(hexs(f[-1][0]), "55 D5 80 03 05 C0 0F FF 70 F0 00 00")

    def test_json_roundtrip(self):
        items = [FpgaItem(desc="q", addr=2), PkgItem(desc="w", type=4, addr=8, data=5),
                 ProgItem(desc="p", segs=[[1, 3]]), WaitItem(desc="w", ms=10)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            sequence_io.save_json(p, items, {"core": "00"})
            back, h = sequence_io.load_json(p)
        self.assertEqual([x.to_dict() for x in back], [x.to_dict() for x in items])
        self.assertEqual(h["core"], "00")

    def test_netassist_roundtrip_collapses(self):
        items = write_test.plan(write_test.WriteTestSpec(repeat=50)).items
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.ini")
            sequence_io.export_netassist(p, items, R)
            back, _, _ = sequence_io.load_any(p, R)
        progs = [x for x in back if isinstance(x, ProgItem)]
        self.assertEqual(len(progs), 1)
        self.assertEqual(progs[0].count(), 51)

    def test_legacy_items(self):
        it = from_dict({"kind": "batch", "desc": "x", "start": 0, "count": 3, "data": 7, "stop": True})
        self.assertEqual(it.count(), 4)
        it = from_dict({"kind": "fpga", "desc": "q", "ctrl": 2, "data": "0000000000000000"})
        self.assertEqual((it.addr, it.write), (2, False))


class RecipeTest(unittest.TestCase):
    def test_i1000_scene(self):
        p = write_test.plan(write_test.scene("单器件长时间（I1000 实验台：4095 次）"))
        self.assertEqual(p.instructions, 4095)
        self.assertEqual(p.wwv.word, 0x00FF00FE)              # 师姐实操参数
        self.assertEqual(p.wwv.cycles, 64770)
        self.assertEqual(p.first_word, 0x40100002)
        self.assertAlmostEqual(p.est_s, 26.523315, places=6)
        p = write_test.plan(write_test.WriteTestSpec(pulse_ms=6.477))   # I1000 实验台的值
        self.assertEqual(p.wwv.word, 0x00FF00FE)

    def test_hold_time(self):
        p = write_test.plan(write_test.scene("单器件持续选通 8 s（配合 4200 测量）"))
        self.assertEqual(p.instructions, 8000)              # 1 ms × 8000
        with self.assertRaises(write_test.SpecError):
            write_test.plan(write_test.WriteTestSpec(hold_s=9.0, pulse_ms=1.0))

    def test_direct_wwv_fields(self):
        p = write_test.plan(write_test.WriteTestSpec(wwv_base=13, wwv_times=17, repeat=2))
        self.assertEqual(p.wwv.word, 0x0011000D)
        self.assertEqual(p.items[0].data, 0x0011000D)
        self.assertEqual(p.instructions, 2)
        for base, times in ((0, 255), (254, 0), (256, 255), (254, 256)):
            with self.subTest(base=base, times=times), self.assertRaises(write_test.SpecError):
                write_test.plan(write_test.WriteTestSpec(wwv_base=base, wwv_times=times))

    def test_too_many(self):
        with self.assertRaises(write_test.SpecError):
            write_test.plan(write_test.WriteTestSpec(col_from=0, col_to=127, repeat=100))


class Events(RunEvents):
    def __init__(self):
        self.logs = []

    def log(self, tag, head, text):
        self.logs.append((tag, text))


class RunnerTest(unittest.TestCase):
    def _run(self, items, fast, chip_replies=True, port=9180):
        board = FakeBoard(("127.0.0.1", port), ("127.0.0.1", port + 1), chip_replies).start()
        link = UdpLink()
        link.open("127.0.0.1", port + 1, "127.0.0.1", port)
        ev = Events()
        try:
            ok = Runner(link, ev).run(items, RunOptions(R, gap_s=0, fast=fast), [None] * len(items))
        finally:
            link.close()
            board.stop()
            time.sleep(0.05)
        return ok, ev, board

    def test_traversal_fast(self):
        spec = write_test.scene("一行遍历 128 个器件（I1000 traversal）")
        spec.pulse_ms = 0.001
        spec.check_reg8 = spec.check_inst = spec.poll_after = True
        ok, ev, board = self._run(write_test.plan(spec).items, fast=True)
        self.assertTrue(ok)
        self.assertEqual(len(board.inst), 129)
        self.assertEqual(board.inst[128], isa.STOP_INST)
        self.assertIn(("ok", "芯片执行完成，reg[0] = 0x00000080"), ev.logs)

    def test_without_chip_reply(self):
        spec = write_test.WriteTestSpec(repeat=5, pulse_ms=0.001, check_reg8=True)
        ok, ev, board = self._run(write_test.plan(spec).items, fast=False, chip_replies=False, port=9190)
        self.assertFalse(ok)
        self.assertEqual(len(board.inst), 0)       # Stop before programming or starting the core.
        self.assertTrue(any("核对失败" in text for _, text in ev.logs))

    def test_default_write_does_not_require_chip_reply(self):
        spec = write_test.WriteTestSpec(repeat=5, pulse_ms=0.001, remind_4200=False)
        ok, ev, board = self._run(write_test.plan(spec).items, fast=False, chip_replies=False, port=9192)
        self.assertTrue(ok)
        self.assertEqual(len(board.inst), 6)
        self.assertTrue(any("已发送，预计等待结束" in text for _, text in ev.logs))
        self.assertFalse(any("芯片执行完成" in text for _, text in ev.logs))


if __name__ == "__main__":
    unittest.main()
