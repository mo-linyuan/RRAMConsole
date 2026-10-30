"""Offline fault tests: a successful send must never imply verified execution."""
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from i1003.engine.runner import Runner, RunEvents, RunOptions
from i1003.model.items import FpgaItem, FpgaProbeItem, PkgItem, PollItem, RawItem, VerifyItem, WaitItem, from_dict
from i1003.protocol import fpga
from i1003.protocol.pkg import Route, Pkg, encode
from i1003.transport.udp_link import UdpLink
from rram_console.run_record import RunRecord

R = Route()


def reply_to(request, data=1, addr=None, type_=None, route=None):
    sent = Pkg.decode(fpga.parse_frame(request)[2])
    route = route or Route(sent.sx, sent.sy, sent.dx, sent.dy, 2)
    return encode(8 | sent.type if type_ is None else type_, sent.addr if addr is None else addr, data, route)


@contextmanager
def peer(handler):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(.05)
    stopped, received = threading.Event(), []
    events = []
    link = UdpLink(on_receive=lambda kind, data: events.append((kind, data)))
    link.open("127.0.0.1", 0, *server.getsockname())

    def serve():
        while not stopped.is_set():
            try:
                data, address = server.recvfrom(65536)
                received.append(data)
                for response in handler(data):
                    server.sendto(response, address)
            except socket.timeout:
                continue
            except OSError:
                return
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield link, received, events, server
    finally:
        stopped.set()
        link.close()
        thread.join(.3)
        server.close()


class Events(RunEvents):
    def __init__(self):
        self.logs, self.states, self.outcomes = [], [], []
        self.waiting = threading.Event()
    def log(self, tag, head, text):
        self.logs.append(text)
    def item_state(self, row, state):
        self.states.append((row, state))
    def status(self, text):
        if text:
            self.waiting.set()
    def finished(self, ok):
        self.outcomes.append(ok)


