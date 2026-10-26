"""Measure downloads to an in-process loopback peer, never a physical board."""
import json
from pathlib import Path
import tempfile
import time

from i1003.engine.runner import Runner, RunEvents, RunOptions
from i1003.model.items import ProgItem
from i1003.protocol import fpga, isa
from i1003.protocol.pkg import Route, Pkg, encode
from i1003.transport.simulator import SimulatableUdpLink
from rram_console.run_record import RunRecord


def measure(check_ready):
    with tempfile.TemporaryDirectory() as directory:
        record = RunRecord({"simulation": True, "benchmark": "4095 WRITEB plus STOP"}, directory)
        link = SimulatableUdpLink(on_send=lambda data, note, quiet: record.write(
            "tx", hex=data.hex(" "), note=note, quiet=quiet))
        try:
            link.open_simulation("readback")
            runner = Runner(link, RunEvents())
            ok = runner.run([ProgItem(segs=[[0x40000002, 4095]])],
                            RunOptions(Route(), check_ready=check_ready), [0])
            # A final read also acts as an ordered loopback processing barrier.
            reply = link.request("chip", fpga.chip_frame(encode(1, 4095, 0, Route())), 1)
            result = {"simulation": True, "check_ready": check_ready, "control_gap_ms": 20,
                      "download_gap_ms": 0, "frames_sent": runner.last_result.sent,
                      "download_s": round(runner.last_result.download_s, 6),
                      "datagram_frames_received": link._simulator.received_frames,
                      "last_slot_is_stop": reply is not None and Pkg.decode(reply).data == isa.STOP_INST}
            expected_received = 8193 if check_ready else 4097
            if not ok or not result["last_slot_is_stop"] or result["datagram_frames_received"] != expected_received:
                raise RuntimeError("Loopback dropped or misordered frames: " + str(result))
            return result
        finally:
            link.close()
            record.close()


if __name__ == "__main__":
    results = [measure(False), measure(True)]
    output = Path("artifacts/download-timing.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
