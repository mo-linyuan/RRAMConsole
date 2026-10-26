"""Exercise the simulator over real loopback UDP using the production runner."""
import time
import unittest

from i1003.engine.runner import Runner, RunOptions
from i1003.model.items import FpgaProbeItem, PkgItem, ProgItem, VerifyItem
from i1003.protocol import fpga, isa
from i1003.protocol.pkg import Route, encode, Pkg
from i1003.transport.simulator import SimulatableUdpLink
from tests.test_execution_safety import Events, peer


class SimulatorTest(unittest.TestCase):
    def connect(self, profile="standard"):
        link = SimulatableUdpLink()
        self.addCleanup(link.close)
        link.open_simulation(profile)
        return link

    def test_default_single_cell_recipe_finishes_as_sent_only(self):
        from i1003.recipes.write_test import WriteTestSpec, plan
        link = self.connect()
        items = plan(WriteTestSpec(repeat=1, remind_4200=False)).items
        runner = Runner(link, Events())
        self.assertTrue(runner.run(items, RunOptions(Route(), gap_s=0), [None] * len(items)))
        self.assertEqual(runner.last_result.outcome, "sent")
        self.assertEqual(runner.last_result.summary, "报文已发送")
        self.assertEqual([item.kind for item in items], ["pkg", "prog", "pkg"])
        self.assertEqual(runner.last_result.sent, 4)  # reg8, WRITEB, STOP, start

    def test_standard_profile_keeps_chip_reads_silent_but_fpga_probe_works(self):
        link = self.connect()
        self.assertTrue(link.is_simulation)
        self.assertEqual(link.endpoints[0], "127.0.0.1")
        self.assertEqual(link.endpoints[2], "127.0.0.1")
        self.assertEqual(link.read_bit(2), 1)
        events = Events()
        runner = Runner(link, events)
        self.assertTrue(runner.run([FpgaProbeItem()], RunOptions(Route(), gap_s=0), [0]))
        self.assertEqual(runner.last_result.outcome, "fpga_checked")
        self.assertIsNone(link.request("chip", fpga.chip_frame(encode(0, 8, 0, Route())), .05))

    def test_readback_profile_verifies_registers_and_instruction_download(self):
        link = self.connect("readback")
        events = Events()
        runner = Runner(link, events)
        items = [PkgItem(type=4, addr=8, data=0x00FF00FE), VerifyItem(addr=8, expect=0x00FF00FE),
                 ProgItem(start=3, segs=[[0x40100001, 2]])]
        self.assertTrue(runner.run(items, RunOptions(Route(), gap_s=0), [0, 1, 2]))
        for address, value in [(3, 0x40100001), (4, 0x40100001), (5, isa.STOP_INST)]:
            reply = link.request("chip", fpga.chip_frame(encode(1, address, 0, Route())), .3)
            self.assertIsNotNone(reply)
            self.assertEqual(Pkg.decode(reply).data, value)
        self.assertEqual(runner.last_result.outcome, "checked")

    def test_registers_are_isolated_by_route_and_object(self):
        link = self.connect("readback")
        target = Route(dx=1, dy=2, rgn=2)
        link.send(fpga.chip_frame(encode(4, 8, 73, target)))
        for route, kind, expected in [(target, 0, 73), (Route(), 0, 0), (target, 1, 0)]:
            reply = link.request("chip", fpga.chip_frame(encode(kind, 8, 0, route)), .3)
            self.assertEqual(Pkg.decode(reply).data, expected)

    def test_start_never_fabricates_execution_end(self):
        link = self.connect("readback")
        link.send(fpga.chip_frame(encode(4, isa.REG_STATUS, isa.START_VALUE, Route())))
        reply = link.request("chip", fpga.chip_frame(encode(0, isa.REG_STATUS, 0, Route())), .3)
        self.assertEqual(Pkg.decode(reply).data, isa.START_VALUE)
        self.assertFalse(Pkg.decode(reply).data & isa.END_FLAG)

    def test_ready_low_stops_runner_before_program_download(self):
        link = self.connect("not_ready")
        runner = Runner(link, Events())
        self.assertFalse(runner.run([ProgItem(segs=[[0x40100001, 1]])],
                                    RunOptions(Route(), gap_s=0, ready_wait_s=.08), [0]))
        self.assertEqual(runner.last_result.sent, 0)
        self.assertEqual(runner.last_result.outcome, "failed")

    def test_timeout_and_deterministic_loss(self):
        silent = self.connect("timeout")
        self.assertIsNone(silent.read_bit(2, timeout=.05))
        lossy = self.connect("loss")
        self.assertEqual(lossy.read_bit(2, timeout=.1), 1)
        self.assertIsNone(lossy.read_bit(2, timeout=.05))
        self.assertEqual(lossy.read_bit(2, timeout=.1), 1)

    def test_delayed_reply_and_close_cancel_pending_schedule(self):
        link = self.connect("delay")
        started = time.monotonic()
        self.assertEqual(link.read_bit(2, timeout=1.4), 1)
        self.assertGreaterEqual(time.monotonic() - started, .75)
        simulator = link._simulator
        link.send(fpga.read_frame(2))
        link.close()
        self.assertFalse(simulator._thread.is_alive())
        self.assertFalse(link.is_open)

    def test_malformed_datagram_is_ignored_and_server_survives(self):
        link = self.connect()
        link.send(fpga.write_frame(1, 0) + b"broken")
        self.assertEqual(link.read_bit(1, timeout=.3), 1)
        self.assertEqual(link._simulator.invalid_datagrams, 1)

    def test_reconnect_resets_memory_and_real_link_uses_original_peer(self):
        link = self.connect("readback")
        link.send(fpga.chip_frame(encode(4, 8, 19, Route())))
        with self.assertRaises(RuntimeError):
            link.open_simulation()
        link.close()
        link.open_simulation("readback")
        reply = link.request("chip", fpga.chip_frame(encode(0, 8, 0, Route())), .3)
        self.assertEqual(Pkg.decode(reply).data, 0)
        link.close()
        with peer(lambda data: [bytes(7) + b"\x01"]) as (_, _, _, server):
            link.open("127.0.0.1", 0, *server.getsockname())
            self.assertFalse(link.is_simulation)
            self.assertEqual(link.read_bit(2), 1)


if __name__ == "__main__":
    unittest.main()