class ExecutionSafetyTest(unittest.TestCase):
    def test_bulk_preview_limit_does_not_skip_validation_of_later_words(self):
        from i1003.model.items import ProgItem
        with peer(lambda data: []) as (link, received, _, _):
            item = ProgItem(segs=[[0x40100002, 1], [0x48100002, 1]])  # PE8 is invalid.
            ok, runner, _ = self.run_items(link, [item])
            self.assertFalse(ok)
            self.assertEqual(runner.last_result.sent, 0)
            self.assertEqual(received, [])

    def test_fpga_probe_succeeds_without_chip_reply(self):
        saved = [bytes(8)]
        def respond(data):
            write, _, payload = fpga.parse_frame(data)
            if write:
                saved[0] = payload
                return []
            return [saved[0]]
        with peer(respond) as (link, received, _, _):
            ok, runner, _ = self.run_items(link, [FpgaProbeItem()])
            self.assertTrue(ok)
            self.assertEqual(runner.last_result.outcome, "fpga_checked")
            self.assertIn("尚未验证", runner.last_result.summary)
            self.assertEqual(Pkg.decode(received[0][4:]).type, 0)
            self.assertEqual(len(received), 2)

    def test_fpga_probe_detects_stale_or_wrong_staging(self):
        with peer(lambda data: [] if fpga.parse_frame(data)[0] else [bytes(8)]) as (link, _, _, _):
            ok, runner, events = self.run_items(link, [FpgaProbeItem()])
            self.assertFalse(ok)
            self.assertEqual(runner.last_result.outcome, "failed")
            self.assertTrue(any("暂存不一致" in text for text in events.logs))

    def test_fpga_probe_does_not_consume_chip_reply_as_saved_pkg(self):
        saved = [bytes(8)]
        chip_reply = [None]
        def respond(data):
            write, _, payload = fpga.parse_frame(data)
            if write:
                saved[0], chip_reply[0] = payload, reply_to(data, data=123)
                return []
            return [chip_reply[0], saved[0]]
        with peer(respond) as (link, _, events, _):
            ok, _, _ = self.run_items(link, [FpgaProbeItem()])
            self.assertTrue(ok)
            self.assertEqual([kind for kind, _ in events], ["unmatched", "fpga"])

    def test_fpga_probe_json_roundtrip(self):
        original = FpgaProbeItem(desc="FPGA staging")
        restored = from_dict(original.to_dict())
        self.assertEqual(restored.count(), 2)
        self.assertEqual(restored.frames(R), original.frames(R))

    def test_default_scenes_do_not_generate_chip_readback(self):
        from i1003.recipes import write_test as W
        for name in W.SCENES:
            with self.subTest(scene=name):
                spec = W.scene(name)
                self.assertFalse(spec.check_reg8 or spec.check_inst or spec.poll_after)
                items = W.plan(spec).items
                self.assertFalse(any(isinstance(item, (VerifyItem, PollItem)) for item in items))
                self.assertTrue(all(not isinstance(item, PkgItem) or item.type >= 4 for item in items))

    def test_optional_readback_check_stays_strict(self):
        from i1003.recipes.write_test import readback_check
        items = readback_check()
        self.assertTrue(any(isinstance(item, VerifyItem) for item in items))
        with peer(lambda data: [bytes(7) + b"\x01"] if not fpga.parse_frame(data)[0] else []) as (link, _, _, _):
            ok, runner, _ = self.run_items(link, items)
            self.assertFalse(ok)
            self.assertEqual(runner.last_result.outcome, "failed")

    def run_items(self, link, items):
        events = Events()
        runner = Runner(link, events)
        ok = runner.run(items, RunOptions(R, check_ready=False, gap_s=0), list(range(len(items))))
        return ok, runner, events

    def test_verify_mismatch_stops_before_next_write(self):
        with peer(lambda data: [reply_to(data, data=2)]) as (link, received, _, _):
            ok, runner, events = self.run_items(link, [VerifyItem(addr=8, expect=1), PkgItem(type=4, addr=0, data=1)])
            self.assertFalse(ok)
            self.assertEqual(len(received), 1)
            self.assertEqual(runner.last_result.outcome, "failed")
            self.assertIn((0, "失败"), events.states)

    def test_raw_and_template_ready_both_await_reply(self):
        from i1003.ui.templates import TEMPLATES
        template = next(t for t in TEMPLATES if t.name == "查询芯片 Ready 0002")
        with peer(lambda data: [bytes(7) + b"\x01"]) as (link, received, events, _):
            ok, runner, _ = self.run_items(link, [RawItem(hex=fpga.read_frame(2).hex()), template.make()])
            self.assertTrue(ok)
            self.assertEqual(runner.last_result.sent, 2)
            self.assertEqual([kind for kind, _ in events], ["bit", "bit"])
            self.assertEqual(received[0], received[1])

    def test_probe_link_reports_wire_truth_not_local_bind(self):
        from rram_console.chips.i1003 import I1003Backend
        backend = I1003Backend()
        with peer(lambda data: [bytes(7) + b"\x01"]) as (link, received, _, _):
            ok, detail = backend.probe_link(link)
            self.assertTrue(ok)
            self.assertEqual(detail, "")
        with peer(lambda data: []) as (link, received, _, _):
            ok, detail = backend.probe_link(link)
            self.assertFalse(ok)
            self.assertIn("无回包", detail)
            self.assertIn("重新连接", detail)

    def test_raw_reply_timeout_does_not_fail_or_block_following_items(self):
        # A raw staging write whose payload decodes as a chip READ (TYPE<4)
        # must report the silence and continue, not abort the task.
        raw = RawItem(desc="原始报文", hex=fpga.chip_frame(encode(0, 8, 0, R)).hex())
        follow = PkgItem(type=4, addr=8, data=0x00FF00FE)
        with peer(lambda data: []) as (link, received, rx_kinds, _):
            ok, runner, events = self.run_items(link, [raw, follow])
            self.assertTrue(ok)
            self.assertEqual(runner.last_result.outcome, "sent")
            self.assertEqual(runner.last_result.sent, 2)
            self.assertIn((0, "已发送"), events.states)
            self.assertIn((1, "已发送"), events.states)
            deadline = time.monotonic() + 1  # drain: the last sendto may still be in flight
            while len(received) < 2 and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual(len(received), 2)
            self.assertTrue(any("未等到匹配回包" in text for text in events.logs))

    def test_board_templates_accept_builtin_address_enums(self):
        from i1003.ui.templates import TEMPLATES
        for template in (t for t in TEMPLATES if t.group == "板卡"):
            options = ("读", "写 0", "写 1") if template.fields else (None,)
            for option in options:
                with self.subTest(template=template.name, option=option):
                    item = template.make({"op": option} if option else None)
                    item.validate()
                    self.assertEqual(len(item.frames(R)[0][0]), 12)

    def test_invalid_fpga_addresses_still_rejected(self):
        for addr in (-1, 32768, 2.0, "2", True, None):
            with self.subTest(addr=addr), self.assertRaises(ValueError):
                FpgaItem(addr=addr).validate()
        for addr in (0, 32767, *fpga.Addr):
            FpgaItem(addr=addr).validate()

    def test_real_path_check_preset_executes_with_enum_address(self):
        from i1003.recipes.write_test import path_check
        registers = {}
        last_out = [bytes(8)]
        def respond(data):
            write, addr, payload = fpga.parse_frame(data)
            if not write:
                if addr == fpga.Addr.NOC_OUT:
                    return [last_out[0]]
                return [bytes(7) + b"\x01"]
            last_out[0] = payload
            pkg = Pkg.decode(payload)
            if pkg.type == 4:
                registers[pkg.addr] = pkg.data
                return []
            return [reply_to(data, data=registers.get(pkg.addr, 0))]
        with peer(respond) as (link, received, _, _):
            ok, runner, _ = self.run_items(link, path_check())
            self.assertTrue(ok)
            self.assertEqual(runner.last_result.sent, 5)
            self.assertEqual(received[0], fpga.read_frame(fpga.Addr.CHIP_READY))
            self.assertEqual(runner.last_result.outcome, "fpga_checked")
            writes = [Pkg.decode(fpga.parse_frame(data)[2]) for data in received if fpga.parse_frame(data)[0]]
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0].type, 0)

    def test_plain_chip_read_awaits_chip_reply(self):
        with peer(lambda data: [reply_to(data, data=7)]) as (link, _, events, _):
            ok, _, _ = self.run_items(link, [PkgItem(type=0, addr=8)])
            self.assertTrue(ok)
            self.assertEqual(events[0][0], "chip")

    def test_unrelated_packets_do_not_satisfy_chip_request(self):
        def responses(data):
            return [b"bad", bytes(7) + b"\x01", reply_to(data, addr=9),
                    reply_to(data, type_=9), reply_to(data, route=Route(1, 0, 0, 0)), reply_to(data, data=7)]
        with peer(responses) as (link, _, events, _):
            ok, _, _ = self.run_items(link, [VerifyItem(addr=8, expect=7)])
            self.assertTrue(ok)
            self.assertEqual([kind for kind, _ in events], ["unmatched"] * 5 + ["chip"])

    def test_foreign_sender_cannot_satisfy_request(self):
        foreign = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with peer(lambda data: []) as (link, _, events, _):
                def send_foreign(data, note, quiet):
                    foreign.sendto(bytes(7) + b"\x01", link._sock.getsockname())
                link.on_send = send_foreign
                result = link.request("bit", fpga.read_frame(2), .1)
                self.assertIsNone(result)
                self.assertEqual(events[0][0], "foreign")
        finally:
            foreign.close()

    def test_missing_fpga_reply_is_failure(self):
        with peer(lambda data: []) as (link, _, _, _):
            ok, runner, _ = self.run_items(link, [FpgaItem(addr=2)])
            self.assertFalse(ok)
            self.assertEqual(runner.last_result.outcome, "failed")

    def test_poll_without_reply_is_failure(self):
        with peer(lambda data: []) as (link, _, _, _):
            ok, runner, _ = self.run_items(link, [PollItem(timeout_s=.08)])
            self.assertFalse(ok)
            self.assertEqual(runner.last_result.outcome, "failed")

    def test_close_unblocks_request_and_reopen_is_clean(self):
        with peer(lambda data: []) as (link, _, _, server):
            sent = threading.Event()
            link.on_send = lambda *args: sent.set()
            values = []
            worker = threading.Thread(target=lambda: values.append(link.request("bit", fpga.read_frame(2), 5)))
            worker.start()
            self.assertTrue(sent.wait(1))
            link.close()
            worker.join(.5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(values, [None])
            link.open("127.0.0.1", 0, *server.getsockname())
            self.assertIsNone(link.request("bit", fpga.read_frame(2), .05))

    def test_concurrent_requests_are_serialized(self):
        with peer(lambda data: [reply_to(data, data=Pkg.decode(data[4:]).addr)]) as (link, _, _, _):
            results = {}
            barrier = threading.Barrier(3)
            def request(addr):
                barrier.wait()
                frame = fpga.chip_frame(encode(0, addr, 0, R))
                response = link.request("chip", frame, .5)
                results[addr] = None if response is None else Pkg.decode(response).data
            threads = [threading.Thread(target=request, args=(addr,)) for addr in (8, 9)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(1)
                self.assertFalse(thread.is_alive())
            self.assertEqual(results, {8: 8, 9: 9})

    def test_cancel_final_wait_is_not_success(self):
        with peer(lambda data: []) as (link, _, _, _):
            ev = Events()
            runner = Runner(link, ev)
            self.assertTrue(runner.start([WaitItem(ms=5000)], RunOptions(R, check_ready=False)))
            self.assertTrue(ev.waiting.wait(1))
            runner.stop()
            runner._thread.join(.5)
            self.assertFalse(runner.busy)
            self.assertEqual(runner.last_result.outcome, "cancelled")
            self.assertEqual(ev.outcomes, [False])

    def test_preflight_checks_later_item_before_first_write(self):
        with peer(lambda data: []) as (link, received, _, _):
            ok, runner, _ = self.run_items(link, [PkgItem(type=4, addr=8, data=1), PkgItem(type=4, addr=-1)])
            self.assertFalse(ok)
            self.assertEqual(runner.last_result.sent, 0)
            self.assertEqual(received, [])

    def test_pure_writes_have_no_execution_claim(self):
        with peer(lambda data: []) as (link, _, _, _):
            ok, runner, _ = self.run_items(link, [PkgItem(type=4, addr=8, data=1)])
            self.assertTrue(ok)
            self.assertEqual(runner.last_result.outcome, "sent")
            self.assertEqual(runner.last_result.summary, "报文已发送")

    def test_jsonl_record_preserves_full_packets_and_results(self):
        with tempfile.TemporaryDirectory() as directory:
            record = RunRecord({"chip_family": "i1003", "sequence": [{"kind": "wait", "ms": 1}]}, directory)
            data = bytes(range(256))
            record.write("rx", hex=data.hex(" "))
            record.write("result", outcome="failed")
            record.close()
            rows = [json.loads(line) for line in Path(record.path).read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["event"] for row in rows], ["start", "rx", "result"])
            self.assertEqual(bytes.fromhex(rows[1]["hex"]), data)
            self.assertLessEqual(rows[0]["elapsed_s"], rows[2]["elapsed_s"])
            self.assertTrue(rows[0]["timestamp"].endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
